"""Operator corrections (C5): a correction replaces or removes fields' steps and confirms fields;
every field it touches becomes `operator`, the result is an `operator` config, and a correction that names a field the
schema or the config does not have is refused."""

from datetime import UTC, datetime
from typing import Any

import pytest

from snowcrawl.config_ir.corrections import Correction, InvalidCorrection, correct
from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import SchemaId
from snowcrawl.schemas.types import FieldSpec, FieldType, SchemaDef

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)
TEXT = FieldSpec(type=FieldType.TEXT, description="d")
PAGE_TEXT = FieldSpec(type=FieldType.TEXT, description="d", scope="page")
H1 = {"xpath": "normalize-space(//h1)"}
# A stored step: the document form, with its (empty) post ops.
H2_STORED: dict[str, Any] = {"xpath": "normalize-space(//h2)", "post": []}
H2 = {"xpath": "normalize-space(//h2)"}
CELL = {"xpath": "normalize-space(.//td)"}


def _schema(page_kind: str = "detail", **fields: FieldSpec) -> SchemaDef:
    document = {"id": SchemaId(uuid7()), "origin": "user", "status": "active", "name": "synthetic"}
    return SchemaDef.model_validate({**document, "page_kind": page_kind, "fields": fields})


def _ir(fields: dict[str, Any], listing: dict[str, Any] | None = None) -> ExtractionConfigIR:
    return ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": "shop.example.test",
            "schema": {"name": "synthetic", "digest": "0" * 64},
            "page_kind": "detail" if listing is None else "listing",
            "fetch": {"method": "http"},
            "fields": fields,
            "listing": listing,
            "provenance": {
                "origin": "induced",
                "validated_on": [str(uuid7())],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "old",
            },
        }
    )


def _steps(step: dict[str, Any], status: str = "uncorroborated", **extra: Any) -> dict[str, Any]:
    return {"steps": [step], "status": status, **extra}


DETAIL = _schema(title=TEXT, subtitle=TEXT, brand=TEXT)
BASE = _ir({"title": _steps(H1, "corroborated", **{"yield": 1.0, "validity": 1.0}), "brand": _steps(H2)})


def _correct(body: dict[str, Any], ir: ExtractionConfigIR = BASE, schema: SchemaDef = DETAIL) -> dict[str, Any]:
    corrected = correct(ir, schema, Correction.model_validate(body), engine_version="now", at=NOW)
    document: dict[str, Any] = corrected.model_dump(mode="json")
    return document


def test_corrected_steps_replace_the_fields_steps_as_operator_and_drop_their_measurements() -> None:
    corrected = _correct({"fields": {"title": {"steps": [H2]}}})
    sourced = {"needs": "http", "call": None}
    assert corrected["fields"]["title"] == {
        "steps": [H2_STORED],
        "status": "operator",
        "yield": None,
        "validity": None,
        **sourced,
    }
    assert corrected["fields"]["brand"] == {
        "steps": [H2_STORED],
        "status": "uncorroborated",
        "yield": None,
        "validity": None,
        **sourced,
    }


def test_a_listing_routes_row_fields_to_its_rows_and_page_fields_to_the_page() -> None:
    schema = _schema("listing", name=TEXT, price=TEXT, heading=PAGE_TEXT)
    listing = {"row": {"xpath": "//tr"}, "fields": {"name": _steps(CELL)}}
    ir = _ir({}, listing)

    corrected = _correct({"fields": {"price": {"steps": [CELL]}, "heading": {"steps": [H1]}}}, ir, schema)

    assert list(corrected["listing"]["fields"]) == ["name", "price"]
    assert corrected["listing"]["fields"]["price"]["status"] == "operator"
    assert corrected["listing"]["row"] == {"xpath": "//tr", "post": []}
    assert corrected["fields"]["heading"]["status"] == "operator"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({}, ("", "a correction changes or confirms at least one field")),
        ({"fields": {"price": {"steps": [H1]}}}, ("fields.price", "not a field of schema synthetic")),
        ({"confirm": ["subtitle"]}, ("confirm.subtitle", "the config has no steps to confirm")),
        ({"fields": {"subtitle": None}}, ("fields.subtitle", "the config has no steps to remove")),
        ({"fields": {"brand": None}, "confirm": ["brand"]}, ("confirm.brand", "the field is also corrected")),
    ],
)
def test_a_correction_the_config_cannot_take_is_refused_with_the_field(
    body: dict[str, Any], error: tuple[str, str]
) -> None:
    correction = Correction.model_validate(body)
    with pytest.raises(InvalidCorrection) as raised:
        correct(BASE, DETAIL, correction, engine_version="now", at=NOW)
    assert raised.value.errors == [error]
