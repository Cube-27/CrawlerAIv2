"""Drift (SPEC-08 §4.9): a config field's windowed yield and validity, measured on the pages an active config runs on,
against its validated yield and validity less the dev-fitted margins; a field that falls below is suspended and no
longer runs."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.drift import (
    WINDOW_PAGES,
    DriftMargins,
    Observation,
    drifted,
    extend,
    load_margins,
    observe,
    suspend,
)
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

CTX_TIME = datetime(2026, 10, 1, tzinfo=UTC)
MARGINS = DriftMargins.model_validate({"yield": 0.25, "validity": 0.25, "source_split": "dev"})
HIT = Observation(matched=True, valid=True)
MISS = Observation(matched=False, valid=False)
DECLINED = Observation(matched=True, valid=False)


def _ir(
    page_kind: str = "detail", listing: dict[str, Any] | None = None, **fields: dict[str, Any]
) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "version": 1},
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
            "version": 1,
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


def test_yield_exactly_at_the_margin_is_not_drift_and_just_below_is() -> None:
    ir = _ir(title=_field())
    assert drifted(ir, _window(("title", [HIT, HIT, HIT, MISS])), MARGINS) == []  # 0.75 = 1.0 - 0.25
    (found,) = drifted(ir, _window(("title", [HIT, HIT, MISS, MISS])), MARGINS)
    assert (found.field, found.yield_) == ("title", 0.5)


def test_validity_below_the_margin_suspends_a_field_that_still_matches() -> None:
    ir = _ir(price=_field("//b"))
    observed = _run(ir, _schema(price=PRICE), "<html><body><b>call us</b></body></html>")
    assert observed == {"price": DECLINED}
    at = _window(("price", [HIT, HIT, HIT, DECLINED]))  # validity 0.75 = 1.0 - 0.25
    assert drifted(ir, at, MARGINS) == []
    (found,) = drifted(ir, _window(("price", [HIT, DECLINED, HIT, DECLINED])), MARGINS)
    assert (found.field, found.yield_, found.validity) == ("price", 1.0, 0.5)


def test_fewer_than_three_pages_are_never_drift() -> None:
    ir = _ir(title=_field())
    assert drifted(ir, _window(("title", [MISS, MISS])), MARGINS) == []
    assert [d.field for d in drifted(ir, _window(("title", [MISS, MISS, MISS])), MARGINS)] == ["title"]


def test_a_field_without_a_validated_yield_or_validity_is_not_compared_on_it() -> None:
    ir = _ir(title=_field(yield_=None, validity=None), price=_field("//b", validity=None))
    window = _window(("title", [MISS] * 5), ("price", [DECLINED] * 5))
    assert drifted(ir, window, MARGINS) == []


def test_with_no_matched_page_validity_is_unmeasured_and_only_yield_is_compared() -> None:
    ir = _ir(title=_field(yield_=0.5))
    (found,) = drifted(ir, _window(("title", [MISS] * 5)), MARGINS)
    assert (found.yield_, found.validity) == (0.0, None)
    assert drifted(_ir(title=_field(yield_=0.25)), _window(("title", [MISS] * 5)), MARGINS) == []


def test_a_suspended_field_is_neither_observed_nor_run() -> None:
    ir = suspend(_ir(title=_field("//h1"), price=_field("//b")), ["title"])
    assert (ir.fields["title"].status, ir.fields["price"].status) == ("suspended", "corroborated")
    observed = _run(ir, _schema(title=TITLE, price=PRICE), "<html><body><h1>A lamp</h1><b>9.99 EUR</b></body></html>")
    assert observed == {"price": HIT}
    assert drifted(ir, _window(("title", [MISS] * 5)), MARGINS) == []


def test_a_listing_field_matches_when_any_row_does_and_is_valid_only_when_every_row_is() -> None:
    listing = {"row": {"xpath": "//li"}, "fields": {"price": _field("b"), "title": _field("i")}}
    ir = _ir("listing", listing)
    html = "<html><body><ul><li><b>9.99 EUR</b></li><li><b>ask</b></li></ul></body></html>"
    assert _run(ir, _schema("listing", price=PRICE, title=TITLE), html) == {"price": DECLINED, "title": MISS}


@given(st.lists(st.sampled_from([HIT, MISS, DECLINED]), max_size=2 * WINDOW_PAGES + 3))
def test_the_window_is_the_last_fifty_pages_in_order(pages: list[Observation]) -> None:
    window: dict[str, list[Observation]] = {}
    for page in pages:
        window = extend(window, {"title": page})
    assert window.get("title", []) == pages[-WINDOW_PAGES:]


def test_margins_are_read_from_their_dev_stamped_file(tmp_path: Path) -> None:
    path = tmp_path / "drift_margins.json"
    assert load_margins(path) is None
    path.write_text(json.dumps({"yield": 0.2, "validity": 0.1, "source_split": "dev"}), encoding="utf-8")
    margins = load_margins(path)
    assert margins is not None
    assert (margins.yield_, margins.validity) == (0.2, 0.1)


def test_margins_fitted_on_another_split_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "drift_margins.json"
    path.write_text(json.dumps({"yield": 0.2, "validity": 0.1, "source_split": "hidden"}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_margins(path)
