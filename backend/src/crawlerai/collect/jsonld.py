"""The JSON-LD collector (SPEC-05 §4.5, ARCHITECTURE §8.1): schema.org nodes in `application/ld+json` blocks.

Each block is parsed as JSON (an invalid block is skipped with a diagnostic, never repaired). Every JSON object in it
is a node; `@graph` and nesting need no special case, since the walk visits every object in document order. A node
whose `@type` is a schema.org type in the vocabulary is an entity. A node reference (an object holding only `@id`,
JSON-LD 1.1 §9.5) stands for the node defined with that `@id` anywhere on the page.

Entities and locators are addressed as `jsonld:<block>:<path>`, where the path is the RFC 9535 normalized path of
the object in its block's JSON (`$['@graph'][1]`).
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.collect.base import CollectResult, Entity, descends
from crawlerai.collect.json_doc import member, parse
from crawlerai.collect.schema_org_map import (
    NAMESPACES,
    Typed,
    Value,
    Vocabulary,
    entity_urls,
    field_candidates,
    schema_term,
)
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# The JSON-LD media type (JSON-LD 1.1, IANA considerations); HTML embeds JSON-LD in a script element of that type
# (JSON-LD 1.1 §7.3).
_MEDIA_TYPE = "application/ld+json"
# A context naming schema.org by its namespace, with or without the trailing slash (schema.org's published form).
_CONTEXTS = frozenset(n.rstrip("/") for n in NAMESPACES)
# A reference to a node: the entity it is nested in, and that entity's property it is under.
_Reference = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class _Object:
    """A JSON object in a block: where it is, whether schema.org is the vocabulary in its scope, its schema.org types,
    the nearest entity it is nested in, and the schema.org property of that entity it is nested under."""

    data: Mapping[str, JsonValue]
    block: int
    path: str
    in_schema: bool
    types: tuple[str, ...]
    enclosing: str | None
    via: str | None

    @property
    def id(self) -> str:
        return f"jsonld:{self.block}:{self.path}"


@dataclass
class _Graph:
    """Every object of the page's blocks, and the `@id` index that node references resolve through."""

    base: str | None
    objects: list[_Object] = field(default_factory=list)
    at: dict[str, _Object] = field(default_factory=dict)  # by locator
    by_id: dict[str, _Object] = field(default_factory=dict)  # node definitions by resolved @id; the first one wins
    # @id -> (entity id, property) of each reference nested in an entity
    referrers: defaultdict[str, list[_Reference]] = field(default_factory=lambda: defaultdict(list))

    def add(self, found: _Object) -> None:
        self.objects.append(found)
        self.at[found.id] = found
        node_id = self.resolve_id(found.data.get("@id"))
        if node_id is None:
            return
        if found.data.keys() == {"@id"}:
            if found.enclosing is not None:
                self.referrers[node_id].append((found.enclosing, found.via))
        else:
            self.by_id.setdefault(node_id, found)

    def resolve_id(self, node_id: JsonValue) -> str | None:
        # JSON-LD 1.1 §4.1.2: `@id` is an IRI reference, resolved against the document base; `_:` names a blank node.
        if not isinstance(node_id, str):
            return None
        if node_id.startswith("_:"):
            return node_id
        try:
            resolved = node_id if self.base is None else urljoin(self.base, node_id)
            urlsplit(resolved)
        except ValueError:  # not an IRI reference (an unclosed IPv6 bracket), so it names no node
            return None
        return resolved


@dataclass(frozen=True, slots=True)
class _Node:
    """A JSON-LD node as `schema_org_map` reads it."""

    found: _Object
    graph: _Graph

    @property
    def node_id(self) -> str | None:
        return self.graph.resolve_id(self.found.data.get("@id"))

    def values(self, prop: str) -> Sequence[Value]:
        values: list[Value] = []
        for key in _keys(prop, in_schema=self.found.in_schema):
            if key not in self.found.data:
                continue
            path, written = member(self.found.path, key), self.found.data[key]
            # JSON-LD 1.1 §4.3.1: an array holds several values of the property.
            items = [(f"{path}[{i}]", item) for i, item in enumerate(written)] if isinstance(written, list) else []
            for item_path, item in items or [(path, written)]:
                if (value := self._value(item, item_path)) is not None:
                    values.append(value)
        return values

    def _value(self, written: JsonValue, path: str) -> Value | None:
        """One written value: a scalar, a value object, a node, or a reference to a node defined on the page. `null`
        is no value (JSON-LD 1.1 §4.1.4), and an array inside the array of values is not one either."""
        locator = f"jsonld:{self.found.block}:{path}"
        if isinstance(written, list) or written is None:
            return None
        if not isinstance(written, dict):
            return Value(written, locator)
        if "@value" in written:  # a value object (JSON-LD 1.1 §4.2) holds a scalar
            scalar = written["@value"]
            return None if scalar is None or isinstance(scalar, (list, dict)) else Value(scalar, locator)
        target: _Object | None = self.graph.at[locator]
        if written.keys() == {"@id"}:
            # A reference to a node the page does not define holds no value here.
            target = self.graph.by_id.get(self.graph.resolve_id(written["@id"]) or "")
        return None if target is None else Value(dict(target.data), target.id, _Node(target, self.graph))


def _keys(prop: str, *, in_schema: bool) -> list[str]:
    # A term is a schema.org property only where schema.org is the vocabulary (JSON-LD 1.1 §4.1.2); a full IRI is one
    # anywhere.
    return ([prop] if in_schema else []) + [namespace + prop for namespace in NAMESPACES]


def _in_schema(context: JsonValue, inherited: bool) -> bool:
    """Whether schema.org is the vocabulary after `context` (JSON-LD 1.1 §4.1: a `null` context resets it; an array is
    processed in order; an object without `@vocab` keeps the vocabulary in scope). A remote context other than
    schema.org's is not fetched, so its terms are not read as schema.org terms."""
    for item in context if isinstance(context, list) else [context]:
        inherited = _after(item, inherited)
    return inherited


def _after(context: JsonValue, inherited: bool) -> bool:
    if isinstance(context, str):
        return context.rstrip("/") in _CONTEXTS
    if isinstance(context, dict):
        return context["@vocab"] in NAMESPACES if "@vocab" in context else inherited
    return False


@dataclass(frozen=True, slots=True)
class JsonLdCollector:
    vocabulary: Vocabulary

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        graph = _Graph(ctx.base_url)
        diagnostics: list[str] = []
        blocks = [script for script in page.scripts if script.type == _MEDIA_TYPE]
        for index, script in enumerate(blocks):
            try:
                document = parse(script.text)
            except ValueError as e:
                diagnostics.append(f"jsonld:{index}: invalid JSON ({e})")
                continue
            for found in self._walk(index, document):
                graph.add(found)
        entities = [found for found in graph.objects if found.types]
        parents, vias = _parents(entities, graph)
        typed = [Typed(found.id, found.types, _Node(found, graph)) for found in entities]
        candidates = field_candidates(
            typed, schema, ctx, vocabulary=self.vocabulary, source_kind="jsonld", diagnostics=diagnostics
        )
        return CollectResult(
            entities=tuple(
                Entity(id=t.id, kind=t.types[0], urls=entity_urls(t.node, ctx), parent=parents[t.id], via=vias[t.id])
                for t in typed
            ),
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
        )

    def _walk(self, block: int, document: JsonValue) -> Iterator[_Object]:
        """Every object of `document` in document order. Iterative, so that nesting depth is bounded by what the JSON
        parser accepts rather than by the call stack."""
        stack: list[tuple[JsonValue, str, bool, str | None, str | None]] = [(document, "$", False, None, None)]
        while stack:
            value, path, in_schema, enclosing, via = stack.pop()
            if isinstance(value, list):
                items = reversed(list(enumerate(value)))
                stack.extend((item, f"{path}[{i}]", in_schema, enclosing, via) for i, item in items)
                continue
            if not isinstance(value, dict):
                continue
            if "@context" in value:
                in_schema = _in_schema(value["@context"], in_schema)
            found = _Object(value, block, path, in_schema, self._types(value.get("@type"), in_schema), enclosing, via)
            yield found
            inner = found.id if found.types else enclosing
            stack.extend(
                (child, member(path, key), in_schema, inner, _member_via(found, key, via))
                for key, child in reversed(value.items())
                if key != "@context"
            )

    def _types(self, declared: JsonValue, in_schema: bool) -> tuple[str, ...]:
        names: list[str] = []
        for item in declared if isinstance(declared, list) else [declared]:
            if isinstance(item, str) and (name := schema_term(item) or (item if in_schema else None)) is not None:
                names.append(name)
        return self.vocabulary.specific_first(names)


def _member_via(holder: _Object, key: str, via: str | None) -> str | None:
    """The property a member of `holder` is under: an entity's member is under the entity's property of that name (a
    full schema.org IRI anywhere, a bare term other than a keyword where schema.org is the vocabulary; JSON-LD 1.1
    §4.1.2); a member of a plain object is under the property the object is under."""
    if not holder.types:
        return via
    return schema_term(key) or (key if holder.in_schema and not key.startswith("@") else None)


def _parents(entities: Sequence[_Object], graph: _Graph) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Each entity's parent, and the parent's property it is under: the entity it is nested in; else, for a node
    defined on its own, the one entity that references it, unless that would make a cycle. A node two entities
    reference has no parent; a node its one referrer references under two properties is under neither."""
    parents: dict[str, str | None] = {found.id: found.enclosing for found in entities}
    vias: dict[str, str | None] = {found.id: found.via for found in entities}
    for found in entities:
        node_id = graph.resolve_id(found.data.get("@id"))
        if found.enclosing is None and node_id is not None:
            referenced = _referrer(found.id, graph.referrers.get(node_id, []), parents)
            if referenced is not None:
                parents[found.id], vias[found.id] = referenced
    return parents, vias


def _referrer(entity: str, references: Sequence[_Reference], parents: Mapping[str, str | None]) -> _Reference | None:
    """The one entity other than `entity` itself that references it, unless that would make a cycle, with the
    property it references it under."""
    references = [r for r in references if r[0] != entity]
    referrers = {referrer for referrer, _ in references}
    if len(referrers) != 1:
        return None
    (referrer,) = referrers
    if descends(referrer, entity, parents):
        return None
    properties = {prop for _, prop in references}
    return (referrer, properties.pop() if len(properties) == 1 else None)
