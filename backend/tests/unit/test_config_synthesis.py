"""Role A synthesis (learning-configs spec): steps are kept only when the engine executor reproduces the published
values on every sample page; failing fields are repaired with diagnostics at most 3 times; the model returns steps,
never values. The client is scripted; no provider is called. Pages are synthetic (`example.test`)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir import step_wire
from crawlerai.config_ir.induction import Published, SamplePage
from crawlerai.config_ir.model import CssStep, ExtractionConfigIR, XPathStep
from crawlerai.config_ir.synthesis import Synthesis, synthesize
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.support.fake_llm import ScriptedClient

JOB = JobId(uuid7())
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
TEXT = FieldSpec(type=FieldType.TEXT, description="Name of the item")
URL = FieldSpec(type=FieldType.URL, description="Link", scope="row")
NEXT = FieldSpec(type=FieldType.URL, description="Next page", scope="page")

TITLE = {"xpath": "normalize-space(//h1[@id='t'])"}


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic"}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields or {"title": TEXT}})


def _ir(page_kind: str = "detail", fields: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
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


def _wire(step: dict[str, Any]) -> dict[str, Any]:
    """An IR step document as role A writes it (`step_wire`), even one the IR refuses."""
    selector = next(key for key in step_wire.SELECTORS if key in step)
    post = [
        {"op": op, "pattern": params.get("pattern", ""), "repl": params.get("repl", "")}
        for item in step.get("post", [])
        for op, params in item.items()
    ]
    return {
        "selector": selector,
        "expression": step[selector],
        "when_type": step.get("when_type", ""),
        "source": step.get("source", ""),
        "post": post,
    }


def _steps(name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"field": name, "steps": [_wire(step) for step in steps]}


def _entries(steps: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [_steps(name, s) for name, s in steps.items()]


def _fields(**steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"fields": _entries(steps)}


def _run(
    client: ScriptedClient,
    fields: tuple[str, ...] = ("title",),
    *,
    sample: list[SamplePage] = SAMPLE,
    schema: SchemaDef | None = None,
    ir: ExtractionConfigIR | None = None,
    max_chars: int = 60_000,
) -> Synthesis:
    schema = schema or _schema()
    ir = ir or _ir(schema.page_kind)
    return asyncio.run(synthesize(client, ir, schema, sample, fields, VOCABULARY, max_chars=max_chars, job_id=JOB))


# --- the request ---


# --- verification and repair ---


def test_a_step_that_does_not_parse_is_dropped_and_the_others_are_verified() -> None:
    client = ScriptedClient(_fields(title=[{"xpath": "lower-case(//h1)"}, TITLE]))
    result = _run(client)
    assert result.ir.fields["title"].steps == [XPathStep(xpath=TITLE["xpath"])]


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
    listing: dict[str, Any] = {"fields": _entries(fields)}
    if row is not None:
        listing["row"] = _wire(row)
    return listing


def _run_listing(client: ScriptedClient, sample: list[SamplePage] = LISTING_SAMPLE) -> Synthesis:
    fields = ("link", "next_page_url", "title")
    return _run(client, fields, sample=sample, schema=_schema("listing", **LISTING_SCHEMA))


def test_a_listing_gets_its_row_selector_row_fields_and_next() -> None:
    reply = {
        **_fields(next_page_url=[NEXT_STEP]),
        "listing": _listing_reply(ROW_STEP, title=[ROW_TITLE], link=[ROW_LINK]),
    }
    client = ScriptedClient(reply)
    result = _run_listing(client)
    listing = result.ir.listing
    assert listing is not None
    assert (listing.row, listing.next) == (CssStep.model_validate(ROW_STEP), XPathStep.model_validate(NEXT_STEP))
    assert listing.fields["title"].steps == [XPathStep(xpath="normalize-space(em)")]
    assert (result.ir.fields, result.unresolved) == ({}, {})
