"""The adapter collector (SPEC-05 §4.5, SPEC-15 §4.4, ARCHITECTURE §8.1): a platform API's JSON, read as the schema.org
nodes its adapter's shapes say it holds.

An adapter capture's body is the JSON the platform's documented API serves for the page (SPEC-02 §4.9). Each object a
shape reaches is an entity (`adapter:<name>:<normalized path>`, its kind the shape's type, its parent the enclosing
node's entity, `via` the property the shape is under) and a node `schema_org_map` reads. Candidates come from
`field_candidates` with source kind `adapter`, so a field's path reads adapter JSON by the rules it reads JSON-LD and
microdata with: alternatives, identifier sub-properties, `.name` stand-ins, lists, and the sub-fields of a row-mapped
field (SPEC-13 §4.2). Each value is located at its own normalized path. Nothing here interprets a value: the field's
normalizer is the only filter (C7).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache

from pydantic import JsonValue

from crawlerai.adapters.base import ALL, Adapter, AdapterMatch, Members, Shape
from crawlerai.collect.base import CollectResult, Entity
from crawlerai.collect.json_doc import ROOT, member, parse, select
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import Typed, Value, Vocabulary, entity_urls, field_candidates
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef


class AdapterCollector:
    """The collector of a capture `adapter` fetched, for a page the adapter detected as `match`."""

    def __init__(self, adapter: Adapter, match: AdapterMatch, vocabulary: Vocabulary) -> None:
        self._adapter = adapter
        self._match = match
        self._vocabulary = vocabulary

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        name = self._adapter.name
        try:
            document = parse(page.html)
        except ValueError as e:
            return CollectResult(entities=(), candidates=(), diagnostics=(f"adapter:{name}: not JSON ({e})",))
        nodes: list[_Node] = []
        for shape in self._adapter.shapes(self._match, document):
            nodes.extend(_reach(name, shape, document, ROOT, parent=None, via=None))
        entities = tuple(
            Entity(id=n.id, kind=n.shape.type, urls=entity_urls(n, ctx), parent=n.parent, via=n.via) for n in nodes
        )
        diagnostics: list[str] = []
        candidates = field_candidates(
            [Typed(n.id, (n.shape.type,), n) for n in nodes],
            self._rows_schema(schema),
            ctx,
            vocabulary=self._vocabulary,
            source_kind="adapter",
            diagnostics=diagnostics,
        )
        return CollectResult(entities=entities, candidates=tuple(candidates), diagnostics=tuple(diagnostics))

    def _rows_schema(self, schema: SchemaDef) -> SchemaDef:
        """A listing's page-scoped fields describe the page, not a row (SPEC-05 §4.7): the API's rows hold none."""
        if self._match.page_kind == "detail":
            return schema
        rows = {name: spec for name, spec in schema.fields.items() if spec.scope == "row"}
        return schema.model_copy(update={"fields": rows})


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
        if (members := self.shape.properties.get(prop)) is not None:
            prefix = self.shape.prefixes.get(prop, "")
            return [value for at in (members, *self.shape.also.get(prop, ())) for value in self._read(at, prefix)]
        return [
            Value(node.data, self._locator(node.path), node)
            for shape in self.shape.nodes.get(prop, ())
            for node in _reach(self.adapter, shape, self.data, self.path, parent=self.id, via=prop, nested=False)
        ]

    def _read(self, members: Members, prefix: str) -> list[Value]:
        # RFC 8259 `null`: the API states no value.
        return [
            Value(prefix + raw if prefix and isinstance(raw, str) else raw, self._locator(at))
            for at, raw in _select(members, self.data, self.path)
            if raw is not None
        ]

    def _locator(self, path: str) -> str:
        return format_locator("adapter", self.adapter, path)


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
    """`members` as RFC 9535 segments: a name segment each, a wildcard segment for `ALL`."""
    return "".join("[*]" if name == ALL else member("", name) for name in members)
