"""The LLM client without a database: request checks, the request hash, the
JSON-schema check with its one retry, and provider errors. Calls without a job touch no budget or usage, so these
tests run on an engine that never connects; budgets and usage are in `tests/db/test_llm_client.py`."""

import asyncio
import hashlib
import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.llm.client import (
    AnsweredCall,
    LLMRequest,
    LLMResponse,
    MeteredClient,
    OutputCut,
    ProviderError,
    ProviderReply,
    redacted,
    request_hash,
)
from tests.support.fake_llm import FakeProvider

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

REQUEST = LLMRequest(
    prompt_kind="c_extract_detail",
    model_class="fast",
    system="system prompt",
    user="user prompt",
    output_schema=SCHEMA,
    max_output_tokens=256,
    job_id=None,
)


def reply(text: str, tokens_in: int = 10, tokens_out: int = 3) -> ProviderReply:
    return ProviderReply(model="fake-model", text=text, tokens_in=tokens_in, tokens_out=tokens_out)


def complete(provider: FakeProvider, req: LLMRequest = REQUEST) -> LLMResponse:
    return complete_with([provider], req)


def complete_with(providers: list[FakeProvider], req: LLMRequest = REQUEST) -> LLMResponse:
    # The engine is never connected: a request without a job has no budget and records no usage.
    client = MeteredClient(providers, create_async_engine("postgresql+asyncpg://127.0.0.1/unused"))
    return asyncio.run(client.complete_json(req))


# --- the request hash ---


def test_the_hash_is_sha256_of_the_canonical_request() -> None:
    canonical = json.dumps(
        ["c_extract_detail", "fast", "system prompt", "user prompt", SCHEMA],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert request_hash(REQUEST) == hashlib.sha256(canonical.encode()).hexdigest()


# --- completing a request ---


def test_a_valid_reply_becomes_the_response() -> None:
    provider = FakeProvider([reply('{"summary": "a summary"}', tokens_in=12, tokens_out=4)])

    response = complete(provider)

    assert response.model_dump(exclude={"latency_ms"}) == {
        "data": {"summary": "a summary"},
        "provider": "fake",
        "model": "fake-model",
        "tokens_in": 12,
        "tokens_out": 4,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "request_hash": request_hash(REQUEST),
        "retried": (),
    }
    [call] = provider.calls
    assert (call.model_class, call.system, call.user, call.output_schema, call.max_output_tokens) == (
        "fast",
        "system prompt",
        "user prompt",
        SCHEMA,
        256,
    )


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("not json", "not JSON"),
        ('["summary"]', "not a JSON object"),
        ('{"summary": 3}', "3 is not of type 'string'"),
    ],
)
def test_an_invalid_reply_is_retried_once_with_the_error_appended(text: str, error: str) -> None:
    provider = FakeProvider([reply(text), reply('{"summary": "fixed"}', tokens_in=20, tokens_out=5)])

    response = complete(provider)

    assert (response.data, response.tokens_in, response.tokens_out) == ({"summary": "fixed"}, 20, 5)
    assert response.request_hash == request_hash(REQUEST)
    first, retry = provider.calls
    assert first.user == "user prompt"
    assert retry.user.startswith("user prompt\n\n")
    assert error in retry.user
    assert (retry.system, retry.output_schema) == (first.system, first.output_schema)


# --- failover ---


def test_a_provider_that_does_not_answer_fails_over_to_the_next() -> None:
    down = FakeProvider([ProviderError("429 rate limited")], name="first")
    up = FakeProvider([reply('{"summary": "s"}')], name="second")

    response = complete_with([down, up])

    assert (response.provider, response.data) == ("second", {"summary": "s"})
    assert (len(down.calls), up.calls) == (1, down.calls)


# --- a reply cut at its token cap, and the calls a failure was charged for (F29, F30) ---


def test_a_reply_cut_at_its_token_cap_is_not_retried() -> None:
    # The retry would ask the same with the same cap, and run into it again.
    provider = FakeProvider([ProviderReply(model="fake-model", text='{"summ', tokens_in=9, tokens_out=256, cut=True)])

    with pytest.raises(OutputCut, match="stopped at its cap of 256 output tokens") as cut:
        complete(provider)

    assert len(provider.calls) == 1
    assert (cut.value.field_reason, cut.value.cause()) == ("llm_output_invalid", str(cut.value))
    assert cut.value.answered == (
        AnsweredCall(
            provider="fake", model="fake-model", request_hash=request_hash(REQUEST), tokens_in=9, tokens_out=256
        ),
    )


# --- a provider's refusal is logged (F33) ---


def test_a_secret_is_redacted_from_a_message() -> None:
    assert redacted("bad key sk-123 given", "sk-123") == "bad key [redacted] given"
    assert redacted("no key here", "") == "no key here"
