"""The RSC Flight reader (extraction spec, "Source documents"): the rows of a React Server Components payload, read by
the wire format React's client reads (`packages/react-client/src/ReactFlightClient.js`), without evaluating anything.

The payload is a byte stream of rows `<hex id>:<tag?><payload>`. After the `:`, a byte of `_LENGTH_TAGS` is the row's
tag and is followed by `<hex length>,` and that many bytes (no line end): `T` is UTF-8 text, the others typed arrays,
which hold no document and are skipped. Any other uppercase letter, `#`, `r` or `x` is a tag whose payload runs to the
next `\\n` (module, hint, error, debug and stream rows), kept as text. Any other byte starts the JSON model, which runs
to the next `\\n`: the rows the engine reads as documents. Inside it, a string starting with `$` is no text the page
states (`parseModelString`): `$$` is an escaped `$` and reads as one, `$D<ISO 8601>` a Date and `$n<digits>` a BigInt
read as the text after the tag, and any other (`$L` lazy, `$@` promise, `$<hex id>` another row, `$undefined`, ...) a
reference or special value, which reads as null: the value is elsewhere or none, and its tag is no value of the page
(`"$1"` is no count of one).

A row that does not follow the grammar, or whose JSON or text does not decode, adds a diagnostic and the rows after it
are still read; a length past the end of the stream ends it. A stream over `MAX_BYTES` is not read.
"""

import re
from dataclasses import dataclass

from pydantic import JsonValue

from crawlerai.core.json_text import parse

MAX_BYTES = 10_000_000
# ReactFlightClient.js `processBinaryChunk`: the tags whose rows are length-prefixed, and the other tags.
_LENGTH_TAGS = frozenset(b"TAOobUSsLlGgMmV")
_LINE_TAGS = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ#rx")
_ROW_ID = re.compile(rb"([0-9a-fA-F]+):")
_LENGTH = re.compile(rb"([0-9a-fA-F]+),")
_TEXT = "T"
# ReactFlightClient.js `parseModelString`: the escape of a string starting with `$`, and the tags of a Date and a
# BigInt, whose text follows the tag.
_ESCAPE = "$$"
_TEXT_VALUES = ("$D", "$n")


@dataclass(frozen=True, slots=True)
class Row:
    """One row: its id as written, its tag (`""` for the JSON model) and its value (the JSON model, or text)."""

    id: str
    tag: str
    value: JsonValue


def read_rows(data: bytes, source: str, diagnostics: list[str]) -> list[Row]:
    """The rows of the Flight stream `data`, in order; each problem adds a diagnostic prefixed with `source`."""
    if len(data) > MAX_BYTES:
        diagnostics.append(f"{source}: RSC payload over {MAX_BYTES} bytes")
        return []
    reader = _Reader(data, source, diagnostics)
    pos = 0
    while pos < len(data):
        pos = pos + 1 if data[pos] == 0x0A else reader.row(pos)  # a line end between rows
    return reader.rows


class _Reader:
    def __init__(self, data: bytes, source: str, diagnostics: list[str]) -> None:
        self.data, self.source, self.diagnostics = data, source, diagnostics
        self.rows: list[Row] = []

    def row(self, pos: int) -> int:
        """Read the row at `pos`; the index after it (past the end when the stream ends there)."""
        data = self.data
        head = _ROW_ID.match(data, pos)
        if head is None:
            return self._skip(pos, f"RSC row without an id at byte {pos}")
        row_id, pos = head.group(1).decode(), head.end()
        tag = data[pos] if pos < len(data) else None
        if tag in _LENGTH_TAGS:
            length = _LENGTH.match(data, pos + 1)
            if length is None:
                return self._skip(pos, f"RSC row {row_id} without a length")
            end = length.end() + int(length.group(1), 16)
            if end > len(data):
                self.diagnostics.append(f"{self.source}: RSC row {row_id} longer than the payload")
                return len(data)
            if tag == ord(_TEXT):
                self._text(row_id, _TEXT, data[length.end() : end])
            return end
        end = _line_end(data, pos)
        if tag in _LINE_TAGS:
            self._text(row_id, chr(tag), data[pos + 1 : end])
        else:
            self._model(row_id, data[pos:end])
        return end + 1

    def _skip(self, pos: int, problem: str) -> int:
        """Note `problem` and go on at the next line."""
        self.diagnostics.append(f"{self.source}: {problem}")
        return _line_end(self.data, pos) + 1

    def _text(self, row_id: str, tag: str, payload: bytes) -> None:
        try:
            self.rows.append(Row(row_id, tag, payload.decode("utf-8")))
        except UnicodeDecodeError as e:
            self.diagnostics.append(f"{self.source}: RSC row {row_id} is not UTF-8 ({e})")

    def _model(self, row_id: str, payload: bytes) -> None:
        try:
            self.rows.append(Row(row_id, "", _unescaped(parse(payload.decode("utf-8")))))
        except (ValueError, RecursionError) as e:  # UnicodeDecodeError is a ValueError
            self.diagnostics.append(f"{self.source}: RSC row {row_id} is not JSON ({e})")


def model_rows(rows: list[Row]) -> dict[str, JsonValue] | None:
    """The JSON model rows' values by row id, a Flight stream's one document (extraction spec, "Source documents");
    None when it has none."""
    found: dict[str, JsonValue] = {row.id: row.value for row in rows if not row.tag}
    return found or None


def _line_end(data: bytes, pos: int) -> int:
    end = data.find(b"\n", pos)
    return len(data) if end < 0 else end


def _unescaped(value: JsonValue) -> JsonValue:
    """`value` with each string value read by its `$` tag (module docstring; object keys are not tagged)."""
    if isinstance(value, str):
        return _model_string(value)
    if isinstance(value, list):
        return [_unescaped(item) for item in value]
    if isinstance(value, dict):
        return {key: _unescaped(member) for key, member in value.items()}
    return value


def _model_string(value: str) -> str | None:
    if not value.startswith("$"):
        return value
    if value.startswith(_ESCAPE):
        return value[1:]
    return value[2:] if value.startswith(_TEXT_VALUES) else None
