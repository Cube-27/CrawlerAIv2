"""The LLM client without a database (SPEC-06 §4.2, §4.6, §4.7): request checks, the request hash (INV-10), the
JSON-schema check with its one retry, and provider errors. Calls without a job touch no budget or usage, so these
tests run on an engine that never connects; budgets and usage (INV-23) are in `tests/db/test_llm_client.py`."""

import asyncio
import hashlib
import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId
from crawlerai.llm.client import (
    LLMRequest,
    LLMResponse,
    MeteredClient,
    OutputInvalid,
    ProviderError,
    ProviderReply,
    ProviderUnavailable,
    is_transient,
    request_hash,
)
from crawlerai.llm.providers.fake import FakeProvider

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}

REQUEST = LLMRequest(
    prompt_kind="c_prefill",
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


# --- the request ---


@pytest.mark.parametrize(
    "schema",
    [
        {**SCHEMA, "additionalProperties": True},
        {key: value for key, value in SCHEMA.items() if key != "additionalProperties"},
        {"type": "array", "items": {"type": "string"}},
    ],
)
def test_a_root_that_is_not_a_closed_object_is_refused(schema: dict[str, Any]) -> None:
    # §4.6: a model could otherwise add fields that downstream code picks up.
    fields = REQUEST.model_dump() | {"output_schema": schema}
    with pytest.raises(ValidationError, match="additionalProperties"):
        LLMRequest.model_validate(fields)


def test_an_invalid_json_schema_is_refused() -> None:
    fields = REQUEST.model_dump() | {"output_schema": {"type": "no-such-type"}}
    with pytest.raises(ValidationError, match="output_schema"):
        LLMRequest.model_validate(fields)


def test_an_unknown_prompt_kind_is_refused() -> None:
    fields = REQUEST.model_dump() | {"prompt_kind": "free_text"}
    with pytest.raises(ValidationError, match="prompt_kind"):
        LLMRequest.model_validate(fields)


# --- the request hash (INV-10) ---


def test_the_hash_is_sha256_of_the_canonical_request() -> None:
    canonical = json.dumps(
        ["c_prefill", "fast", "system prompt", "user prompt", SCHEMA],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert request_hash(REQUEST) == hashlib.sha256(canonical.encode()).hexdigest()


def test_the_hash_ignores_schema_key_order() -> None:
    reordered = REQUEST.model_copy(update={"output_schema": dict(reversed(SCHEMA.items()))})
    assert request_hash(reordered) == request_hash(REQUEST)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("prompt_kind", "c_extract_detail"),
        ("model_class", "strong"),
        ("system", "system prompt "),
        ("user", "user prompt."),
        ("output_schema", {"type": "object"}),
    ],
)
def test_each_part_of_the_request_changes_the_hash(field: str, value: Any) -> None:
    assert request_hash(REQUEST.model_copy(update={field: value})) != request_hash(REQUEST)


def test_the_token_cap_and_the_job_do_not_change_the_hash() -> None:
    # A recording replays for any job, and the cap bounds the reply rather than shaping the prompt.
    other = REQUEST.model_copy(update={"max_output_tokens": 1, "job_id": JobId(uuid7())})
    assert request_hash(other) == request_hash(REQUEST)


@given(st.text(), st.text(), st.text(), st.text())
def test_parts_cannot_run_into_each_other(system_a: str, user_a: str, system_b: str, user_b: str) -> None:
    # Moving text between two parts never keeps the hash: the parts are a JSON array, not a concatenation.
    a = REQUEST.model_copy(update={"system": system_a, "user": user_a})
    b = REQUEST.model_copy(update={"system": system_b, "user": user_b})
    assert (request_hash(a) == request_hash(b)) == ((system_a, user_a) == (system_b, user_b))


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
        "request_hash": request_hash(REQUEST),
    }
    [call] = provider.calls
    assert (call.model_class, call.system, call.user, call.output_schema, call.max_output_tokens) == (
        "fast",
        "system prompt",
        "user prompt",
        SCHEMA,
        256,
    )


@pytest.mark.parametrize(("model_class", "timeout_s"), [("fast", 60), ("strong", 120)])
def test_the_timeout_follows_the_model_class(model_class: str, timeout_s: int) -> None:
    provider = FakeProvider([reply('{"summary": "s"}')])
    complete(provider, REQUEST.model_copy(update={"model_class": model_class}))
    assert [call.timeout_s for call in provider.calls] == [timeout_s]


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("not json", "not JSON"),
        ('["summary"]', "not a JSON object"),
        ('{"summary": 3}', "3 is not of type 'string'"),
        ('{"summary": "s", "extra": 1}', "Additional properties are not allowed"),
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


def test_a_second_invalid_reply_raises_output_invalid() -> None:
    provider = FakeProvider([reply("not json"), reply('{"summary": 3}')])
    with pytest.raises(OutputInvalid, match="3 is not of type 'string'"):
        complete(provider)
    assert len(provider.calls) == 2


def test_a_provider_error_raises_provider_unavailable() -> None:
    provider = FakeProvider([ProviderError("503 from the provider")])
    with pytest.raises(ProviderUnavailable, match="503 from the provider"):
        complete(provider)


def test_the_fake_provider_fails_when_its_script_runs_out() -> None:
    provider = FakeProvider([])
    with pytest.raises(ProviderUnavailable, match="no scripted reply"):
        complete(provider)


# --- failover (§4.2) ---


def test_a_provider_that_does_not_answer_fails_over_to_the_next() -> None:
    down = FakeProvider([ProviderError("429 rate limited")], name="first")
    up = FakeProvider([reply('{"summary": "s"}')], name="second")

    response = complete_with([down, up])

    assert (response.provider, response.data) == ("second", {"summary": "s"})
    assert (len(down.calls), up.calls) == (1, down.calls)


def test_the_first_provider_answers_without_asking_the_next() -> None:
    first = FakeProvider([reply('{"summary": "s"}')], name="first")
    second = FakeProvider([], name="second")

    assert complete_with([first, second]).provider == "first"
    assert second.calls == []


def test_when_neither_provider_answers_both_errors_are_reported() -> None:
    providers = [FakeProvider([ProviderError(f"503 from {name}")], name=name) for name in ("a", "b")]

    with pytest.raises(ProviderUnavailable, match=r"^a: 503 from a; b: 503 from b$"):
        complete_with(providers)
    assert [len(provider.calls) for provider in providers] == [1, 1]


def test_the_retry_after_an_invalid_reply_asks_the_first_provider_again() -> None:
    first = FakeProvider([reply("not json"), reply('{"summary": "fixed"}')], name="first")
    second = FakeProvider([], name="second")

    response = complete_with([first, second])

    assert (response.provider, response.data, len(first.calls), second.calls) == (
        "first",
        {"summary": "fixed"},
        2,
        [],
    )


@pytest.mark.parametrize("count", [0, 3])
def test_a_client_has_one_or_two_providers(count: int) -> None:
    # A call fails over at most once, so a third provider would never be asked.
    providers = [FakeProvider([], name=str(index)) for index in range(count)]
    engine = create_async_engine("postgresql+asyncpg://127.0.0.1/unused")
    with pytest.raises(ValueError, match="one or two providers"):
        MeteredClient(providers, engine)


@pytest.mark.parametrize(
    ("status", "transient"),
    [(408, True), (429, True), (500, True), (503, True), (529, True), (599, True)]
    + [(status, False) for status in (200, 400, 401, 403, 404, 413, 422, 600)],
)
def test_only_timeouts_rate_limits_and_server_errors_are_transient(status: int, transient: bool) -> None:
    assert is_transient(status) is transient
