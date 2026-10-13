"""Role A synthesis (SPEC-08 §4.6): steps are kept only when the engine executor reproduces the published values on
every sample page; failing fields are repaired with diagnostics at most 3 times; the model returns steps, never values.
The client is scripted; no provider is called. Pages are synthetic (`example.test`)."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.induction import Published, SamplePage
from crawlerai.config_ir.model import CssStep, ExtractionConfigIR, FieldSteps, XPathStep
from crawlerai.config_ir.synthesis import ROW, Synthesis, synthesize
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId, SchemaId
from crawlerai.llm.client import BudgetExhausted, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

JOB = JobId(uuid7())
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
TEXT = FieldSpec(type=FieldType.TEXT, description="Name of the item")
URL = FieldSpec(type=FieldType.URL, description="Link", scope="row")
NEXT = FieldSpec(type=FieldType.URL, description="Next page", scope="page")

TITLE = {"xpath": "normalize-space(//h1[@id='t'])"}
WRONG = {"xpath": "normalize-space(//h2)"}


class ScriptedClient:
    """Answers each call with the next scripted reply, or raises the next scripted failure; keeps the requests."""

    def __init__(self, *script: Mapping[str, Any] | Exception) -> None:
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
            data=dict(step),
            provider="fake",
            model="fake-strong",
            tokens_in=10,
            tokens_out=5,
            latency_ms=1,
            request_hash=request_hash(req),
        )


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic", "version": 1}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields or {"title": TEXT}})


def _ir(page_kind: str = "detail", fields: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "version": 1},
            "page_kind": page_kind,
            "fetch": {"method": "http"},
            "fields": fields or {},
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _detail(n: int) -> SamplePage:
    body = f"<div class='card'><h1 id='t'> Item {n} </h1><h2>Other {n}</h2><p class='sku'>S-{n}</p></div>"
    page = ParsedPage(f"<html><body>{body}</body></html>")
    return SamplePage(page, CTX, {"title": Published(f"Item {n}", "microdata:/html/body/div/h1")})


SAMPLE = [_detail(n) for n in range(1, 6)]


def _fields(**steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"fields": {name: {"steps": list(s)} for name, s in steps.items()}}


def _run(
    client: ScriptedClient,
    fields: tuple[str, ...] = ("title",),
    *,
    sample: list[SamplePage] = SAMPLE,
    schema: SchemaDef | None = None,
    ir: ExtractionConfigIR | None = None,
) -> Synthesis:
    schema = schema or _schema()
    ir = ir or _ir(schema.page_kind)
    return asyncio.run(synthesize(client, ir, schema, sample, fields, VOCABULARY, max_chars=120_000, job_id=JOB))


# --- the request ---


def test_the_first_request_is_a_strong_synthesis_call_charged_to_the_job() -> None:
    client = ScriptedClient(_fields(title=[TITLE]))
    _run(client)
    (req,) = client.requests
    assert (req.prompt_kind, req.model_class, req.job_id) == ("a_synth", "strong", JOB)


def test_the_request_shows_each_field_and_each_pages_published_value_and_html() -> None:
    client = ScriptedClient(_fields(title=[TITLE]))
    _run(client)
    user = client.requests[0].user
    assert "- title (text): Name of the item" in user
    assert user.count("<sample_page n=") == 5
    assert '- title: "Item 3"' in user
    assert '<h1 id="t"> Item 3 </h1>' in user


def test_the_output_schema_has_steps_for_the_asked_fields_and_no_place_for_a_value() -> None:
    client = ScriptedClient(_fields(title=[TITLE]))
    _run(client)
    validator = Draft202012Validator(client.requests[0].output_schema)
    assert validator.is_valid(_fields(title=[TITLE]))
    assert not validator.is_valid({"fields": {"title": {"steps": [TITLE], "value": "Item 1"}}})
    assert not validator.is_valid(_fields(title=[{**TITLE, "value": "Item 1"}]))
    assert not validator.is_valid(_fields(title=[TITLE], other=[TITLE]))


# --- verification and repair ---


def test_steps_that_reproduce_every_published_value_are_kept_after_one_call() -> None:
    client = ScriptedClient(_fields(title=[TITLE]))
    result = _run(client)
    assert result.ir.fields == {"title": FieldSteps(steps=[XPathStep(xpath=TITLE["xpath"])], status="uncorroborated")}
    assert (result.ir.provenance.origin, result.unresolved, result.repairs, len(client.requests)) == (
        "llm_synth",
        {},
        0,
        1,
    )


def test_a_failing_field_is_repaired_with_its_previous_steps_and_diagnostics() -> None:
    client = ScriptedClient(_fields(title=[WRONG]), _fields(title=[TITLE]))
    result = _run(client)
    assert (list(result.ir.fields), result.repairs) == (["title"], 1)
    repair = client.requests[1]
    assert (repair.prompt_kind, repair.model_class) == ("a_repair", "strong")
    assert '- title: [{"xpath": "normalize-space(//h2)"}]' in repair.user
    assert '  - page 1: value_mismatch("Other 1", "Item 1")' in repair.user


def test_repairs_stop_after_three_rounds_and_the_field_is_left_without_steps() -> None:
    client = ScriptedClient(*[_fields(title=[WRONG])] * 4)
    result = _run(client)
    assert [r.prompt_kind for r in client.requests] == ["a_synth", "a_repair", "a_repair", "a_repair"]
    assert (result.repairs, result.ir) == (3, _ir())
    assert result.unresolved["title"][0] == 'page 1: value_mismatch("Other 1", "Item 1")'


def test_a_repair_asks_only_for_the_fields_that_failed() -> None:
    schema = _schema(title=TEXT, sku=FieldSpec(type=FieldType.TEXT, description="Code"))
    sample = [
        SamplePage(s.page, CTX, {**s.published, "sku": Published(f"S-{n}", "text:0-3")})
        for n, s in enumerate(SAMPLE, 1)
    ]
    sku = {"xpath": "normalize-space(//p[@class='sku'])"}
    client = ScriptedClient(_fields(title=[TITLE], sku=[WRONG]), _fields(sku=[sku]))
    result = _run(client, ("sku", "title"), sample=sample, schema=schema)
    repair: Any = client.requests[1].output_schema
    assert list(repair["properties"]["fields"]["properties"]) == ["sku"]
    assert sorted(result.ir.fields) == ["sku", "title"]


@pytest.mark.parametrize(
    ("step", "diagnostic"),
    [
        ({"xpath": "//h1 | //h2"}, "page 1: multi_match(2)"),
        ({"xpath": "//h3"}, "page 1: no_match"),
        ({"xpath": "lower-case(//h1)"}, "step 0: invalid_xpath("),
        ({"xpath": "//h1", "regex": "h1"}, "step 0: invalid_step(a step has exactly one selector key"),
    ],
)
def test_each_failure_has_its_diagnostic(step: dict[str, Any], diagnostic: str) -> None:
    client = ScriptedClient(*[_fields(title=[step])] * 4)
    assert _run(client).unresolved["title"][0].startswith(diagnostic)


def test_a_step_that_does_not_parse_is_dropped_and_the_others_are_verified() -> None:
    client = ScriptedClient(_fields(title=[{"xpath": "lower-case(//h1)"}, TITLE]))
    result = _run(client)
    assert result.ir.fields["title"].steps == [XPathStep(xpath=TITLE["xpath"])]


def test_a_step_that_does_not_parse_is_reported_when_the_others_fail() -> None:
    client = ScriptedClient(*[_fields(title=[{"xpath": "lower-case(//h1)"}, WRONG])] * 4)
    diagnostics = _run(client).unresolved["title"]
    assert diagnostics[0].startswith("step 0: invalid_xpath(")
    assert diagnostics[1] == 'page 1: value_mismatch("Other 1", "Item 1")'


def test_an_empty_reply_for_a_field_is_no_steps() -> None:
    client = ScriptedClient(*[_fields(title=[])] * 4)
    assert _run(client).unresolved == {"title": ("no_steps",)}


def test_a_field_published_on_no_sample_page_is_not_asked() -> None:
    sample = [SamplePage(s.page, CTX, {}) for s in SAMPLE]
    client = ScriptedClient()
    result = _run(client, sample=sample)
    assert (client.requests, result.unresolved, result.ir) == ([], {"title": ("not_published",)}, _ir())


def test_induced_fields_are_kept_and_not_asked() -> None:
    induced = {"sku": {"steps": [{"xpath": "normalize-space(//p)"}], "status": "uncorroborated"}}
    schema = _schema(title=TEXT, sku=TEXT)
    client = ScriptedClient(_fields(title=[TITLE]))
    result = _run(client, schema=schema, ir=_ir(fields=induced))
    assert sorted(result.ir.fields) == ["sku", "title"]
    assert "- sku" not in client.requests[0].user


def test_a_field_outside_the_schema_is_refused() -> None:
    client = ScriptedClient()
    with pytest.raises(ValueError, match="not fields of synthetic"):
        _run(client, ("price",))


def test_an_llm_failure_propagates() -> None:
    client = ScriptedClient(BudgetExhausted("no budget"))
    with pytest.raises(BudgetExhausted):
        _run(client)


# --- listings ---

LISTING_SCHEMA = {"title": FieldSpec(type=FieldType.TEXT, description="Row name"), "link": URL, "next_page_url": NEXT}
ROW_STEP = {"css": "ul > li"}
ROW_TITLE = {"xpath": "normalize-space(em)"}
ROW_LINK = {"xpath": "a/@href"}
NEXT_STEP = {"xpath": "//a[@rel='next']/@href", "post": [{"absolutize_url": {}}]}


def _listing_page(n: int, rows: int = 3) -> SamplePage:
    items = "".join(
        f"<li class='row'><em>Row {n}.{r}</em><a href='https://shop.example.test/i/{n}{r}'>go</a></li>"
        for r in range(rows)
    )
    page = ParsedPage(f"<html><body><ul>{items}</ul><a rel='next' href='/list/{n + 1}'>next</a></body></html>")
    published = {"next_page_url": Published(f"https://shop.example.test/list/{n + 1}", "meta:x")}
    row_values = [
        {
            "title": Published(f"Row {n}.{r}", "text:0-3"),
            "link": Published(f"https://shop.example.test/i/{n}{r}", "meta:x"),
        }
        for r in range(rows)
    ]
    return SamplePage(page, CTX, published, row_values)


LISTING_SAMPLE = [_listing_page(n) for n in range(1, 6)]


def _listing_reply(row: dict[str, Any] | None = None, **fields: list[dict[str, Any]]) -> dict[str, Any]:
    listing: dict[str, Any] = {"fields": {name: {"steps": steps} for name, steps in fields.items()}}
    if row is not None:
        listing["row"] = row
    return listing


def _run_listing(client: ScriptedClient, sample: list[SamplePage] = LISTING_SAMPLE) -> Synthesis:
    fields = ("link", "next_page_url", "title")
    return _run(client, fields, sample=sample, schema=_schema("listing", **LISTING_SCHEMA))


def test_a_listing_gets_its_row_selector_row_fields_and_next() -> None:
    reply = {
        "fields": {"next_page_url": {"steps": [NEXT_STEP]}},
        "listing": _listing_reply(ROW_STEP, title=[ROW_TITLE], link=[ROW_LINK]),
    }
    client = ScriptedClient(reply)
    result = _run_listing(client)
    listing = result.ir.listing
    assert listing is not None
    assert (listing.row, listing.next) == (CssStep.model_validate(ROW_STEP), XPathStep.model_validate(NEXT_STEP))
    assert listing.fields["title"].steps == [XPathStep(xpath="normalize-space(em)")]
    assert (result.ir.fields, result.unresolved) == ({}, {})


def test_next_takes_one_step() -> None:
    reply = {
        "fields": {"next_page_url": {"steps": [NEXT_STEP]}},
        "listing": _listing_reply(ROW_STEP, title=[ROW_TITLE], link=[ROW_LINK]),
    }
    client = ScriptedClient(reply)
    _run_listing(client)
    validator = Draft202012Validator(client.requests[0].output_schema)
    assert not validator.is_valid({**reply, "fields": {"next_page_url": {"steps": [NEXT_STEP, NEXT_STEP]}}})


def test_a_row_selector_with_too_few_rows_is_repaired_with_its_row_fields() -> None:
    first = {
        "fields": {"next_page_url": {"steps": [NEXT_STEP]}},
        "listing": _listing_reply({"css": "ul > li:first-child"}, title=[ROW_TITLE], link=[ROW_LINK]),
    }
    second = {"listing": _listing_reply(ROW_STEP, title=[ROW_TITLE], link=[ROW_LINK])}
    client = ScriptedClient(first, second)
    result = _run_listing(client)
    assert "  - page 1: rows(1, 3)" in client.requests[1].user
    assert "  - row_not_verified" in client.requests[1].user
    assert result.ir.listing is not None and sorted(result.ir.listing.fields) == ["link", "title"]
    assert result.ir.listing.next is not None


def test_a_row_field_that_fails_is_repaired_under_the_verified_row() -> None:
    first = {
        "fields": {"next_page_url": {"steps": [NEXT_STEP]}},
        "listing": _listing_reply(ROW_STEP, title=[ROW_TITLE], link=[{"attr": "class"}]),
    }
    second = {"listing": _listing_reply(link=[ROW_LINK])}
    client = ScriptedClient(first, second)
    result = _run_listing(client)
    repair = client.requests[1]
    schema: Any = repair.output_schema
    assert list(schema["properties"]) == ["listing"]
    assert 'the row selector is {"css": "ul > li"' in repair.user
    assert result.ir.listing is not None and result.ir.listing.fields["link"].steps == [XPathStep(xpath="a/@href")]


def test_without_a_verified_row_there_is_no_listing_and_next_is_left_out() -> None:
    reply = {
        "fields": {"next_page_url": {"steps": [NEXT_STEP]}},
        "listing": _listing_reply({"attr": "class"}, title=[ROW_TITLE], link=[ROW_LINK]),
    }
    client = ScriptedClient(reply, *[{"listing": _listing_reply({"attr": "class"}, title=[], link=[])}] * 3)
    result = _run_listing(client)
    assert (result.ir.listing, result.ir.fields) == (None, {})
    assert result.unresolved["next_page_url"] == ("no_listing",)
    assert result.unresolved[ROW][:2] == (
        "page 1: rows(0, 3)",
        "page 1: a row step selects elements, so it is an xpath or css step",
    )
