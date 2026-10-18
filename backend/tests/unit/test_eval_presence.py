"""Whether a capture shows a value (`eval.presence`) and which label rows re-keying marks stale (`eval.rekey`).
Synthetic documents and RFC 2606 hosts only (C3, C9)."""

import pytest
from pydantic import JsonValue

from crawlerai.eval.labels import Labels
from crawlerai.eval.presence import Capture
from crawlerai.eval.rekey import stale_rows
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

TEXT = FieldSpec(type=FieldType.TEXT)
URL = FieldSpec(type=FieldType.URL)
PLACES = FieldSpec(type=FieldType.LIST, item=FieldSpec(type=FieldType.LOCATION))
MONEY = FieldSpec(type=FieldType.MONEY)
DOCUMENT = (
    '<main><h2>Caf&eacute; <em>Table</em>  Lamp</h2><a href="/p/table-lamp?ref=1">x</a>'
    '<script>{"next": "https:\\/\\/shop.example.test\\/p\\/desk-chair"}</script><span>Lakeside</span></main>'
)


@pytest.mark.parametrize(
    ("value", "spec", "shown"),
    [
        # Character references decoded, inline markup taken out, case and white space ignored.
        ("café table lamp", TEXT, True),
        ("Floor Lamp", TEXT, False),
        # A URL by its path, in an attribute or in inline JSON with escaped solidus.
        ("https://shop.example.test/p/table-lamp", URL, True),
        ("https://shop.example.test/p/desk-chair", URL, True),
        ("https://shop.example.test/p/sofa", URL, False),
        # A list by any of its items; a location by its text.
        ([{"text": "Hilltop"}, {"text": "Lakeside"}], PLACES, True),
        # Too short to say anything, or not searchable as written: unknown.
        ("ab", TEXT, None),
        ("https://shop.example.test/", URL, None),
        ({"amount": "19.90", "currency": "EUR"}, MONEY, None),
    ],
)
def test_a_capture_shows_a_value_as_written(value: JsonValue, spec: FieldSpec, shown: bool | None) -> None:
    assert Capture(DOCUMENT).shows(value, spec) is shown


def _labels(*rows: dict[str, JsonValue]) -> Labels:
    return Labels.model_validate(
        {
            "label_version": 1,
            "status": "draft",
            "prefill_source": "none",
            "fields": {},
            "rows": [{"fields": {k: {"value": v, "absent": False} for k, v in row.items()}} for row in rows],
        }
    )


def test_a_row_is_stale_only_when_the_capture_shows_none_of_its_values() -> None:
    schema = SchemaDef.model_validate(
        {
            "id": "01900000-0000-7000-8000-000000000001",
            "origin": "user",
            "status": "active",
            "name": "synthetic_listing",
            "page_kind": "listing",
            "fields": {
                "title": {"type": "text", "description": "d", "scope": "row"},
                "url": {"type": "url", "description": "d", "scope": "row"},
                "price": {"type": "money", "description": "d", "scope": "row"},
            },
        }
    )
    labels = _labels(
        {"title": "Table Lamp", "url": "https://shop.example.test/p/elsewhere"},  # its text is shown
        {"title": "Sofa", "url": "https://shop.example.test/p/sofa"},  # neither is shown
        {"price": {"amount": "1.00", "currency": "EUR"}},  # presence unknown
    )

    marked = stale_rows(labels, schema, Capture(DOCUMENT))

    assert [row.stale for row in marked.rows] == [False, True, False]
