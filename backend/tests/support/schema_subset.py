"""The part of JSON Schema each provider's structured output accepts.

A provider constrains its reply with the request's output schema only when the schema stays inside the provider's
documented subset; outside it, the request is refused with a 400 and nothing is extracted. Every role's output schema
is written inside the subset of every provider, and `violations` is how tests check it.

The subsets are versioned external data (C4): one file per provider under `backend/data/llm/`, transcribed from the
provider's API documentation and pinned in the data manifest with that page; a subset changes when the documentation
does.
"""

from collections.abc import Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, JsonValue

# The subset files, one per provider (`backend/data/manifest.json`).
SUBSET_FILES: Final = {
    "anthropic": Path("llm") / "anthropic-structured-output.json",
    "gemini": Path("llm") / "gemini-structured-output.json",
}
# Keywords whose value is a map of names to subschemas, not a subschema.
# JSON Schema 2020-12 §8.2.4: the keyword of reusable subschemas.
_DEFS: Final = "$defs"
_SCHEMA_MAPS: Final = frozenset({"properties", _DEFS, "definitions"})
_DEFS_PREFIX: Final = "#/$defs/"


class SchemaSubset(BaseModel):
    """One provider's subset file. `keywords`: every keyword it reads. `closed_objects`: every object schema must
    say `additionalProperties: false`. `max_unions` and `max_optional`: caps on the schema's `anyOf` (or type array)
    parameters and on its properties not in `required` (null: no cap). `min_items`: the `minItems` values it accepts
    (null: any). `bare_ref`: a `$ref` must stand alone in its subschema. Neither provider takes a recursive `$ref` in
    the all-required objects the roles use, so no subset allows one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    checked: date
    scope: str
    keywords: frozenset[str]
    closed_objects: bool
    max_unions: int | None
    max_optional: int | None
    min_items: frozenset[int] | None
    bare_ref: bool


def violations(schema: Mapping[str, JsonValue], subset: SchemaSubset) -> list[str]:
    """Why a provider with `subset` would refuse `schema`; empty when it accepts it."""
    found: list[str] = []
    unions = optional = 0
    for path, node in _subschemas(schema, "$"):
        found.extend(_node_violations(path, node, subset))
        unions += "anyOf" in node or isinstance(node.get("type"), list)
        optional += len(_optional(node))
    if subset.max_unions is not None and unions > subset.max_unions:
        found.append(f"$: {unions} union parameters (at most {subset.max_unions})")
    if subset.max_optional is not None and optional > subset.max_optional:
        found.append(f"$: {optional} optional properties (at most {subset.max_optional})")
    cycle = _ref_cycle(schema)
    if cycle is not None:
        found.append(f"$: recursive $ref through {cycle}")
    return found


def _node_violations(path: str, node: Mapping[str, JsonValue], subset: SchemaSubset) -> Iterator[str]:
    for keyword in sorted(set(node) - subset.keywords):
        yield f"{path}: keyword {keyword!r}"
    if subset.closed_objects and _is_object(node) and node.get("additionalProperties") is not False:
        yield f"{path}: object without additionalProperties false"
    if subset.min_items is not None and node.get("minItems", 0) not in subset.min_items:
        yield f"{path}: minItems {node['minItems']}"
    if subset.bare_ref and "$ref" in node and any(not key.startswith("$") for key in node):
        yield f"{path}: $ref with sibling keywords"


def _is_object(node: Mapping[str, JsonValue]) -> bool:
    kind = node.get("type")
    return kind == "object" or (isinstance(kind, list) and "object" in kind) or "properties" in node


def _optional(node: Mapping[str, JsonValue]) -> set[str]:
    properties = node.get("properties")
    if not isinstance(properties, dict):
        return set()
    required = node.get("required")
    return set(properties) - set(required if isinstance(required, list) else [])


def _subschemas(node: Mapping[str, JsonValue], path: str) -> Iterator[tuple[str, Mapping[str, JsonValue]]]:
    """Every subschema of `node`, itself included, with its JSON path."""
    yield path, node
    for child_path, child in _children(node, path):
        yield from _subschemas(child, child_path)


def _children(node: Mapping[str, JsonValue], path: str) -> Iterator[tuple[str, Mapping[str, JsonValue]]]:
    """The subschemas directly under `node`: in a map of names, under a keyword, or in a list of schemas."""
    for key, value in node.items():
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            named = [(f"{path}.{key}.{name}", child) for name, child in value.items()]
        elif isinstance(value, dict):
            named = [(f"{path}.{key}", value)]
        elif isinstance(value, list):
            named = [(f"{path}.{key}[{n}]", child) for n, child in enumerate(value)]
        else:
            named = []
        yield from ((p, child) for p, child in named if isinstance(child, dict))


def _refs(node: Mapping[str, JsonValue]) -> set[str]:
    """The `$defs` names `node` refers to, at any depth outside `$defs` itself."""
    return {
        ref.removeprefix(_DEFS_PREFIX)
        for path, child in _subschemas({k: v for k, v in node.items() if k != _DEFS}, "$")
        if isinstance(ref := child.get("$ref"), str) and ref.startswith(_DEFS_PREFIX)
    }


def _ref_cycle(schema: Mapping[str, JsonValue]) -> str | None:
    """A definition that reaches itself through `$ref`s (or a `$ref` to the root, `#`), if any."""
    if any(child.get("$ref") == "#" for _, child in _subschemas(schema, "$")):
        return "#"
    defs = schema.get(_DEFS)
    graph = {name: _refs(d) for name, d in defs.items() if isinstance(d, dict)} if isinstance(defs, dict) else {}
    for start in graph:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            name = stack.pop()
            if name == start:
                return start
            if name not in seen:
                seen.add(name)
                stack.extend(graph.get(name, ()))
    return None
