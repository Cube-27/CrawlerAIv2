"""JSON documents as collectors read them (parsed by `core.json_text`, JSON-LD blocks leniently), addressed by RFC 9535
normalized paths (`$['offers'][0]`), the path part of the `jsonld`, `js_state`, `xhr` and
`adapter` locators, and queried with the RFC 9535 subset adapter maps are written in."""

import re
from collections.abc import Iterator
from typing import TypeGuard

from pydantic import JsonValue

ROOT = "$"  # RFC 9535 §2.2: the root identifier

# RFC 9535 §2.7: a normalized path writes a member name in single quotes, escaping `'`, `\` and control characters.
_ESCAPES = {"'": "\\'", "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def member(path: str, name: str) -> str:
    escaped = "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " else c) for c in name)
    return f"{path}['{escaped}']"


def scalars(document: JsonValue) -> Iterator[tuple[str, str | int | float]]:
    """Every string and number in `document` with its normalized path, in document order. `true`, `false` and `null`
    are left out: they are not values of any field type."""
    return ((path, value) for path, value in nodes(document) if is_scalar(value))


def nodes(document: JsonValue, *, wildcard: bool = False) -> Iterator[tuple[str, JsonValue]]:
    """Every node of `document` with its normalized path, in document order; with `wildcard`, array indices are
    written `[*]` (RFC 9535 §2.5.1.2). Iterative, so that nesting depth is bounded by what the parser accepts rather
    than by the call stack."""
    stack: list[tuple[str, JsonValue]] = [(ROOT, document)]
    while stack:
        path, value = stack.pop()
        yield path, value
        children: list[tuple[str, JsonValue]] = []
        if isinstance(value, dict):
            children = [(member(path, key), child) for key, child in value.items()]
        elif isinstance(value, list):
            children = [(f"{path}[{'*' if wildcard else i}]", child) for i, child in enumerate(value)]
        stack.extend(reversed(children))


def is_scalar(value: JsonValue) -> TypeGuard[str | int | float]:
    """A string or a number; a JSON boolean is not one, though Python's `bool` is an `int`."""
    return isinstance(value, (str, int, float)) and not isinstance(value, bool)


def select(query: str, document: JsonValue, at: str = ROOT) -> list[tuple[str, JsonValue]]:
    """The nodes `query` selects in `document`, in document order, each with its normalized path; `at` is the path of
    `document` itself. The query is `$` followed by name segments (`['name']`, RFC 9535 §2.5.1.1, the name holding no
    quote or backslash), wildcard segments (`[*]`) and non-negative index segments (`[0]`), so a
    normalized path is one; raises `ValueError` for any other query."""
    if not query.startswith(ROOT) or _QUERY_SEGMENTS.fullmatch(query, len(ROOT)) is None:
        raise ValueError(f"not a query of name, wildcard and index segments: {query!r}")
    nodes: list[tuple[str, JsonValue]] = [(at, document)]
    for name, selector in _SEGMENT.findall(query, len(ROOT)):
        nodes = [child for node in nodes for child in _children(*node, name, selector)]
    return nodes


def is_query(query: str) -> bool:
    """Whether `select` takes `query`: a normalized path is one unless a member name holds a quote or a backslash."""
    return query.startswith(ROOT) and _QUERY_SEGMENTS.fullmatch(query, len(ROOT)) is not None


def segments(query: str) -> list[str]:
    """The segments of a query `select` takes (`['name']`, `[*]`, `[0]`), as written; raises `ValueError` for any
    other query."""
    if not query.startswith(ROOT) or _QUERY_SEGMENTS.fullmatch(query, len(ROOT)) is None:
        raise ValueError(f"not a query of name, wildcard and index segments: {query!r}")
    return [found[0] for found in _SEGMENT.finditer(query, len(ROOT))]


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


# A name segment captures its name in the first group; a wildcard or index segment, `*` or the index, in the second.
_ALL = "*"
_SEGMENT = re.compile(r"\['([^'\\]+)'\]|\[(\*|0|[1-9]\d*)\]", re.ASCII)
_QUERY_SEGMENTS = re.compile(rf"(?:{_SEGMENT.pattern})*", re.ASCII)
