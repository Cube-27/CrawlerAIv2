"""The LLM client without a database (SPEC-06 §4.2, §4.6, §4.7): request checks, the request hash (INV-10), the
JSON-schema check with its one retry, and provider errors. Calls without a job touch no budget or usage, so these
tests run on an engine that never connects; budgets and usage (INV-23) are in `tests/db/test_llm_client.py`."""

import asyncio
import hashlib
import json
import logging
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.ids import uuid7
from crawlerai.core.retry import is_transient
from crawlerai.db.models import JobId
from crawlerai.llm import client as client_module
from crawlerai.llm.client import (
    AnsweredCall,
    LLMRequest,
    LLMResponse,
    MeteredClient,
    OutputCut,
    OutputInvalid,
    ProviderError,
    ProviderRefused,
    ProviderReply,
    ProviderUnavailable,
    redacted,
    request_hash,
)
from crawlerai.llm.providers.fake import FakeProvider, ScriptedClient

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


def _no_x(data: dict[str, Any]) -> str | None:
    return "the summary holds an x" if "x" in str(data["summary"]) else None


def test_a_reply_the_role_check_refuses_takes_the_same_one_retry() -> None:
    provider = FakeProvider([reply('{"summary": "x"}'), reply('{"summary": "good"}')])
    client = MeteredClient([provider], create_async_engine("postgresql+asyncpg://127.0.0.1/unused"))

    response = asyncio.run(client.complete_json(REQUEST, check=_no_x))

    assert response.data == {"summary": "good"}
    assert "the summary holds an x" in provider.calls[1].user


def test_a_schema_mismatch_then_a_refused_reply_is_two_calls_then_output_invalid() -> None:
    provider = FakeProvider([reply('{"summary": 3}'), reply('{"summary": "x"}'), reply('{"summary": "ok"}')])
    client = MeteredClient([provider], create_async_engine("postgresql+asyncpg://127.0.0.1/unused"))
    call = client.complete_json(REQUEST, check=_no_x)

    with pytest.raises(OutputInvalid, match="the summary holds an x"):
        asyncio.run(call)
    assert len(provider.calls) == 2


def test_the_scripted_client_retries_a_reply_the_role_check_refuses_as_the_client_does() -> None:
    client = ScriptedClient({"summary": "x"}, {"summary": "good"})

    response = asyncio.run(client.complete_json(REQUEST, check=_no_x))

    assert (response.data, len(client.requests)) == ({"summary": "good"}, 2)


def test_the_scripted_client_raises_output_invalid_when_the_retry_is_refused_too() -> None:
    client = ScriptedClient({"summary": "x"}, {"summary": "xx"}, {"summary": "good"})
    call = client.complete_json(REQUEST, check=_no_x)

    with pytest.raises(OutputInvalid, match="the summary holds an x"):
        asyncio.run(call)
    assert len(client.requests) == 2


def test_a_provider_error_raises_provider_unavailable() -> None:
    provider = FakeProvider([ProviderError("503 from the provider")])
    with pytest.raises(ProviderUnavailable, match="503 from the provider") as unavailable:
        complete(provider)
    assert unavailable.value.answered == ()


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
    [(408, True), (429, True), (500, True), (599, True), (400, False), (600, False)],
)
def test_only_timeouts_rate_limits_and_server_errors_are_transient(status: int, transient: bool) -> None:
    assert is_transient(status) is transient


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


def test_a_retry_cut_at_its_token_cap_names_the_cap() -> None:
    cut = ProviderReply(model="fake-model", text='{"summ', tokens_in=9, tokens_out=256, cut=True)
    provider = FakeProvider([reply("not json", tokens_out=7), cut])

    with pytest.raises(OutputCut) as failure:
        complete(provider)

    assert [call.tokens_out for call in failure.value.answered] == [7, 256]


def test_a_cut_reply_that_is_still_valid_is_taken() -> None:
    provider = FakeProvider(
        [ProviderReply(model="fake-model", text='{"summary": "s"}', tokens_in=9, tokens_out=4, cut=True)]
    )
    assert complete(provider).data == {"summary": "s"}


def test_output_invalid_carries_both_answered_calls() -> None:
    provider = FakeProvider([reply("not json", tokens_out=7), reply('{"summary": 3}', tokens_out=8)])

    with pytest.raises(OutputInvalid) as invalid:
        complete(provider)

    assert [call.tokens_out for call in invalid.value.answered] == [7, 8]
    assert invalid.value.cause() is None  # a schema error may quote the reply, so the page's diagnostic leaves it out


def test_a_retried_response_lists_both_calls() -> None:
    provider = FakeProvider([reply("not json", tokens_out=7), reply('{"summary": "s"}', tokens_out=8)])

    response = complete(provider)

    assert [(call.provider, call.tokens_out) for call in response.answered] == [("fake", 7), ("fake", 8)]
    assert {call.request_hash for call in response.answered} == {request_hash(REQUEST)}


def test_a_retry_that_gets_no_answer_still_carries_the_first_call() -> None:
    provider = FakeProvider([reply("not json", tokens_out=7), ProviderError("503")])

    with pytest.raises(ProviderUnavailable) as unavailable:
        complete(provider)

    assert [call.tokens_out for call in unavailable.value.answered] == [7]


# --- a provider's refusal is logged (F33) ---


def test_a_refusal_is_logged_once_per_provider_model_and_status(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Alembic's `fileConfig` (migrations/env.py) disables existing loggers when a DB test migrates in this process.
    monkeypatch.setattr(client_module.log, "disabled", False)
    unknown = ProviderRefused("fake", "fast-model", 404, "model: fast-model not found")
    provider = FakeProvider([unknown, unknown, ProviderRefused("fake", "fast-model", 401, "invalid key")])
    client = MeteredClient([provider], create_async_engine("postgresql+asyncpg://127.0.0.1/unused"))

    with caplog.at_level(logging.WARNING, logger="crawlerai.llm.client"):
        for _ in range(3):
            call = client.complete_json(REQUEST)
            with pytest.raises(ProviderRefused):
                asyncio.run(call)

    assert [record.getMessage() for record in caplog.records] == [
        "LLM provider fake refused model fast-model: fake: HTTP 404: model: fast-model not found",
        "LLM provider fake refused model fast-model: fake: HTTP 401: invalid key",
    ]


def test_a_refusal_states_its_cause_for_the_page() -> None:
    refused = ProviderRefused("fake", "fast-model", 404, "model not found")
    assert (refused.field_reason, refused.cause()) == ("llm_refused", "fake: HTTP 404: model not found")


def test_a_secret_is_redacted_from_a_message() -> None:
    assert redacted("bad key sk-123 given", "sk-123") == "bad key [redacted] given"
    assert redacted("no key here", "") == "no key here"
