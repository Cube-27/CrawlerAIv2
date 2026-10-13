"""JSON documents as collectors read them: parsed strictly as RFC 8259 JSON, addressed by RFC 9535 normalized paths
(`$['offers'][0]`), the path part of the `jsonld`, `js_state`, `xhr` and `adapter` locators (SPEC-05 §4.3), and
queried with the RFC 9535 subset adapter maps are written in."""

import json
import re
from collections.abc import Callable, Iterator

from pydantic import JsonValue

ROOT = "$"  # RFC 9535 §2.2: the root identifier

# RFC 9535 §2.7: a normalized path writes a member name in single quotes, escaping `'`, `\` and control characters.
_ESCAPES = {"'": "\\'", "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def member(path: str, name: str) -> str:
    escaped = "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " else c) for c in name)
    return f"{path}['{escaped}']"


def parse(text: str) -> JsonValue:
    """`text` as one JSON value; raises `ValueError` when it is not JSON."""
    return _guarded(lambda: _DECODER.decode(text))


def parse_prefix(text: str, start: int) -> JsonValue:
    """The JSON value that starts at `text[start]` after optional whitespace, ignoring what follows it; raises
    `ValueError` when none does."""
    found = _NOT_WHITESPACE.search(text, start)
    start = len(text) if found is None else found.start()
    return _guarded(lambda: _DECODER.raw_decode(text, start)[0])


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
            stack.extend((value[i], f"{path}[{i}]") for i in range(len(value) - 1, -1, -1))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            yield path, value


def select(query: str, document: JsonValue, at: str = ROOT) -> list[tuple[str, JsonValue]]:
    """The nodes `query` selects in `document`, in document order, each with its normalized path; `at` is the path of
    `document` itself. The query is `$` followed by name segments (`['name']`, RFC 9535 §2.5.1.1, the name holding no
    quote or backslash), wildcard segments (`[*]`, §2.5.1.2) and non-negative index segments (`[0]`, §2.3.3), so a
    normalized path is one; raises `ValueError` for any other query."""
    if not query.startswith(ROOT) or _QUERY_SEGMENTS.fullmatch(query, len(ROOT)) is None:
        raise ValueError(f"not a query of name, wildcard and index segments: {query!r}")
    nodes: list[tuple[str, JsonValue]] = [(at, document)]
    for name, selector in _SEGMENT.findall(query, len(ROOT)):
        nodes = [child for node in nodes for child in _children(*node, name, selector)]
    return nodes


def _children(path: str, value: JsonValue, name: str, selector: str) -> Iterator[tuple[str, JsonValue]]:
    """The children of one node that a segment selects: the member `name`, else every child (`selector` `*`) or the
    array item at index `selector` (RFC 9535 §2.3); a node of another kind has none."""
    if name:
        if isinstance(value, dict) and name in value:
            yield member(path, name), value[name]
    elif isinstance(value, dict) and selector == _ALL:
        yield from ((member(path, key), child) for key, child in value.items())
    elif isinstance(value, list) and selector == _ALL:
        yield from ((f"{path}[{i}]", item) for i, item in enumerate(value))
    elif isinstance(value, list) and int(selector) < len(value):
        yield f"{path}[{selector}]", value[int(selector)]


def _not_json(constant: str) -> JsonValue:
    # RFC 8259 §6: `NaN` and `Infinity` are not JSON numbers, though Python's parser reads them.
    raise ValueError(f"{constant} is not JSON")


def _guarded(decode: Callable[[], JsonValue]) -> JsonValue:
    try:
        return decode()
    except RecursionError:
        raise ValueError("nested too deeply") from None


_DECODER = json.JSONDecoder(parse_constant=_not_json)
# RFC 8259 §2: insignificant whitespace is space, horizontal tab, line feed and carriage return.
_NOT_WHITESPACE = re.compile(r"[^ \t\n\r]")
# A name segment captures its name in the first group; a wildcard or index segment, `*` or the index, in the second.
_ALL = "*"
_SEGMENT = re.compile(r"\['([^'\\]+)'\]|\[(\*|0|[1-9][0-9]*)\]")
_QUERY_SEGMENTS = re.compile(rf"(?:{_SEGMENT.pattern})*")
