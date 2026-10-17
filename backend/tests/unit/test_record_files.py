"""The record file exports (`config_ir.exporters.files`, `records.export_records` `jsonl`): the table every export
shares, written as JSON Lines, an Excel workbook and an Apache Parquet file."""

import io
import json
from typing import Any

import openpyxl
import pyarrow.parquet as pq
import pytest

from crawlerai.config_ir.exporters.files import FormatUnavailable, export_file
from crawlerai.config_ir.exporters.records import export_records
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.resolve.types import FieldStatus
from crawlerai.schemas.types import SchemaDocument

SCHEMA = SchemaDocument.model_validate(
    {
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {
            "title": {"type": "text", "description": "d"},
            "stock": {"type": "count", "description": "d"},
            "rating": {"type": "number", "description": "d"},
            "tags": {"type": "list", "description": "d", "item": {"type": "text", "description": "d"}},
        },
    }
)


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


def _record(data: dict[str, Any]) -> RecordContent:
    meta = {name: _meta("published" if name in data else "missing") for name in SCHEMA.fields}
    return RecordContent(data=data, field_meta=meta, complete=True)


RECORDS = [
    _record({"title": "Kettle", "stock": 4, "rating": 4.5, "tags": ["a", "b"]}),
    _record({"title": '=HYPERLINK("http://x.test")', "stock": 10}),
    _record({"title": "Lamp\x07 with a bell"}),
]


def test_jsonl_is_one_json_object_per_line_in_the_csv_columns() -> None:
    lines = export_records("jsonl", SCHEMA, RECORDS).splitlines()
    rows = [json.loads(line) for line in lines]
    assert len(rows) == 3
    assert list(rows[0]) == ["rating", "stock", "tags", "title", *[f"_status_{n}" for n in sorted(SCHEMA.fields)]]
    assert rows[0]["tags"] == ["a", "b"]
    assert rows[1]["rating"] is None
    assert rows[1]["_status_rating"] == "missing"


def test_jsonl_of_no_records_is_empty() -> None:
    assert export_records("jsonl", SCHEMA, []) == ""


def _sheet(data: bytes) -> list[tuple[Any, ...]]:
    return list(openpyxl.load_workbook(io.BytesIO(data))["records"].iter_rows(values_only=True))


def test_xlsx_has_the_columns_then_one_row_per_record_with_numbers_as_numbers() -> None:
    rows = _sheet(export_file("xlsx", SCHEMA, RECORDS))
    assert rows[0][:4] == ("rating", "stock", "tags", "title")
    assert rows[1][:4] == (4.5, 4, '["a","b"]', "Kettle")
    assert rows[1][4:] == ("published", "published", "published", "published")


def test_xlsx_stores_a_formula_looking_string_as_text_and_drops_control_characters() -> None:
    workbook = openpyxl.load_workbook(io.BytesIO(export_file("xlsx", SCHEMA, RECORDS)))
    sheet = workbook["records"]
    assert sheet["D3"].value == '=HYPERLINK("http://x.test")'
    assert sheet["D3"].data_type == "s"
    assert sheet["D4"].value == "Lamp with a bell"


def test_xlsx_cuts_a_string_to_the_cell_limit() -> None:
    long = _record({"title": "x" * 40_000})
    assert len(_sheet(export_file("xlsx", SCHEMA, [long]))[1][3]) == 32_767


def test_parquet_columns_take_the_narrowest_type_that_holds_their_values() -> None:
    table = pq.read_table(io.BytesIO(export_file("parquet", SCHEMA, RECORDS)))
    types = {field.name: str(field.type) for field in table.schema}
    assert types["stock"] == "int64"
    assert types["rating"] == "double"
    assert types["title"] == "string"
    assert types["tags"] == "string"
    assert table.column("tags").to_pylist() == ['["a","b"]', None, None]
    assert table.column("stock").to_pylist() == [4, 10, None]


def test_parquet_writes_a_string_column_where_values_differ_in_type() -> None:
    mixed = [_record({"title": "a", "stock": 1}), _record({"title": "b", "stock": "many"})]
    table = pq.read_table(io.BytesIO(export_file("parquet", SCHEMA, mixed)))
    assert table.column("stock").to_pylist() == ["1", "many"]


def test_parquet_without_pyarrow_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(__import__("sys").modules, "pyarrow", None)
    with pytest.raises(FormatUnavailable):
        export_file("parquet", SCHEMA, RECORDS)


def test_a_record_with_other_fields_than_the_schemas_is_refused() -> None:
    wrong = RecordContent(data={}, field_meta={}, complete=True)
    with pytest.raises(ValueError, match="is not of the schema"):
        export_file("xlsx", SCHEMA, [wrong])
