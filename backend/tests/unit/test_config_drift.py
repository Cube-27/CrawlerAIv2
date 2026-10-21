"""Drift (learning-configs spec): a config field's windowed yield and validity, measured on the pages an active config
runs on, against its validated yield and validity less the dev-fitted margins; a field that falls below is suspended and
no longer runs."""

from datetime import UTC, datetime
from typing import Any

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.drift import (
    DriftMargins,
    Observation,
    drifted,
    observe,
    relocated,
)
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import LocateRequest
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import JobId, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX_TIME = datetime(2026, 10, 1, tzinfo=UTC)
MARGINS = DriftMargins.model_validate({"yield": 0.25, "validity": 0.25, "source_split": "dev", "fit": "test"})
HIT = Observation(matched=True, valid=True)
DECLINED = Observation(matched=True, valid=False)


def _ir(
    page_kind: str = "detail", listing: dict[str, Any] | None = None, **fields: dict[str, Any]
) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": page_kind,
            "fetch": {"method": "http"},
            "fields": fields,
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )


def _field(xpath: str = "//h1", *, yield_: float | None = 1.0, validity: float | None = 1.0) -> dict[str, Any]:
    return {"steps": [{"xpath": xpath}], "status": "corroborated", "yield": yield_, "validity": validity}


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef.model_validate(
        {
            "id": SchemaId(uuid7()),
            "origin": "user",
            "status": "active",
            "name": "synthetic",
            "page_kind": page_kind,
            "fields": fields,
        }
    )


def _window(*entries: tuple[str, list[Observation]]) -> dict[str, list[Observation]]:
    return dict(entries)


TITLE = FieldSpec(type=FieldType.TEXT, description="d")
PRICE = FieldSpec(type=FieldType.MONEY, description="d")


def _run(ir: ExtractionConfigIR, schema: SchemaDef, html: str) -> dict[str, Observation]:
    executed = EngineExecutor(ir, Vocabulary(supertypes={})).execute(
        ParsedPage(html), schema, Context(captured_at=CTX_TIME)
    )
    return observe(ir, executed.candidates)


def test_validity_below_the_margin_suspends_a_field_that_still_matches() -> None:
    ir = _ir(price=_field("//b"))
    observed = _run(ir, _schema(price=PRICE), "<html><body><b>call us</b></body></html>")
    assert observed == {"price": DECLINED}
    at = _window(("price", [HIT, HIT, HIT, DECLINED]))  # validity 0.75 = 1.0 - 0.25
    assert drifted(ir, at, MARGINS) == []
    (found,) = drifted(ir, _window(("price", [HIT, DECLINED, HIT, DECLINED])), MARGINS)
    assert (found.field, found.yield_, found.validity) == ("price", 1.0, 0.5)


def test_a_drifted_located_field_requeues_a_locate_run_while_the_surface_locates() -> None:
    rendered = {**_field("//div[@class='price']"), "needs": "browser"}
    ir = _ir(title=_field(), price=rendered)

    job = JobId(uuid7())
    assert relocated(ir, ["title", "price"], "locate", job) == LocateRequest(job_id=job, fields=["price"])
    assert relocated(ir, ["price"], "off") is None
    assert relocated(ir, ["title"], "always") is None
    by_locate = ir.model_copy(update={"provenance": ir.provenance.model_copy(update={"origin": "located"})})
    assert relocated(by_locate, ["title"], "always") == LocateRequest(fields=["title"])
