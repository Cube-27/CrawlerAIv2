"""The record exporters that write files: `xlsx` (an Excel workbook, ECMA-376 / ISO/IEC 29500, by openpyxl) and
`parquet` (Apache Parquet, by pyarrow, an optional extra). They write the table the text exports do (`records.table`):
a column per field in name order, then a status column each.

A cell keeps the published value's type where the format has one: a string, a number or a boolean; a value with
structure (an object, a list) is its JSON text, as the CSV export writes it. An `xlsx` string is always stored as text,
so a value that starts with `=` is never a formula (OWASP CSV Injection), whatever `csv_safe` says. Excel refuses a cell
past 32,767 characters and control characters (ECMA-376 §18.3.1.4), so a longer string is cut to the limit and the
control characters are dropped. A `parquet` column is the narrowest type that holds all its values (boolean, 64-bit
integer, double or string), and a string when they differ.
"""

import io
import json
from collections.abc import Sequence
from typing import Any, Literal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from pydantic import JsonValue

from crawlerai.config_ir.exporters.records import table
from crawlerai.resolve.records import RecordContent
from crawlerai.schemas.types import SchemaDocument

FileFormat = Literal["xlsx", "parquet"]
# The media types of the files, as IANA registers them: the OOXML spreadsheet, and Parquet.
MEDIA_TYPES: dict[FileFormat, str] = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "parquet": "application/vnd.apache.parquet",
}
_XLSX_CELL_MAX = 32_767


class FormatUnavailable(Exception):
    """The format's library is not installed (`parquet` needs the `parquet` extra)."""


def export_file(fmt: FileFormat, schema: SchemaDocument, records: Sequence[RecordContent]) -> bytes:
    """`records`, all of `schema`, as the bytes of a file in `fmt`. Raises `FormatUnavailable` for `parquet` without
    pyarrow, and `ValueError` for a record whose fields are not the schema's."""
    columns, rows = table(schema, records)
    return _xlsx(columns, rows) if fmt == "xlsx" else _parquet(columns, rows)


def _xlsx(columns: list[str], rows: list[dict[str, JsonValue]]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("records")
    sheet.append(columns)
    for row in rows:
        sheet.append([_xlsx_cell(sheet, row[column]) for column in columns])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _xlsx_cell(sheet: Any, value: JsonValue) -> Any:
    """The value as a cell: a text cell for any string, so no value is read as a formula."""
    if value is None or isinstance(value, bool | int | float):
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False)
    cleaned = ILLEGAL_CHARACTERS_RE.sub("", text)[:_XLSX_CELL_MAX]
    cell = WriteOnlyCell(sheet, value=cleaned)
    cell.data_type = "s"
    return cell


def _parquet(columns: list[str], rows: list[dict[str, JsonValue]]) -> bytes:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise FormatUnavailable("parquet needs pyarrow: install the `parquet` extra") from e
    arrays = {column: _column([row[column] for row in rows], pa) for column in columns}
    out = io.BytesIO()
    pq.write_table(pa.table(arrays), out)
    return out.getvalue()


def _column(values: list[JsonValue], pa: Any) -> Any:
    present = [value for value in values if value is not None]
    if present and all(isinstance(value, bool) for value in present):
        return pa.array(values, type=pa.bool_())
    integers = all(isinstance(value, int) and not isinstance(value, bool) for value in present)
    if present and integers and all(-(2**63) <= value < 2**63 for value in present if isinstance(value, int)):
        return pa.array(values, type=pa.int64())
    numbers = all(isinstance(value, int | float) and not isinstance(value, bool) for value in present)
    if present and numbers and not integers:
        return pa.array(values, type=pa.float64())
    return pa.array([_text(value) for value in values], type=pa.string())


def _text(value: JsonValue) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
