"""Record exporters (SPEC-08 §4.11): every published value and status comes back out of the CSV and JSON exports,
and the CSV header depends on the schema alone ("CSV columns stable", PR plan row 12). A clean record (SPEC-14 §4.4)
has exactly the schema's fields, in schema order, and no status column."""

import csv
import io
import json
import random

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.config_ir.exporters.records import clean_record, export_records
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.resolve.types import FieldStatus
from crawlerai.schemas.types import NAME_PATTERN, FieldSpec, FieldType, SchemaDocument

_TEXT = FieldSpec(type=FieldType.TEXT, description="d")
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


@st.composite
def _page(draw: st.DrawFn) -> tuple[SchemaDocument, list[RecordContent]]:
    names = draw(_names)
    schema = SchemaDocument(name="thing", version=1, page_kind="detail", fields=dict.fromkeys(names, _TEXT))
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


@given(_page(), st.randoms())
def test_csv_header_depends_on_the_schema_alone(
    page: tuple[SchemaDocument, list[RecordContent]], rng: random.Random
) -> None:
    schema, records = page
    names = list(schema.fields)
    rng.shuffle(names)
    reordered = schema.model_copy(update={"fields": {name: schema.fields[name] for name in names}})

    header = export_records("csv_records", reordered, records).split("\r\n", 1)[0]

    assert header == ",".join([*sorted(names), *(f"_status_{name}" for name in sorted(names))])


@given(_page())
def test_a_clean_record_has_exactly_the_schemas_fields_in_schema_order(
    page: tuple[SchemaDocument, list[RecordContent]],
) -> None:
    schema, records = page

    for record in records:
        clean = clean_record(schema, record.data)
        assert list(clean) == list(schema.fields)
        assert not any(name.startswith("_status_") for name in clean)
        assert clean == {name: record.data.get(name) for name in schema.fields}
