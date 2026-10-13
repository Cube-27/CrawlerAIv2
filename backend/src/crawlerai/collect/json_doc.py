"""JSON documents as collectors read them: parsed strictly as RFC 8259 JSON, and addressed by RFC 9535 normalized
paths (`$['offers'][0]`), the path part of the `jsonld`, `js_state` and `xhr` locators (SPEC-05 §4.3)."""

import json
from collections.abc import Iterator

from pydantic import JsonValue

ROOT = "$"  # RFC 9535 §2.2: the root identifier

# RFC 9535 §2.7: a normalized path writes a member name in single quotes, escaping `'`, `\` and control characters.
_ESCAPES = {"'": "\\'", "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def member(path: str, name: str) -> str:
    escaped = "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " else c) for c in name)
    return f"{path}['{escaped}']"


def parse(text: str) -> JsonValue:
    """`text` as one JSON value; raises `ValueError` when it is not JSON."""
    try:
        parsed: JsonValue = json.loads(text, parse_constant=_not_json)
    except RecursionError:
        raise ValueError("nested too deeply") from None
    return parsed


def parse_prefix(text: str, start: int) -> JsonValue:
    """The JSON value that starts at `text[start]` after optional whitespace, ignoring what follows it; raises
    `ValueError` when none does."""
    decoder = json.JSONDecoder(parse_constant=_not_json)
    while start < len(text) and text[start] in _WHITESPACE:
        start += 1
    try:
        parsed: JsonValue = decoder.raw_decode(text, start)[0]
    except RecursionError:
        raise ValueError("nested too deeply") from None
    return parsed


def scalars(document: JsonValue) -> Iterator[tuple[str, str | int | float]]:
    """Every string and number in `document` with its normalized path, in document order. `true`, `false` and `null`
    are left out: they are not values of any field type. Iterative, so that nesting depth is bounded by what the parser
    accepts rather than by the call stack."""
    stack: list[tuple[JsonValue, str]] = [(document, ROOT)]
    while stack:
        value, path = stack.pop()
        if isinstance(value, dict):
            stack.extend((child, member(path, key)) for key, child in reversed(value.items()))
        elif isinstance(value, list):
            stack.extend((item, f"{path}[{i}]") for i, item in reversed(list(enumerate(value))))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            yield path, value


# RFC 8259 §2: insignificant whitespace is space, horizontal tab, line feed and carriage return.
_WHITESPACE = " \t\n\r"


def _not_json(constant: str) -> JsonValue:
    # RFC 8259 §6: `NaN` and `Infinity` are not JSON numbers, though Python's parser reads them.
    raise ValueError(f"{constant} is not JSON")
