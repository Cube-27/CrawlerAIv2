"""The record file exports (`config_ir.exporters.files`, `records.export_records` `jsonl`): the table every export
shares, written as JSON Lines, an Excel workbook and an Apache Parquet file."""

import io
import json
from typing import Any

import openpyxl

from snowcrawl.config_ir.exporters.files import export_file
from snowcrawl.config_ir.exporters.records import export_records
from snowcrawl.resolve.records import FieldMeta, RecordContent
from snowcrawl.resolve.types import FieldStatus
from snowcrawl.schemas.types import SchemaDocument

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


def _sheet(data: bytes) -> list[tuple[Any, ...]]:
    return list(openpyxl.load_workbook(io.BytesIO(data))["records"].iter_rows(values_only=True))


def test_xlsx_has_the_columns_then_one_row_per_record_with_numbers_as_numbers() -> None:
    rows = _sheet(export_file("xlsx", SCHEMA, RECORDS))
    assert rows[0][:4] == ("rating", "stock", "tags", "title")
    assert rows[1][:4] == (4.5, 4, '["a","b"]', "Kettle")
    assert rows[1][4:] == ("published", "published", "published", "published")
