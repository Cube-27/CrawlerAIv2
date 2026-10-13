"""The JSON-LD collector (SPEC-05 §4.5, ARCHITECTURE §8.1): schema.org nodes in `application/ld+json` blocks.

Each block is parsed as JSON (an invalid block is skipped with a diagnostic, never repaired). Every JSON object in it
is a node; `@graph` and nesting need no special case, since the walk visits every object in document order. A node
whose `@type` is a schema.org type in the vocabulary is an entity. A node reference (an object holding only `@id`,
JSON-LD 1.1 §9.5) stands for the node defined with that `@id` anywhere on the page.

Entities and locators are addressed as `jsonld:<block>:<path>`, where the path is the RFC 9535 normalized path of
the object in its block's JSON (`$['@graph'][1]`).
"""

import json
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from pydantic import JsonValue, ValidationError

from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.schema_org_map import Value, Vocabulary, parse_path, select
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# The JSON-LD media type (JSON-LD 1.1, IANA considerations); HTML embeds JSON-LD in a script element of that type
# (JSON-LD 1.1 §7.3).
_MEDIA_TYPE = "application/ld+json"
# schema.org namespaces: https is current, http the earlier one; the vocabulary treats both as the same terms.
_NAMESPACES = ("https://schema.org/", "http://schema.org/")
# A context naming schema.org by its namespace, with or without the trailing slash (schema.org's published form).
_CONTEXTS = frozenset(n.rstrip("/") for n in _NAMESPACES)
_URL = FieldSpec(type=FieldType.URL)


@dataclass(frozen=True, slots=True)
class _Object:
    """A JSON object in a block: where it is, whether schema.org is the vocabulary in its scope, its schema.org types,
    and the nearest entity it is nested in."""

    data: Mapping[str, JsonValue]
    block: int
    path: str
    in_schema: bool
    types: tuple[str, ...]
    enclosing: str | None

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
    referrers: defaultdict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # @id -> entity ids

    def add(self, found: _Object) -> None:
        self.objects.append(found)
        self.at[found.id] = found
        node_id = self.resolve_id(found.data.get("@id"))
        if node_id is None:
            return
        if found.data.keys() == {"@id"}:
            if found.enclosing is not None:
                self.referrers[node_id].append(found.enclosing)
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

    def values(self, prop: str) -> Sequence[Value]:
        values: list[Value] = []
        for key in _keys(prop, in_schema=self.found.in_schema):
            if key not in self.found.data:
                continue
            path, written = _member(self.found.path, key), self.found.data[key]
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
    return ([prop] if in_schema else []) + [namespace + prop for namespace in _NAMESPACES]


# RFC 9535 §2.7: a normalized path writes a member name in single quotes, escaping `'`, `\` and control characters.
_ESCAPES = {"'": "\\'", "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _member(path: str, name: str) -> str:
    escaped = "".join(_ESCAPES.get(c) or (f"\\u{ord(c):04x}" if c < " " else c) for c in name)
    return f"{path}['{escaped}']"


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
        return context["@vocab"] in _NAMESPACES if "@vocab" in context else inherited
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
                document = _parse(script.text)
            except ValueError as e:
                diagnostics.append(f"jsonld:{index}: invalid JSON ({e})")
                continue
            for found in self._walk(index, document):
                graph.add(found)
        entities = [found for found in graph.objects if found.types]
        parents = _parents(entities, graph)
        return CollectResult(
            entities=tuple(self._entity(found, parents, graph, ctx) for found in entities),
            candidates=tuple(self._candidates(entities, graph, schema, ctx, diagnostics)),
            diagnostics=tuple(diagnostics),
        )

    def _walk(self, block: int, document: JsonValue) -> Iterator[_Object]:
        """Every object of `document` in document order. Iterative, so that nesting depth is bounded by what the JSON
        parser accepts rather than by the call stack."""
        stack: list[tuple[JsonValue, str, bool, str | None]] = [(document, "$", False, None)]
        while stack:
            value, path, in_schema, enclosing = stack.pop()
            if isinstance(value, list):
                items = reversed(list(enumerate(value)))
                stack.extend((item, f"{path}[{i}]", in_schema, enclosing) for i, item in items)
                continue
            if not isinstance(value, dict):
                continue
            if "@context" in value:
                in_schema = _in_schema(value["@context"], in_schema)
            found = _Object(value, block, path, in_schema, self._types(value.get("@type"), in_schema), enclosing)
            yield found
            inner = found.id if found.types else enclosing
            stack.extend(
                (child, _member(path, key), in_schema, inner)
                for key, child in reversed(value.items())
                if key != "@context"
            )

    def _types(self, declared: JsonValue, in_schema: bool) -> tuple[str, ...]:
        """The schema.org types `declared` names, most specific first: a type that another listed type is a subtype of
        follows it."""
        names: list[str] = []
        for item in declared if isinstance(declared, list) else [declared]:
            if not isinstance(item, str):
                continue
            name = next((item.removeprefix(n) for n in _NAMESPACES if item.startswith(n)), None)
            if name is None and in_schema:
                name = item
            if name is not None and name in self.vocabulary and name not in names:
                names.append(name)
        return tuple(sorted(names, key=lambda t: any(o != t and self.vocabulary.is_a(o, t) for o in names)))

    def _entity(self, found: _Object, parents: Mapping[str, str | None], graph: _Graph, ctx: Context) -> Entity:
        return Entity(id=found.id, kind=found.types[0], urls=_urls(_Node(found, graph), ctx), parent=parents[found.id])

    def _candidates(
        self, entities: Sequence[_Object], graph: _Graph, schema: SchemaDef, ctx: Context, diagnostics: list[str]
    ) -> Iterator[Candidate]:
        """A candidate per value each field's path reaches on each entity of its type. A value the candidate model
        refuses (nested deeper than its validator recurses) is skipped with a diagnostic: a collector never raises on
        page content (§4.5)."""
        for name, spec in schema.fields.items():
            if spec.schema_org is None:
                continue
            path = parse_path(spec.schema_org)
            for found in entities:
                if not any(self.vocabulary.is_a(t, path.root) for t in found.types):
                    continue
                for selected in select(_Node(found, graph), path, as_list=spec.type is FieldType.LIST):
                    try:
                        yield Candidate(
                            field=name,
                            entity_id=found.id,
                            source_kind="jsonld",
                            raw=selected.raw,
                            normalized=normalize(selected.raw, spec, ctx),
                            locator=selected.locator,
                            independent=True,
                        )
                    except ValidationError as e:
                        reason = e.errors()[0]["type"]
                        block = selected.locator.split(":", 2)[1]
                        diagnostics.append(f"jsonld:{block}: value at {selected.locator} skipped ({reason})")


def _parse(text: str) -> JsonValue:
    try:
        parsed: JsonValue = json.loads(text, parse_constant=_not_json)
    except RecursionError:
        raise ValueError("nested too deeply") from None
    return parsed


def _not_json(constant: str) -> JsonValue:
    # RFC 8259 §6: `NaN` and `Infinity` are not JSON numbers, though Python's parser reads them.
    raise ValueError(f"{constant} is not JSON")


def _parents(entities: Sequence[_Object], graph: _Graph) -> dict[str, str | None]:
    """Each entity's parent: the entity it is nested in; else, for a node defined on its own, the one entity that
    references it, unless that would make a cycle. A node two entities reference has no parent."""
    parents: dict[str, str | None] = {found.id: found.enclosing for found in entities}
    for found in entities:
        node_id = graph.resolve_id(found.data.get("@id"))
        if found.enclosing is not None or node_id is None:
            continue
        referrers = set(graph.referrers.get(node_id, ())) - {found.id}
        if len(referrers) == 1 and not _descends(next(iter(referrers)), found.id, parents):
            parents[found.id] = next(iter(referrers))
    return parents


def _descends(entity: str | None, ancestor: str, parents: Mapping[str, str | None]) -> bool:
    while entity is not None:
        if entity == ancestor:
            return True
        entity = parents[entity]
    return False


def _urls(node: _Node, ctx: Context) -> tuple[str, ...]:
    """The canonical URLs that name the page an entity is on (SPEC-05 §4.2): its `url` and `@id`, its
    `mainEntityOfPage`, and its offers' `url`."""
    written: list[JsonValue] = _page_names(node)
    for value in node.values("mainEntityOfPage"):
        written.extend(_page_names(value.node) if isinstance(value.node, _Node) else [value.raw])
    for value in node.values("offers"):
        if value.node is not None:
            written.extend(v.raw for v in value.node.values("url"))
    urls: list[str] = []
    for raw in written:
        result = normalize(raw, _URL, ctx)
        if isinstance(result, Ok) and isinstance(result.value, str) and result.value not in urls:
            urls.append(result.value)
    return tuple(urls)


def _page_names(node: _Node) -> list[JsonValue]:
    names: list[JsonValue] = [v.raw for v in node.values("url")]
    node_id = node.graph.resolve_id(node.found.data.get("@id"))
    # RFC 3986 §3.5: an `@id` with a fragment names a part of a document, not the page itself.
    if node_id is not None and not urlsplit(node_id).fragment:
        names.append(node_id)
    return names
