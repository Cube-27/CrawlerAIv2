"""Record exporters (SPEC-08 §4.11, PR 12): `json_records`, `csv_records` and `markdown` over a page of records, and
the clean records of `json_values` (SPEC-14 §4.4)."""

import json

from pydantic import JsonValue

from crawlerai.config_ir.exporters.records import clean_record, export_records
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.resolve.types import FieldStatus
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument

_TEXT = FieldSpec(type=FieldType.TEXT, description="d")
# Declared out of name order: columns follow the names, not the declaration (or JSONB's storage order).
SCHEMA = SchemaDocument(name="thing", page_kind="detail", fields={"title": _TEXT, "price": _TEXT})


def _meta(status: FieldStatus) -> FieldMeta:
    published = status == "published"
    return FieldMeta(
        status=status,
        reason=None if published else "no_candidates",
        evidence="structured" if published else None,
        confidence=None,
        calibrated=False,
        source_kind="jsonld" if published else None,
        locator=None,
        derived_by=None,
    )


def _record(**values: JsonValue) -> RecordContent:
    """A record whose fields in `values` published those values; the schema's other fields are `missing`."""
    meta = {name: _meta("published" if name in values else "missing") for name in SCHEMA.fields}
    return RecordContent(data=dict(values), field_meta=meta, complete=len(values) == len(SCHEMA.fields))


def test_csv_has_one_column_per_field_then_one_status_column_per_field_in_name_order() -> None:
    text = export_records("csv_records", SCHEMA, [_record(title="Lamp")])

    # Rows end with CRLF, as RFC 4180 §2 says.
    assert text == "price,title,_status_price,_status_title\r\n,Lamp,missing,published\r\n"


def test_csv_safe_prefixes_a_quote_on_cells_a_spreadsheet_reads_as_a_formula() -> None:
    record = _record(title="=HYPERLINK(1)", price=-5)

    text = export_records("csv_records", SCHEMA, [record], csv_safe=True)

    assert text == "price,title,_status_price,_status_title\r\n'-5,'=HYPERLINK(1),published,published\r\n"


def test_json_records_is_an_array_of_objects_with_the_csv_columns() -> None:
    text = export_records("json_records", SCHEMA, [_record(title="Lamp"), _record(price={"amount": "1"})])

    assert json.loads(text) == [
        {"price": None, "title": "Lamp", "_status_price": "missing", "_status_title": "published"},
        {"price": {"amount": "1"}, "title": None, "_status_price": "published", "_status_title": "missing"},
    ]


def test_markdown_is_a_gfm_table_with_the_csv_columns() -> None:
    text = export_records("markdown", SCHEMA, [_record(title="Lamp", price={"amount": "9"})])

    assert text == (
        "| price | title | \\_status\\_price | \\_status\\_title |\n"
        "| --- | --- | --- | --- |\n"
        '| \\{\\"amount\\"\\:\\"9\\"\\} | Lamp | published | published |\n'
    )


_MONEY = FieldSpec(type=FieldType.MONEY, description="d")
_EUR: JsonValue = {"amount": "9.50", "currency": "EUR"}


def test_a_clean_record_has_the_published_fields_in_name_order_and_leaves_out_the_rest() -> None:
    record = clean_record(SCHEMA, {"title": "Lamp", "price": "cheap", "colour": "blue"})

    assert list(record.items()) == [("price", "cheap"), ("title", "Lamp")]
    assert clean_record(SCHEMA, {"price": None}) == {}


def test_another_money_field_or_a_schema_currency_field_names_its_currency_after_the_field() -> None:
    fields = {"price": _MONEY, "list_price": _MONEY, "currency": _TEXT}
    schema = SchemaDocument(name="thing", page_kind="detail", fields=fields)

    assert clean_record(schema, {"price": _EUR, "list_price": _EUR, "currency": "x"}) == {
        "currency": "x",
        "list_price": "9.50",
        "list_price_currency": "EUR",
        "price": "9.50",
        "price_currency": "EUR",
    }
