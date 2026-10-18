"""Drift (SPEC-08 §4.9): a config field's windowed yield and validity, measured on the pages an active config runs on,
against its validated yield and validity less the dev-fitted margins; a field that falls below is suspended and no
longer runs."""

from datetime import UTC, datetime
from typing import Any

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.drift import (
    DriftMargins,
    Observation,
    drifted,
    extend,
    observe,
)
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
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


def test_a_layout_change_suspends_the_field_once_its_windowed_yield_falls_below_the_margin() -> None:
    ir = _ir(title=_field("//h1[@class='title']"))
    schema = _schema(title=TITLE)
    window: dict[str, list[Observation]] = {}
    for _ in range(4):
        window = extend(window, _run(ir, schema, "<html><body><h1 class='title'>A lamp</h1></body></html>"))
    assert window == {"title": [HIT] * 4}
    changed = "<html><body><h2 class='heading'>A lamp</h2></body></html>"
    window = extend(window, _run(ir, schema, changed))  # 4 of 5 = 0.8: not below 1.0 - 0.25
    assert drifted(ir, window, MARGINS) == []
    window = extend(window, _run(ir, schema, changed))  # 4 of 6

    (found,) = drifted(ir, window, MARGINS)
    assert (found.field, found.pages, found.yield_, found.validity) == ("title", 6, 4 / 6, 1.0)


def test_validity_below_the_margin_suspends_a_field_that_still_matches() -> None:
    ir = _ir(price=_field("//b"))
    observed = _run(ir, _schema(price=PRICE), "<html><body><b>call us</b></body></html>")
    assert observed == {"price": DECLINED}
    at = _window(("price", [HIT, HIT, HIT, DECLINED]))  # validity 0.75 = 1.0 - 0.25
    assert drifted(ir, at, MARGINS) == []
    (found,) = drifted(ir, _window(("price", [HIT, DECLINED, HIT, DECLINED])), MARGINS)
    assert (found.field, found.yield_, found.validity) == ("price", 1.0, 0.5)
