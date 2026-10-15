"""Record exporters (SPEC-08 §4.11, PR 12): `json_records`, `csv_records` and `markdown` over a page of records, and
the clean records of `json_values` (SPEC-14 §4.4)."""

import csv
import io
import json

import pytest
from pydantic import JsonValue

from crawlerai.config_ir.exporters.records import clean_record, export_records
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.resolve.types import FieldStatus
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument

_TEXT = FieldSpec(type=FieldType.TEXT, description="d")
# Declared out of name order: columns follow the names, not the declaration (or JSONB's storage order).
SCHEMA = SchemaDocument(name="thing", version=1, page_kind="detail", fields={"title": _TEXT, "price": _TEXT})


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


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def test_csv_has_one_column_per_field_then_one_status_column_per_field_in_name_order() -> None:
    text = export_records("csv_records", SCHEMA, [_record(title="Lamp")])

    # Rows end with CRLF, as RFC 4180 §2 says.
    assert text == "price,title,_status_price,_status_title\r\n,Lamp,missing,published\r\n"


def test_csv_header_is_written_for_an_empty_page() -> None:
    assert export_records("csv_records", SCHEMA, []) == "price,title,_status_price,_status_title\r\n"


def test_csv_json_encodes_nested_and_non_string_values() -> None:
    record = _record(title=["a", "b"], price={"amount": "9.50", "currency": "EUR"})

    rows = _csv_rows(export_records("csv_records", SCHEMA, [record]))

    assert rows[1][:2] == ['{"amount":"9.50","currency":"EUR"}', '["a","b"]']


def test_csv_writes_a_string_value_unchanged_even_with_separators_quotes_and_newlines() -> None:
    title = 'say "hi",\nthen =1+1'

    rows = _csv_rows(export_records("csv_records", SCHEMA, [_record(title=title)]))

    assert rows[1][1] == title


def test_json_records_is_an_array_of_objects_with_the_csv_columns() -> None:
    text = export_records("json_records", SCHEMA, [_record(title="Lamp"), _record(price={"amount": "1"})])

    assert json.loads(text) == [
        {"price": None, "title": "Lamp", "_status_price": "missing", "_status_title": "published"},
        {"price": {"amount": "1"}, "title": None, "_status_price": "published", "_status_title": "missing"},
    ]


def test_json_records_keeps_non_ascii_text_as_is() -> None:
    assert '"Größe"' in export_records("json_records", SCHEMA, [_record(title="Größe")])


def test_markdown_is_a_gfm_table_with_the_csv_columns() -> None:
    text = export_records("markdown", SCHEMA, [_record(title="Lamp", price={"amount": "9"})])

    assert text == (
        "| price | title | \\_status\\_price | \\_status\\_title |\n"
        "| --- | --- | --- | --- |\n"
        '| \\{\\"amount\\"\\:\\"9\\"\\} | Lamp | published | published |\n'
    )


def test_markdown_escapes_punctuation_and_line_breaks_so_a_value_renders_literally() -> None:
    text = export_records("markdown", SCHEMA, [_record(title="a|b *c*\nd")])

    assert text.splitlines()[2] == "|  | a\\|b \\*c\\*<br>d | missing | published |"


def test_a_record_of_another_schema_is_refused() -> None:
    stray = RecordContent(data={}, field_meta={"title": _meta("missing")}, complete=False)
    records = [stray]

    with pytest.raises(ValueError, match="schema"):
        export_records("csv_records", SCHEMA, records)


def test_a_clean_record_has_the_schemas_fields_in_its_order_with_null_where_none_published() -> None:
    record = clean_record(SCHEMA, {"price": {"amount": "9.50", "currency": "EUR"}})

    assert list(record.items()) == [("title", None), ("price", {"amount": "9.50", "currency": "EUR"})]


def test_a_clean_record_leaves_out_a_value_of_no_schema_field() -> None:
    assert clean_record(SCHEMA, {"title": "Lamp", "colour": "blue"}) == {"title": "Lamp", "price": None}
