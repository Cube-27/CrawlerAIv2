"""Role C on a detail page (SPEC-06 §4.4, §4.7, §6, INV-12): a deterministic request, grounded candidates, dropped
ungrounded values, and failures that leave fields missing with their reason. The client is scripted; no provider is
called. Pages are synthetic (`example.test`)."""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from crawlerai.collect.base import Candidate, Entity
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId, SchemaId
from crawlerai.llm.client import (
    BudgetExhausted,
    LLMFailure,
    LLMRequest,
    LLMResponse,
    OutputInvalid,
    ProviderUnavailable,
    ReplyCheck,
    request_hash,
)
from crawlerai.llm.roles.c_extract import DETAIL_MAX_CHARS, Filled, detail_request, extract_detail, output_schema
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.resolve.pipeline import GapReply, GapRequest
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

JOB = JobId(uuid7())
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), page_url=PAGE_URL)
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    version=1,
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="Name of the item", required=True),
        "released": FieldSpec(type=FieldType.DATE, description="Release date"),
        "sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="Stock keeping unit"),
    },
)
TEXT = "Widget One\nReleased 2026-09-30\nIn stock"
OWNER = "jsonld:0:$"


def span(value: str, start: int, end: int | None = None) -> dict[str, JsonValue]:
    return {"value": value, "start": start, "end": start + len(value) if end is None else end}


class ScriptedClient:
    """Answers each call with the next scripted reply, or raises the next scripted failure; keeps the requests."""

    def __init__(self, *script: dict[str, JsonValue] | Exception) -> None:
        self._script = list(script)
        self.requests: list[LLMRequest] = []

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        self.requests.append(req)
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        # The real client validates every reply against the request's schema; so does this one.
        Draft202012Validator(req.output_schema).validate(step)
        return LLMResponse(
            data=step,
            provider="fake",
            model="fake-fast",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            request_hash=request_hash(req),
        )


def extract(client: ScriptedClient, fields: Sequence[str] = ("title", "released"), text: str = TEXT) -> Filled:
    return asyncio.run(extract_detail(client, text, SCHEMA, CTX, owner=OWNER, fields=fields, job_id=JOB))


def reply(**fields: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    return {"fields": dict(fields)}


# --- the request ---


def test_the_request_is_a_fast_detail_call_charged_to_the_job() -> None:
    req = detail_request(TEXT, SCHEMA, ["title"], page_url=PAGE_URL, job_id=JOB)

    assert (req.prompt_kind, req.model_class, req.job_id) == ("c_extract_detail", "fast", JOB)


def test_the_request_names_each_field_with_its_type_and_description_and_holds_the_text() -> None:
    user = detail_request(TEXT, SCHEMA, ["title", "sku"], page_url=PAGE_URL, job_id=JOB).user

    assert "- sku (identifier, scheme sku): Stock keeping unit\n- title (text): Name of the item\n" in user
    assert f"<page_text>\n{TEXT}\n</page_text>" in user
    assert f"Page URL (context only, never a source of values): {PAGE_URL}" in user
    assert "released" not in user


def test_the_same_fields_in_any_order_give_the_same_request_hash() -> None:
    first = detail_request(TEXT, SCHEMA, ["title", "released"], page_url=PAGE_URL, job_id=JOB)
    second = detail_request(TEXT, SCHEMA, ["released", "title"], page_url=PAGE_URL, job_id=JOB)

    assert request_hash(first) == request_hash(second)


def test_the_output_schema_takes_a_span_or_null_for_exactly_the_requested_fields() -> None:
    validator = Draft202012Validator(output_schema(["title", "released"]))

    assert validator.is_valid(reply(title=span("Widget One", 0), released=None))
    assert not validator.is_valid(reply(title=span("Widget One", 0)))  # every requested field answers
    assert not validator.is_valid(reply(title=None, released=None, sku=None))  # and no other
    assert not validator.is_valid(reply(title={"value": "Widget One", "start": 0}, released=None))
    assert not validator.is_valid({**reply(title=None, released=None), "note": "x"})


def test_a_long_text_is_cut_at_the_detail_limit_and_the_cut_is_recorded() -> None:
    text = "a" * DETAIL_MAX_CHARS + "Widget One"
    client = ScriptedClient(reply(title=None))

    filled = extract(client, ["title"], text)

    assert f"<page_text>\n{'a' * DETAIL_MAX_CHARS}\n</page_text>" in client.requests[0].user
    assert filled.diagnostics == (f"role C read the first {DETAIL_MAX_CHARS} of {DETAIL_MAX_CHARS + 10} characters",)


# --- grounding the reply ---


def test_a_grounded_value_becomes_an_llm_candidate_owned_by_the_target() -> None:
    filled = extract(ScriptedClient(reply(title=span("Widget One", 0), released=None)))

    assert filled.candidates == (
        Candidate(
            field="title",
            entity_id=OWNER,
            source_kind="llm",
            raw="Widget One",
            normalized=Ok("Widget One"),
            locator="text:0-10",
            independent=True,
        ),
    )
    assert (filled.failure, filled.diagnostics) == (None, ())


def test_wrong_offsets_are_corrected_to_where_the_value_is() -> None:
    filled = extract(ScriptedClient(reply(title=None, released=span("2026-09-30", 3))))

    assert [(c.raw, c.locator, c.normalized) for c in filled.candidates] == [
        ("2026-09-30", "text:20-30", Ok("2026-09-30"))
    ]


def test_a_value_the_text_does_not_contain_is_dropped_with_a_diagnostic() -> None:
    filled = extract(ScriptedClient(reply(title=span("Widget Two", 0), released=None)))

    assert (filled.candidates, filled.diagnostics) == ((), ("role C: title ungrounded",))


def test_a_value_past_the_cut_is_ungrounded() -> None:
    text = "a" * DETAIL_MAX_CHARS + "Widget One"
    filled = extract(ScriptedClient(reply(title=span("Widget One", DETAIL_MAX_CHARS))), ["title"], text)

    assert filled.candidates == ()
    assert "role C: title ungrounded" in filled.diagnostics


def test_null_proposes_nothing() -> None:
    filled = extract(ScriptedClient(reply(title=None, released=None)))

    assert (filled.candidates, filled.diagnostics, filled.failure) == ((), (), None)


def test_a_value_its_normalizer_declines_stays_a_candidate_with_the_decline() -> None:
    # Preference rejects it as `invalid`; the candidate row keeps why.
    filled = extract(ScriptedClient(reply(title=None, released=span("In stock", 31))))

    (candidate,) = filled.candidates
    assert (candidate.field, candidate.raw, isinstance(candidate.normalized, Invalid)) == ("released", "In stock", True)


# INV-12: every candidate's value is the cleaned text at its locator, for any text and any claimed offsets.
@given(
    st.text(min_size=1, max_size=200),
    st.data(),
)
def test_a_candidate_is_always_the_text_at_its_locator(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(text) - 1))
    end = data.draw(st.integers(start + 1, len(text)))
    hint = data.draw(st.integers(0, len(text) + 5))
    filled = extract(ScriptedClient(reply(title=span(text[start:end], hint))), ["title"], text)

    (candidate,) = filled.candidates
    first, last = map(int, candidate.locator.removeprefix("text:").split("-"))
    assert text[first:last] == candidate.raw == text[start:end]


# --- failures (§4.7) ---


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (BudgetExhausted("no llm_calls left"), "llm_budget"),
        (ProviderUnavailable("fake: 503"), "llm_unavailable"),
        (OutputInvalid("at $: not an object"), "llm_output_invalid"),
    ],
)
def test_a_call_without_a_valid_reply_leaves_the_reason_and_no_candidates(failure: LLMFailure, reason: str) -> None:
    filled = extract(ScriptedClient(failure))

    assert (filled.candidates, filled.response, filled.failure) == ((), None, reason)
    assert filled.diagnostics == (f"role C: {reason}",)


def test_other_errors_propagate() -> None:
    # A replay's missing recording must reach the harness, which drops the page (SPEC-03 §4.5).
    client = ScriptedClient(LookupError("no recorded response"))
    with pytest.raises(LookupError, match="no recorded response"):
        extract(client)


# --- the bound hook ---


def fill(client: ScriptedClient, request: GapRequest) -> GapReply:
    async def run() -> GapReply:
        return await role_c(client, job_id=JOB)(request)

    return asyncio.run(run())


def gap_request(html: str, missing: tuple[str, ...]) -> GapRequest:
    target = Entity(id=OWNER, kind="Product", urls=(PAGE_URL,), parent=None)
    return GapRequest(ParsedPage(html), SCHEMA, CTX, target, missing)


def test_the_hook_reads_the_cleaned_text_and_records_the_call() -> None:
    client = ScriptedClient(reply(title=span("Widget One", 0)))
    request = gap_request("<html><body><h1>Widget One</h1><script>var x = 1;</script></body></html>", ("title",))

    answer = fill(client, request)

    assert "<page_text>\nWidget One\n</page_text>" in client.requests[0].user
    assert [(c.field, c.raw, c.locator) for c in answer.candidates] == [("title", "Widget One", "text:0-10")]
    (call,) = answer.llm_calls
    assert (call.prompt_kind, call.provider, call.model, call.tokens_in, call.tokens_out) == (
        "c_extract_detail",
        "fake",
        "fake-fast",
        10,
        5,
    )
    assert call.request_hash == request_hash(client.requests[0])
    assert (answer.failure, answer.diagnostics) == (None, ())


def test_a_failed_call_is_recorded_as_the_hooks_failure_without_a_call() -> None:
    request = gap_request("<html><body><h1>Widget One</h1></body></html>", ("title",))

    answer = fill(ScriptedClient(BudgetExhausted("none left")), request)

    assert (answer.candidates, answer.llm_calls, answer.failure) == ((), (), "llm_budget")
