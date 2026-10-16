"""The JSON-LD collector (SPEC-05 §4.5, ARCHITECTURE §8.1): schema.org nodes in `application/ld+json` blocks.

Each block is parsed as JSON (an invalid block is skipped with a diagnostic, never repaired). Every JSON object in it
is a node; `@graph` and nesting need no special case, since the walk visits every object in document order. A node
whose `@type` is a schema.org type in the vocabulary is an entity. A node reference (an object holding only `@id`,
JSON-LD 1.1 §9.5) stands for the node defined with that `@id` anywhere on the page.

Entities and locators are addressed as `jsonld:<block>:<path>`, where the path is the RFC 9535 normalized path of
the object in its block's JSON (`$['@graph'][1]`).

Root nodes of one type that share an identity are one entity, the first of them (`_same_nodes`): the same `@id`
resolved against the document base (JSON-LD 1.1 node map generation merges node objects with one `@id`; RFC 3986
§5), or the same value of a schema.org identifier property (`identifier` and its sub-properties, such as `sku` and
`gtin13`, identify the item). The later nodes' values and their nested nodes become the first's, so resolution sees
one entity and applies its rules to all of them: agreeing values publish, Offers that disagree are a conflict.
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import urljoin, urlsplit

from pydantic import JsonValue

from crawlerai.collect.base import CollectResult, Entity, descends
from crawlerai.collect.json_doc import member, parse
from crawlerai.collect.schema_org_map import (
    NAMESPACES,
    Typed,
    Value,
    Vocabulary,
    field_candidates,
    item_urls,
    offer_urls,
    schema_term,
)
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# JSON-LD 1.1 §4.2: the keyword of a value object, which holds a scalar.
_VALUE: Final = "@value"

# The JSON-LD media type (JSON-LD 1.1, IANA considerations); HTML embeds JSON-LD in a script element of that type
# (JSON-LD 1.1 §7.3).
MEDIA_TYPE = "application/ld+json"
# A context naming schema.org by its namespace, with or without the trailing slash (schema.org's published form).
_CONTEXTS = frozenset(n.rstrip("/") for n in NAMESPACES)
_CONTEXT_KEY = "@context"  # JSON-LD 1.1 §3.1
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
        if _VALUE in written:  # a value object (JSON-LD 1.1 §4.2) holds a scalar
            scalar = written[_VALUE]
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
        for index, document in blocks(page, diagnostics):
            for found in self._walk(index, document):
                graph.add(found)
        entities = [found for found in graph.objects if found.types]
        parents, vias = _parents(entities, graph)
        typed = [Typed(found.id, found.types, _Node(found, graph)) for found in entities]
        own = {t.id: item_urls(t.node, ctx) for t in typed}
        roots = [found for found in entities if parents[found.id] is None]
        same = _same_nodes(roots, graph, self.vocabulary, own)
        diagnostics.extend(
            f"jsonld: {node} is the node {first} (same @id or identifier)" for node, first in same.items()
        )
        candidates = field_candidates(
            typed, schema, ctx, vocabulary=self.vocabulary, source_kind="jsonld", diagnostics=diagnostics
        )
        urls: dict[str, dict[str, None]] = {}
        for t in typed:
            # SPEC-05 §4.2: an entity's URLs are its own and its offers'; a merged node adds its members'.
            urls.setdefault(same.get(t.id, t.id), {}).update(dict.fromkeys((*own[t.id], *offer_urls(t.node, ctx))))
        return CollectResult(
            entities=tuple(
                Entity(
                    id=t.id,
                    kind=t.types[0],
                    urls=tuple(urls[t.id]),
                    parent=same.get(parent, parent) if (parent := parents[t.id]) is not None else None,
                    via=vias[t.id],
                )
                for t in typed
                if t.id not in same
            ),
            candidates=tuple(
                c.model_copy(update={"entity_id": same[c.entity_id]}) if c.entity_id in same else c for c in candidates
            ),
            diagnostics=tuple(diagnostics),
        )

    def nodes(self, page: ParsedPage) -> Iterator[tuple[str, tuple[str, ...], Mapping[str, JsonValue]]]:
        """The page's schema.org nodes in document order, each with its locator (`jsonld:<block>:<path>`) and its
        types, most specific first. Invalid blocks are skipped; `collect` reports them."""
        for index, document in blocks(page, []):
            for found in self._walk(index, document):
                if found.types:
                    yield found.id, found.types, found.data

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
            if _CONTEXT_KEY in value:
                in_schema = _in_schema(value[_CONTEXT_KEY], in_schema)
            found = _Object(value, block, path, in_schema, self._types(value.get("@type"), in_schema), enclosing, via)
            yield found
            inner = found.id if found.types else enclosing
            stack.extend(
                (child, member(path, key), in_schema, inner, _member_via(found, key, via))
                for key, child in reversed(value.items())
                if key != _CONTEXT_KEY
            )

    def _types(self, declared: JsonValue, in_schema: bool) -> tuple[str, ...]:
        names: list[str] = []
        for item in declared if isinstance(declared, list) else [declared]:
            if isinstance(item, str) and (name := schema_term(item) or (item if in_schema else None)) is not None:
                names.append(name)
        return self.vocabulary.specific_first(names)


def property_scalars(page: ParsedPage, prop: str) -> Iterator[JsonValue]:
    """The scalar values of the schema.org property `prop` on every JSON object of the page's blocks, typed or not,
    in document order: a bare term where schema.org is the vocabulary, a full IRI anywhere (JSON-LD 1.1 §4.1.2).
    Invalid blocks are skipped."""
    for _, document in blocks(page, []):
        for value, in_schema in _scoped_objects(document):
            for key in _keys(prop, in_schema=in_schema):
                yield from _scalars(value.get(key))


def _scoped_objects(document: JsonValue) -> Iterator[tuple[Mapping[str, JsonValue], bool]]:
    """Every object of `document` in document order, with whether schema.org is the vocabulary in its scope."""
    stack: list[tuple[JsonValue, bool]] = [(document, False)]
    while stack:
        value, in_schema = stack.pop()
        if isinstance(value, list):
            stack.extend((item, in_schema) for item in reversed(value))
        elif isinstance(value, dict):
            if _CONTEXT_KEY in value:
                in_schema = _in_schema(value[_CONTEXT_KEY], in_schema)
            yield value, in_schema
            stack.extend((child, in_schema) for key, child in reversed(value.items()) if key != _CONTEXT_KEY)


def _scalars(written: JsonValue) -> Iterator[JsonValue]:
    """The scalar values written for a property: each item of an array (§4.3.1), a value object's `@value` (§4.2)."""
    for item in written if isinstance(written, list) else [written]:
        scalar = item.get(_VALUE) if isinstance(item, dict) else item
        if scalar is not None and not isinstance(scalar, (list, dict)):
            yield scalar


def blocks(page: ParsedPage, diagnostics: list[str]) -> Iterator[tuple[int, JsonValue]]:
    """Each `application/ld+json` block's JSON with its index; an invalid block is skipped with a diagnostic."""
    for index, script in enumerate(s for s in page.scripts if s.type == MEDIA_TYPE):
        try:
            yield index, parse(script.text)
        except ValueError as e:
            diagnostics.append(f"jsonld:{index}: invalid JSON ({e})")


def _member_via(holder: _Object, key: str, via: str | None) -> str | None:
    """The property a member of `holder` is under: an entity's member is under the entity's property of that name (a
    full schema.org IRI anywhere, a bare term other than a keyword where schema.org is the vocabulary; JSON-LD 1.1
    §4.1.2); a member of a plain object is under the property the object is under."""
    return _term(holder, key) if holder.types else via


def _term(holder: _Object, key: str) -> str | None:
    """The schema.org property a member key names: a full schema.org IRI anywhere, a bare term other than a keyword
    where schema.org is the vocabulary (JSON-LD 1.1 §4.1.2)."""
    return schema_term(key) or (key if holder.in_schema and not key.startswith("@") else None)


def _same_nodes(
    roots: Sequence[_Object], graph: _Graph, vocabulary: Vocabulary, urls: Mapping[str, tuple[str, ...]]
) -> dict[str, str]:
    """Each root node that shares an identity (`_identity`) with an earlier root node of the same most specific type,
    mapped to the first node of its group, in document order. One `@id` is one node (JSON-LD). One identifier value
    joins two groups only when their own URLs (`item_urls`) do not name two different items (schema.org `url`, "URL
    of the item"): a listing's items may repeat an identifier across distinct items. An Offer's URL may name a
    variant's page, so it does not count."""
    groups = _Groups([frozenset(urls[found.id]) for found in roots])
    first_with: dict[tuple[str, str, str], int] = {}
    for i, found in enumerate(roots):
        for prop, value in _identity(found, graph, vocabulary):
            first = first_with.setdefault((found.types[0], prop, value), i)
            groups.join(first, i, by_id=prop == "@id")
    return {roots[i].id: roots[groups.find(i)].id for i in range(len(roots)) if groups.find(i) != i}


@dataclass
class _Groups:
    """Disjoint sets of root nodes, each named by its first member, with the URLs its members state."""

    urls: list[frozenset[str]]
    parent: list[int] = field(init=False)

    def __post_init__(self) -> None:
        self.parent = list(range(len(self.urls)))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, i: int, j: int, *, by_id: bool) -> None:
        a, b = sorted((self.find(i), self.find(j)))
        if a == b or not (by_id or self._compatible(a, b)):
            return
        self.parent[b] = a
        self.urls[a] |= self.urls[b]

    def _compatible(self, a: int, b: int) -> bool:
        return not (self.urls[a] and self.urls[b]) or bool(self.urls[a] & self.urls[b])


def _identity(found: _Object, graph: _Graph, vocabulary: Vocabulary) -> Iterator[tuple[str, str]]:
    """What identifies a node: its `@id` resolved against the base (a blank node is scoped to its block, JSON-LD 1.1
    §4.5.1, so it identifies nothing across blocks), and each scalar value of its identifier properties."""
    node_id = graph.resolve_id(found.data.get("@id"))
    if node_id is not None and not node_id.startswith("_:"):
        yield "@id", node_id
    for key, written in found.data.items():
        if (term := _term(found, key)) in vocabulary.identifiers:
            for scalar in _scalars(written):
                if text := str(scalar).strip():
                    yield term, text


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
