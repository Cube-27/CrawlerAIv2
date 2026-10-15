"""Record exporters (SPEC-08 §4.11, ARCHITECTURE §12.2): a page of records as `json_records`, `csv_records` or
`markdown`, for `GET /v1/jobs/{id}/results?format=` (SPEC-10 wires the endpoint).

The three formats share one table: a column per schema field, holding the published value or nothing, then a
`_status_<field>` column per field. Columns are in field-name order, so they depend on the schema alone and not on
the order its fields were declared or stored in (JSONB does not keep key order). Schema names start with a
lowercase letter (`NAME_PATTERN`), so a status column never collides with a field. Values are serialized as
published and never fixed (INV-27).

A clean record (`json_values`, SPEC-14 §4.4) is a record's published values alone: the schema's fields in the order
the schema lists them, each with its value or null, and no status.
"""

import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import JsonValue

from crawlerai.resolve.records import RecordContent
from crawlerai.schemas.types import SchemaDocument

RecordFormat = Literal["json_records", "csv_records", "markdown"]

_STATUS_PREFIX = "_status_"
# CommonMark 0.31 §2.4: any ASCII punctuation character may be backslash-escaped, and then renders literally.
_MD_PUNCTUATION = re.compile(r"""([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""")
# CommonMark 0.31 §2.6 line endings; a GFM table cell holds no line ending, so one becomes an HTML line break.
_LINE_ENDING = re.compile(r"\r\n|\r|\n")

_Row = dict[str, JsonValue]


def export_records(fmt: RecordFormat, schema: SchemaDocument, records: Sequence[RecordContent]) -> str:
    """`records`, all of `schema`, in `fmt`. A record whose fields are not the schema's is refused (`ValueError`)."""
    fields = sorted(schema.fields)
    rows = [_row(fields, record) for record in records]
    columns = [*fields, *(_STATUS_PREFIX + name for name in fields)]
    if fmt == "json_records":
        return _json(rows)
    if fmt == "csv_records":
        return _csv(columns, rows)
    return _markdown(columns, rows)


def clean_record(schema: SchemaDocument, data: Mapping[str, JsonValue]) -> _Row:
    """A record's published values `data` as a clean record of `schema`."""
    return {name: data.get(name) for name in schema.fields}


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


def _csv(columns: list[str], rows: list[_Row]) -> str:
    # RFC 4180: a header line, CRLF line breaks, and fields with separators, quotes or line breaks quoted.
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(columns)
    writer.writerows([_cell(row[column]) for column in columns] for row in rows)
    return out.getvalue()


def _md_cell(text: str) -> str:
    return _LINE_ENDING.sub("<br>", _MD_PUNCTUATION.sub(r"\\\1", text))


def _md_line(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |\n"


def _markdown(columns: list[str], rows: list[_Row]) -> str:
    # GFM 0.29 §4.10: a header row, a delimiter row, then one row per record.
    lines = [_md_line([_md_cell(column) for column in columns]), _md_line(["---"] * len(columns))]
    lines += [_md_line([_md_cell(_cell(row[column])) for column in columns]) for row in rows]
    return "".join(lines)
