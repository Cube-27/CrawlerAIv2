"""The schema document as role S writes it (llm spec): a form inside every provider's structured-output subset.

`SchemaDocument`'s own JSON Schema can't be a provider's output schema: its field specs nest recursively
(`FieldSpec -> FieldSpec`), its fields are an object keyed by name (`patternProperties`, so not a closed object), and
its optional parameters are nullable unions (`tests.support.schema_subset`). The wire form says the same without any
of them:
- fields are a list of entries, each with its `name`;
- every parameter is present: `""` stands for a parameter the field does not have, and `item`, `fields` and `key`
  are lists, empty when the field has none (`item` holds at most one entry);
- nesting is unrolled to `MAX_DEPTH` levels, the deepest level having no `item` or `fields`.

`from_wire` reads a reply back as a document for `SchemaDocument` to validate; `to_wire` writes a document as JSON,
such as a preset shown as an example, in the same form. A list item's entry has the name `""`.
"""

from collections.abc import Mapping, Sequence
from typing import Final, cast, get_args

from pydantic import JsonValue

from crawlerai.db.models import PageKind
from crawlerai.llm.client import closed_object
from crawlerai.schemas.types import MAX_DEPTH, FieldSpec, FieldType, IdentifierScheme, Scope

_NONE: Final = ""
# The field-spec parameters that are a string or absent, written as `""` when absent.
_OPTIONAL_STRINGS: Final = ("description", "schema_org", "vocab", "scheme")


def wire_schema() -> dict[str, JsonValue]:
    """The output schema of a document without its name and version, in the wire form."""
    return closed_object(
        {
            "page_kind": _enum(get_args(PageKind)),
            "required_groups": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            "fields": {"type": "array", "items": {"$ref": f"#/$defs/{_level(1)}"}},
        }
    ) | {"$defs": {_level(depth): _entry_schema(depth) for depth in range(1, MAX_DEPTH + 1)}}


def _level(depth: int) -> str:
    return f"field_{depth}"


def _entry_schema(depth: int) -> dict[str, JsonValue]:
    properties: dict[str, JsonValue] = {
        "name": {"type": "string"},
        "type": _enum([t.value for t in FieldType]),
        "description": {"type": "string"},
        "required": {"type": "boolean"},
        "scope": _enum(get_args(Scope)),
        "schema_org": {"type": "string"},
        "vocab": {"type": "string"},
        "scheme": _enum([_NONE, *get_args(IdentifierScheme)]),
        "key": {"type": "array", "items": {"type": "string"}},
    }
    if depth < MAX_DEPTH:
        inner: JsonValue = {"type": "array", "items": {"$ref": f"#/$defs/{_level(depth + 1)}"}}
        properties |= {"item": inner, "fields": inner}
    return closed_object(properties)


def _enum(values: Sequence[str]) -> dict[str, JsonValue]:
    return {"type": "string", "enum": list[JsonValue](values)}


def from_wire(data: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The document a wire reply stands for, for `SchemaDocument` to validate. Raises `ValueError` for what the
    document form can't hold: a field name given twice, or a list with more than one item."""
    return {
        "page_kind": data["page_kind"],
        "required_groups": data["required_groups"],
        "fields": _fields(cast(list[JsonValue], data["fields"]), "fields"),
    }


def _fields(entries: list[JsonValue], path: str) -> dict[str, JsonValue]:
    fields: dict[str, JsonValue] = {}
    for raw in entries:
        entry = cast(dict[str, JsonValue], raw)
        name = cast(str, entry["name"])
        if name in fields:
            raise ValueError(f"{path}: field {name!r} given twice")
        fields[name] = _spec(entry, f"{path}.{name}")
    return fields


def _spec(entry: Mapping[str, JsonValue], path: str) -> dict[str, JsonValue]:
    spec: dict[str, JsonValue] = {"type": entry["type"], "required": entry["required"], "scope": entry["scope"]}
    spec |= {key: entry[key] for key in _OPTIONAL_STRINGS if entry[key] != _NONE}
    # A reply written before `key` existed has none (variants spec).
    if row_key := entry.get("key"):
        spec["key"] = row_key
    items = cast(list[JsonValue], entry.get("item", []))
    if len(items) > 1:
        raise ValueError(f"{path}: a list has one item, not {len(items)}")
    if items:
        spec["item"] = _spec(cast(dict[str, JsonValue], items[0]), f"{path}.item")
    if fields := cast(list[JsonValue], entry.get("fields", [])):
        spec["fields"] = _fields(fields, path)
    return spec


def to_wire(document: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """A document as JSON, without its name and version, in the wire form; a parameter it leaves out takes the
    `FieldSpec` default."""
    fields = cast(dict[str, JsonValue], document["fields"])
    return {
        "page_kind": document["page_kind"],
        "required_groups": document.get("required_groups", []),
        "fields": [_entry(name, spec, 1) for name, spec in fields.items()],
    }


def _entry(name: str, raw: JsonValue, depth: int) -> dict[str, JsonValue]:
    spec = cast(dict[str, JsonValue], raw)
    entry: dict[str, JsonValue] = {"name": name, "type": spec["type"]}
    entry |= {key: spec.get(key, FieldSpec.model_fields[key].default) for key in ("required", "scope")}
    entry |= {key: spec.get(key) or _NONE for key in _OPTIONAL_STRINGS}
    entry["key"] = spec.get("key") or []
    if depth < MAX_DEPTH:
        item = spec.get("item")
        entry["item"] = [] if item is None else [_entry(_NONE, item, depth + 1)]
        sub = cast(dict[str, JsonValue], spec.get("fields") or {})
        entry["fields"] = [_entry(n, s, depth + 1) for n, s in sub.items()]
    return entry
