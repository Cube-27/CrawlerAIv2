"""Record exporters: a page of records as `json_records`, `csv_records`, `markdown`
or `jsonl` (JSON Lines: one row as a JSON object per line), for `GET /v1/jobs/{id}/results?format=` (the API wires the
endpoint). The binary formats, `xlsx` and `parquet`, read the same table (`files`).

The formats share one table (`table`): a column per schema field, holding the published value or nothing, then a
`_status_<field>` column per field. Columns are in field-name order, so they depend on the schema alone and not on
the order its fields were declared or stored in (JSONB does not keep key order). Schema names start with a
lowercase letter (`NAME_PATTERN`), so a status column never collides with a field. A job's export adds its records'
delta: `_delta` (`new`, `changed`, `same`) and `_previous`, the previous published value of
each changed field by name. Values are serialized as
published and never fixed; a `csv_safe` CSV only marks formula-like cells for spreadsheets.

A clean record (`json_values`) is a record's published values alone, with no status: the schema's
published fields in name order, an unpublished one left out. A money value is written flat: the field holds its amount
and a sibling `currency` (for a field named `price`) or `<field>_currency` its ISO 4217 code, the first key that names
no schema field (when both do, the money value is written whole); objects nested in the
record, such as variant rows, are written the same way.
"""

import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import JsonValue

from crawlerai.resolve.records import Delta, RecordContent
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument

RecordFormat = Literal["json_records", "csv_records", "markdown", "jsonl"]

_STATUS_PREFIX = "_status_"
_DELTA_COLUMNS = ("_delta", "_previous")
# CommonMark 0.31 §2.4: any ASCII punctuation character may be backslash-escaped, and then renders literally.
_MD_PUNCTUATION = re.compile(r"""([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""")
# CommonMark 0.31 §2.6 line endings; a GFM table cell holds no line ending, so one becomes an HTML line break.
_LINE_ENDING = re.compile(r"\r\n|\r|\n")
# OWASP CSV Injection: spreadsheet applications read a cell starting with one of these as a formula; a leading `'`
# makes them show it as text.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

_Row = dict[str, JsonValue]


def export_records(
    fmt: RecordFormat,
    schema: SchemaDocument,
    records: Sequence[RecordContent],
    *,
    csv_safe: bool = False,
    deltas: Sequence[Delta | None] | None = None,
) -> str:
    """`records`, all of `schema`, in `fmt`, with each record's delta when `deltas` is given (`table`). A record whose
    fields are not the schema's is refused (`ValueError`). `csv_safe` (`csv_records` only): a cell a
    spreadsheet would read as a formula starts with `'`."""
    columns, rows = table(schema, records, deltas)
    if fmt == "json_records":
        return _json(rows)
    if fmt == "jsonl":
        return "".join(_json(row) + "\n" for row in rows)
    if fmt == "csv_records":
        return _csv(columns, rows, safe=csv_safe)
    return _markdown(columns, rows)


def table(
    schema: SchemaDocument, records: Sequence[RecordContent], deltas: Sequence[Delta | None] | None = None
) -> tuple[list[str], list[dict[str, JsonValue]]]:
    """The columns and rows every export shares: a column per field of `schema` in name order, then a status column
    each, then with `deltas` (one per record) `_delta` and `_previous`; one row per record, a column's value being the
    published value or None. A record whose fields are not the schema's is refused (`ValueError`)."""
    fields = sorted(schema.fields)
    columns = [*fields, *(_STATUS_PREFIX + name for name in fields)]
    rows = [_row(fields, record) for record in records]
    if deltas is None:
        return columns, rows
    return [*columns, *_DELTA_COLUMNS], [row | _delta_cells(delta) for row, delta in zip(rows, deltas, strict=True)]


def _delta_cells(delta: Delta | None) -> _Row:
    if delta is None:
        return dict.fromkeys(_DELTA_COLUMNS)
    previous: _Row = {change.field: change.previous for change in delta.changes}
    return {"_delta": delta.kind, "_previous": previous or None}


def clean_record(schema: SchemaDocument, data: Mapping[str, JsonValue]) -> _Row:
    """A record's published values `data` as a clean record of `schema`, its fields in name order as the columns."""
    return _clean_object(schema.fields, data)


def _clean_object(fields: Mapping[str, FieldSpec], data: Mapping[str, JsonValue]) -> _Row:
    clean: _Row = {}
    for name in sorted(fields):
        value = data.get(name)
        if value is None:
            continue
        spec = fields[name]
        currency_key = _currency_key(name, fields) if spec.type is FieldType.MONEY else None
        if currency_key is not None and isinstance(value, dict):
            clean[name] = value.get("amount")
            clean[currency_key] = value.get("currency")
        else:
            clean[name] = _clean_value(value, spec)
    return clean


def _clean_value(value: JsonValue, spec: FieldSpec) -> JsonValue:
    if spec.type is FieldType.LIST and spec.item is not None and isinstance(value, list):
        return [_clean_value(item, spec.item) for item in value]
    if spec.type is FieldType.OBJECT and spec.fields is not None and isinstance(value, dict):
        return _clean_object(spec.fields, value)
    return value


def _currency_key(name: str, fields: Mapping[str, FieldSpec]) -> str | None:
    """The key of a money field's currency: `currency` beside `price`, else `<name>_currency`, the first that names no
    field of the schema; None when both do, and the money value is then written whole."""
    candidates = ["currency", f"{name}_currency"] if name == "price" else [f"{name}_currency"]
    return next((key for key in candidates if key not in fields), None)


def _row(fields: list[str], record: RecordContent) -> _Row:
    if sorted(record.field_meta) != fields:
        raise ValueError(f"a record with fields {sorted(record.field_meta)} is not of the schema's {fields}")
    values: _Row = {name: record.data.get(name) for name in fields}
    statuses: _Row = {_STATUS_PREFIX + name: record.field_meta[name].status for name in fields}
    return values | statuses


def _json(value: object) -> str:
    # RFC 8259: UTF-8 text, so non-ASCII characters are written as themselves; NaN and infinities are not JSON.
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _cell(value: JsonValue) -> str:
    """A value as one cell's text: nothing for an unpublished field, a string as itself, anything else as JSON."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _json(value)


def _csv(columns: list[str], rows: list[_Row], *, safe: bool) -> str:
    # RFC 4180: a header line, CRLF line breaks, and fields with separators, quotes or line breaks quoted.
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(columns)
    cell = _safe_cell if safe else _cell
    writer.writerows([cell(row[column]) for column in columns] for row in rows)
    return out.getvalue()


def _safe_cell(value: JsonValue) -> str:
    text = _cell(value)
    return "'" + text if text.startswith(_FORMULA_TRIGGERS) else text


def _md_cell(text: str) -> str:
    return _LINE_ENDING.sub("<br>", _MD_PUNCTUATION.sub(r"\\\1", text))


def _md_line(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |\n"


def _markdown(columns: list[str], rows: list[_Row]) -> str:
    # GFM 0.29 §4.10: a header row, a delimiter row, then one row per record.
    lines = [_md_line([_md_cell(column) for column in columns]), _md_line(["---"] * len(columns))]
    lines += [_md_line([_md_cell(_cell(row[column])) for column in columns]) for row in rows]
    return "".join(lines)
