"""The adapter collector: a platform API's JSON, read as the schema.org
nodes its adapter's shapes say it holds. Each entity carries its identity and item URLs as every structured collector's
do (`schema_org_map.entity`), so resolution merges it with the page's own statement of the item (`resolve.identity`).

An adapter capture's body is the JSON the platform's documented API serves for the page. Each object
a shape reaches is an entity (`adapter:<name>:<normalized path>`, its kind the shape's type, its parent the enclosing
node's entity, `via` the property the shape is under) and a node `schema_org_map` reads. Candidates come from
`field_candidates` with source kind `adapter`, so a field's path reads adapter JSON by the rules it reads JSON-LD and
microdata with: alternatives, identifier sub-properties, `.name` stand-ins, lists, and the sub-fields of a row-mapped
field. Each value is located at its own normalized path. Nothing here interprets a value: the field's
normalizer is the only filter (C7).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache
from html import escape
from typing import Final

from pydantic import JsonValue

from crawlerai.adapters.base import ALL, Adapter, AdapterMatch, Booleans, Members, PageScoped, Section, Shape
from crawlerai.collect.base import CollectResult, Entity
from crawlerai.collect.json_doc import ROOT, member, select
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import Typed, Value, canonical_urls, entity, field_candidates
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.content.links import links
from crawlerai.content.page import ParsedPage
from crawlerai.core.json_text import parse
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import network_json

# POSIX "Seconds Since the Epoch": 1970-01-01T00:00:00Z, which an API's millisecond timestamps count from.
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
# ISO 4217 minor units run from 0 (JPY) to 4 (CLF); a stated unit outside them is no currency's.
_MAX_PLACES: Final = 4


class AdapterCollector:
    """The collector of a capture `adapter` fetched, for a page the adapter detected as `match`: the capture's body, or
    the network body at `call`, the answer a page-scoped adapter joined to the page it serves (`ADAPTER_CALL`)."""

    def __init__(self, adapter: Adapter, match: AdapterMatch, vocabulary: Vocabulary, call: int | None = None) -> None:
        self._adapter = adapter
        self._match = match
        self._vocabulary = vocabulary
        self._call = call

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        name = self._adapter.name
        try:
            document = parse(page.html) if self._call is None else network_json(page.network[self._call])
        except ValueError as e:
            return CollectResult(entities=(), candidates=(), diagnostics=(f"adapter:{name}: not JSON ({e})",))
        shapes = self._adapter.shapes(self._match, document)
        read = read_shapes(name, shapes, document, self._rows_schema(schema), ctx, self._vocabulary)
        if self._call is None or not isinstance(self._adapter, PageScoped):
            return read
        # A page-scoped answer's rows are the page's own items: each also goes by the page's links to it, so it meets
        # the page's block of the item (`PageScoped.row_links`).
        shown = links(page, ctx.page_url or "")
        rows = tuple(_with_links(e, self._adapter, shown, ctx) for e in read.entities)
        return read.model_copy(update={"entities": rows})

    def _rows_schema(self, schema: SchemaDef) -> SchemaDef:
        """A listing's page-scoped fields describe the page, not a row: the API's rows hold none."""
        if self._match.page_kind == "detail":
            return schema
        rows = {name: spec for name, spec in schema.fields.items() if spec.scope == "row"}
        return schema.model_copy(update={"fields": rows})


def _with_links(row: Entity, adapter: PageScoped, shown: Sequence[str], ctx: Context) -> Entity:
    found = (link for url in row.item_urls for link in adapter.row_links(url, shown))
    return row.model_copy(update={"urls": tuple(dict.fromkeys((*row.urls, *canonical_urls(found, ctx))))})


def read_shapes(
    name: str, shapes: Sequence[Shape], document: JsonValue, schema: SchemaDef, ctx: Context, vocabulary: Vocabulary
) -> CollectResult:
    """The entities and `adapter` candidates of the nodes `shapes` reach in the platform answer `document`, located
    under `name` (module docstring)."""
    nodes: list[_Node] = []
    for shape in shapes:
        nodes.extend(_reach(name, shape, document, ROOT, parent=None, via=None))
    typed = [Typed(n.id, (n.shape.type,), n) for n in nodes]
    entities = tuple(entity(t, ctx, vocabulary, parent=n.parent, via=n.via) for t, n in zip(typed, nodes, strict=True))
    diagnostics: list[str] = []
    candidates = field_candidates(
        typed, schema, ctx, vocabulary=vocabulary, source_kind="adapter", diagnostics=diagnostics
    )
    # A value of a property the platform fills from its own record (`Shape.fallbacks`) is a fallback, at its locator.
    records = {v.locator for n in nodes for prop in n.shape.fallbacks for v in n.values(prop)}
    marked = (c.model_copy(update={"fallback": True}) if c.locator in records else c for c in candidates)
    return CollectResult(entities=entities, candidates=tuple(marked), diagnostics=tuple(diagnostics))


@dataclass(frozen=True, slots=True)
class _Node:
    """A JSON object (or array) of the document as the node `shape` describes, at the normalized path `path`."""

    adapter: str
    shape: Shape
    data: JsonValue
    path: str
    parent: str | None
    via: str | None

    @property
    def id(self) -> str:
        return f"adapter:{self.adapter}:{self.path}{_segments(self.shape.anchor)}"

    @property
    def node_id(self) -> str | None:
        return None  # an API object has no IRI

    def values(self, prop: str) -> Sequence[Value]:
        if (sections := self.shape.sections.get(prop)) is not None:
            return self._joined(sections)
        if (members := self.shape.properties.get(prop)) is not None:
            prefix = self.shape.prefixes.get(prop, "")
            places = self._places(prop)
            meant = self.shape.booleans.get(prop)
            values = [
                value
                for at in (members, *self.shape.also.get(prop, ()))
                for value in self._read(at, prefix, places, meant)
            ]
            return _timestamps(values) if prop in self.shape.epoch_ms else values
        return [
            Value(node.as_object(), self._locator(node.path), node)
            for shape in self.shape.nodes.get(prop, ())
            for node in _reach(self.adapter, shape, self.data, self.path, parent=self.id, via=prop, nested=False)
        ]

    def as_object(self) -> JsonValue:
        """The node as the object structured data states it: a node whose shape maps properties or nodes is an object
        of those properties and its nodes' (`MonetaryAmount` with `currency`, `minValue`, `maxValue`), the way a JSON-LD
        node holds them, so a field reading the whole node reads schema.org names; any other node is the API's own
        object."""
        if not (self.shape.properties or self.shape.sections or self.shape.nodes):
            return self.data
        names = (*self.shape.properties, *self.shape.sections, *self.shape.nodes)
        found = {name: _one([v.raw for v in self.values(name)]) for name in names}
        return {name: raw for name, raw in found.items() if raw is not None}

    def _read(
        self, members: Members, prefix: str, places: int | None = None, meant: Booleans | None = None
    ) -> list[Value]:
        # RFC 8259 `null`: the API states no value.
        found = [(at, raw) for at, raw in _select(members, self.data, self.path) if raw is not None]
        if places is not None:
            found = [(at, scaled) for at, raw in found if (scaled := _in_major_units(raw, places)) is not None]
        if meant is not None:
            found = [(at, value) for at, raw in found if (value := _meant(raw, meant)) is not None]
        return [Value(_prefixed(prefix, raw), self._locator(at)) for at, raw in found]

    def _joined(self, sections: Sequence[Section]) -> list[Value]:
        """The one HTML text of a property's parts (`Section`), located at its first part's body; none without a
        part."""
        parts: list[tuple[str, str]] = []
        for section in sections:
            for at, found in _select(section.at, self.data, self.path):
                body = _string(section.body, found, at)
                heading = _string(section.heading, found, at) if section.heading else None
                if body is not None:
                    titled = f"<h2>{escape(heading[1], quote=False)}</h2>" if heading is not None else ""
                    parts.append((body[0], titled + body[1]))
        if not parts:
            return []
        return [Value("\n".join(text for _, text in parts), self._locator(parts[0][0]))]

    def _places(self, prop: str) -> int | None:
        """The decimal places of the minor unit the API states `prop` in (`Shape.minor_units`), or None: no scaling.
        Places the node's object does not state as one integer from 0 to 4 (ISO 4217's minor units) scale nothing,
        and the property's values are then dropped (-1)."""
        unit = self.shape.minor_units.get(prop)
        if unit is None or isinstance(unit, int):
            return unit
        stated = [raw for _, raw in _select(unit, self.data, self.path)]
        one = stated[0] if len(stated) == 1 else None
        return one if isinstance(one, int) and not isinstance(one, bool) and 0 <= one <= _MAX_PLACES else -1

    def _locator(self, path: str) -> str:
        return format_locator("adapter", self.adapter, path)


def _timestamps(values: Sequence[Value]) -> list[Value]:
    """The values that are an integer count of milliseconds since the Unix epoch (`Shape.epoch_ms`), each as the
    RFC 3339 date-time in UTC it names (`2026-05-21T18:11:00.345Z`); any other value, or one past the dates a
    date-time holds, is dropped."""
    return [replace(value, raw=stamp) for value in values if (stamp := _timestamp(value.raw)) is not None]


def _timestamp(raw: JsonValue) -> str | None:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    try:
        moment = _EPOCH + timedelta(milliseconds=raw)
    except OverflowError:
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _meant(raw: JsonValue, meant: Booleans) -> JsonValue:
    """A JSON boolean as the value the documentation means by it (`Shape.booleans`), None where it means no one value;
    any other value as stated."""
    return meant[not raw] if isinstance(raw, bool) else raw


def _prefixed(prefix: str, raw: JsonValue) -> JsonValue:
    """`raw` after `prefix`: a string as written, an integer (an API's numeric id, RFC 8259 §6) in its decimal digits;
    any other value, or any value without a prefix, as it is."""
    if not prefix or isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return prefix + raw
    return prefix + str(raw) if isinstance(raw, int) else raw


def _in_major_units(raw: JsonValue, places: int) -> str | None:
    """An integer amount of a minor unit with `places` decimal places as the decimal amount of the major unit, in plain
    digits (`2900`, 2 places: `29.00`); None for any other value, or for places no unit has (-1)."""
    if places < 0 or isinstance(raw, bool):
        return None
    digits = str(raw) if isinstance(raw, int) else raw if isinstance(raw, str) and raw.isascii() else None
    if digits is None or not digits.isdigit():
        return None
    return format(Decimal(digits).scaleb(-places), "f")


def _string(members: Members, data: JsonValue, path: str) -> tuple[str, str] | None:
    """The first non-empty string at `members` from `data`, with its path; an empty string states nothing."""
    return next(((at, raw) for at, raw in _select(members, data, path) if isinstance(raw, str) and raw.strip()), None)


def _one(values: list[JsonValue]) -> JsonValue:
    """The value a JSON-LD object states for a property: the one value, or an array of several; None for none."""
    return values[0] if len(values) == 1 else (values or None)


def _reach(
    adapter: str,
    shape: Shape,
    data: JsonValue,
    path: str,
    *,
    parent: str | None,
    via: str | None,
    nested: bool = True,
) -> list[_Node]:
    """The nodes `shape` reaches from the object `data` at `path`, and, with `nested`, every node under them in
    document order. A node is an object, or an array a list's shape reaches; an item of another kind holds no node."""
    reached: list[_Node] = []
    for at, found in _select(shape.at, data, path):
        # An anchored node is there only when the member that names it is.
        if not isinstance(found, (dict, list)) or not _named(shape.anchor, found, at):
            continue
        node = _Node(adapter, shape, found, at, parent, via)
        reached.append(node)
        if nested:
            for prop, shapes in shape.nodes.items():
                for inner in shapes:
                    reached.extend(_reach(adapter, inner, found, at, parent=node.id, via=prop))
    return reached


def _named(anchor: Members, data: JsonValue, path: str) -> bool:
    return not anchor or any(value is not None for _, value in _select(anchor, data, path))


def _select(members: Members, data: JsonValue, path: str) -> list[tuple[str, JsonValue]]:
    return select(ROOT + _segments(members), data, path)


@cache  # shapes are module constants: a few distinct member tuples, looked up per node
def _segments(members: Members) -> str:
    """`members` as RFC 9535 segments: a name segment each, a wildcard segment for `ALL`, an index segment for an
    index."""
    return "".join(
        f"[{name}]" if isinstance(name, int) else "[*]" if name == ALL else member("", name) for name in members
    )
