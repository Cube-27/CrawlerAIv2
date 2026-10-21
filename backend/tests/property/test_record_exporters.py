"""Record exporters (learning-configs spec, PR 12): every published value and status comes back out of the CSV and JSON
exports, and the CSV header depends on the schema alone ("CSV columns stable", PR plan row 12). `json_records`,
`csv_records` and `markdown` run over a page of records. A clean record (frontend spec, `json_values`) has the schema's
published fields, in the columns' name order, and no status column."""

import csv
import io
import json

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir.exporters.records import clean_record, export_records
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.resolve.types import FieldStatus
from crawlerai.schemas.types import NAME_PATTERN, FieldSpec, FieldType, SchemaDocument

_TEXT = FieldSpec(type=FieldType.TEXT, description="d")
# Declared out of name order: columns follow the names, not the declaration (or JSONB's storage order).
SCHEMA = SchemaDocument(name="thing", page_kind="detail", fields={"title": _TEXT, "price": _TEXT})
_MONEY = FieldSpec(type=FieldType.MONEY, description="d")
_EUR: JsonValue = {"amount": "9.50", "currency": "EUR"}
_names = st.lists(st.from_regex(rf"\A{NAME_PATTERN}\Z"), min_size=1, max_size=5, unique=True)
_scalars = st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text()
_json_values: st.SearchStrategy[JsonValue] = st.recursive(
    _scalars,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=6,
)
_statuses: st.SearchStrategy[FieldStatus] = st.sampled_from(["published", "missing", "conflict", "abstained"])


def _meta(status: FieldStatus) -> FieldMeta:
    return FieldMeta(
        status=status,
        reason=None,
        evidence=None,
        confidence=None,
        calibrated=False,
        source_kind=None,
        locator=None,
        derived_by=None,
    )


def _record(**values: JsonValue) -> RecordContent:
    """A record whose fields in `values` published those values; the schema's other fields are `missing`."""
    meta = {name: _meta("published" if name in values else "missing") for name in SCHEMA.fields}
    return RecordContent(data=dict(values), field_meta=meta, complete=len(values) == len(SCHEMA.fields))


@st.composite
def _page(draw: st.DrawFn) -> tuple[SchemaDocument, list[RecordContent]]:
    names = draw(_names)
    schema = SchemaDocument(name="thing", page_kind="detail", fields=dict.fromkeys(names, _TEXT))
    records = []
    for _ in range(draw(st.integers(0, 3))):
        statuses = {name: draw(_statuses) for name in names}
        # A published value is never null (INV-22); a field that did not publish has no value.
        data = {
            name: draw(_json_values.filter(lambda v: v is not None)) for name, s in statuses.items() if s == "published"
        }
        meta = {name: _meta(status) for name, status in statuses.items()}
        records.append(RecordContent(data=data, field_meta=meta, complete=False))
    return schema, records


def _expected(schema: SchemaDocument, record: RecordContent) -> dict[str, JsonValue]:
    values: dict[str, JsonValue] = {name: record.data.get(name) for name in schema.fields}
    return values | {f"_status_{name}": meta.status for name, meta in record.field_meta.items()}


def _decoded(cell: str, expected: JsonValue) -> JsonValue:
    """A CSV cell back as a value, given the type it should have: CSV has no types, so the schema supplies them."""
    if expected is None or isinstance(expected, str):
        return cell or None
    value: JsonValue = json.loads(cell)
    return value


@given(_page())
def test_json_records_round_trip_every_value_and_status(page: tuple[SchemaDocument, list[RecordContent]]) -> None:
    schema, records = page

    assert json.loads(export_records("json_records", schema, records)) == [_expected(schema, r) for r in records]


@given(_page())
def test_csv_cells_round_trip_every_value_and_status(page: tuple[SchemaDocument, list[RecordContent]]) -> None:
    schema, records = page

    header, *rows = csv.reader(io.StringIO(export_records("csv_records", schema, records), newline=""))

    assert len(rows) == len(records)
    for row, record in zip(rows, records, strict=True):
        expected = _expected(schema, record)
        assert {column: _decoded(cell, expected[column]) for column, cell in zip(header, row, strict=True)} == {
            column: value or None if isinstance(value, str) else value for column, value in expected.items()
        }


@given(_page())
def test_csv_safe_cells_are_the_plain_cells_with_a_quote_before_a_formula_trigger(
    page: tuple[SchemaDocument, list[RecordContent]],
) -> None:
    schema, records = page

    plain = list(csv.reader(io.StringIO(export_records("csv_records", schema, records), newline="")))
    safe = list(csv.reader(io.StringIO(export_records("csv_records", schema, records, csv_safe=True), newline="")))

    # OWASP CSV Injection: a cell starting with one of these is read as a formula by spreadsheet applications.
    assert safe == [
        ["'" + cell if cell[:1] in ("=", "+", "-", "@", "\t", "\r") else cell for cell in row] for row in plain
    ]


def test_csv_has_one_column_per_field_then_one_status_column_per_field_in_name_order() -> None:
    text = export_records("csv_records", SCHEMA, [_record(title="Lamp")])

    # Rows end with CRLF, as RFC 4180 §2 says.
    assert text == "price,title,_status_price,_status_title\r\n,Lamp,missing,published\r\n"


def test_markdown_is_a_gfm_table_with_the_csv_columns() -> None:
    text = export_records("markdown", SCHEMA, [_record(title="Lamp", price={"amount": "9"})])

    assert text == (
        "| price | title | \\_status\\_price | \\_status\\_title |\n"
        "| --- | --- | --- | --- |\n"
        '| \\{\\"amount\\"\\:\\"9\\"\\} | Lamp | published | published |\n'
    )


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


def test_a_price_whose_currency_is_unknown_exports_its_amount_with_a_null_currency() -> None:
    schema = SchemaDocument(name="thing", page_kind="detail", fields={"price": _MONEY})

    assert clean_record(schema, {"price": {"amount": "9.50", "currency": None}}) == {"price": "9.50", "currency": None}
