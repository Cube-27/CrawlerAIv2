"""The schema.org map (SPEC-05 §4.1, §4.5), shared by the structured-data collectors (JSON-LD, microdata): the type
hierarchy from the pinned schema.org vocabulary file, and a schema field's `schema_org` path read against a node.

A path `T.p[.q][+r]` (SPEC-04 §4.2) applies to every entity of type `T` or a subtype of it (`rdfs:subClassOf`). It
follows `p`, then `q`, through the nodes the values name; `+r` joins the last node's `r` to the value as one object.
A path of alternatives `A|B` (SPEC-13 §4.1) reaches what each alternative reaches. A row-mapped field's sub-fields are
read as fields of their own, named `<field>.<sub-field>` (SPEC-13 §4.2).
"""

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import NamedTuple, Protocol
from urllib.parse import urlsplit

from pydantic import JsonValue, ValidationError

from crawlerai.collect.base import Candidate
from crawlerai.core.engine_version import engine_data_dir
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# The pinned schema.org release in `backend/data/manifest.json` (SPEC-04 §4.6, D-0018).
VOCABULARY_FILE = Path("schemaorg") / "schemaorg-all-https.jsonld"

# The vocabulary file's compact IRIs: `schema:` is https://schema.org/, `rdfs:Class` the RDF Schema class of classes.
_SCHEMA_PREFIX = "schema:"
_RDFS_CLASS = "rdfs:Class"
_SUB_CLASS_OF = "rdfs:subClassOf"
# RDF Schema: `rdf:Property` is the class of properties, `rdfs:subPropertyOf` relates a property to a broader one.
_RDF_PROPERTY = "rdf:Property"
_SUB_PROPERTY_OF = "rdfs:subPropertyOf"
# schema.org `identifier`: "The identifier property represents any kind of identifier for any kind of Thing".
_IDENTIFIER = "identifier"
# schema.org namespaces: https is current, http the earlier one; the vocabulary treats both as the same terms.
NAMESPACES = ("https://schema.org/", "http://schema.org/")
_URL = FieldSpec(type=FieldType.URL)


def schema_term(iri: str) -> str | None:
    """The schema.org term an IRI names in either namespace (`http://schema.org/Product` is `Product`), else `None`."""
    return next((iri.removeprefix(n) for n in NAMESPACES if iri.startswith(n)), None)


class VocabularyMissing(RuntimeError):
    """The schema.org vocabulary file is not in the data directory: a deployment error, not bad input."""


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The schema.org types, each with itself and every type it is a subclass of, transitively; and the properties
    that identify a thing: `identifier` and its sub-properties, transitively (`sku`, `gtin13`); and each property's
    sub-properties, transitively (`narrower`)."""

    supertypes: Mapping[str, frozenset[str]]
    narrower: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def read(cls, path: Path) -> "Vocabulary":
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise VocabularyMissing(f"{path}: missing; run `crawlerai data fetch`") from None
        return cls.parse(json.loads(text))

    @classmethod
    def parse(cls, document: JsonValue) -> "Vocabulary":
        """The types of a schema.org vocabulary file: the `@graph` nodes typed `rdfs:Class` with a `schema:` id."""
        if not isinstance(document, dict) or not isinstance(graph := document.get("@graph"), list):
            raise ValueError("a schema.org vocabulary file is a JSON-LD document with a @graph")
        parents: dict[str, frozenset[str]] = {}
        broader: dict[str, frozenset[str]] = {}
        for node in graph:
            if not isinstance(node, dict):
                continue
            if (name := _term_name(node, _RDFS_CLASS)) is not None:
                parents[name] = frozenset(_schema_names(node.get(_SUB_CLASS_OF)))
            elif (name := _term_name(node, _RDF_PROPERTY)) is not None:
                broader[name] = frozenset(_schema_names(node.get(_SUB_PROPERTY_OF)))
        narrower: dict[str, set[str]] = {}
        for name in broader:
            for ancestor in _ancestors(name, broader) - {name}:
                narrower.setdefault(ancestor, set()).add(name)
        return cls(
            {name: _ancestors(name, parents) for name in parents},
            {name: frozenset(names) for name, names in narrower.items()},
        )

    @property
    def identifiers(self) -> frozenset[str]:
        return self.sub_properties(_IDENTIFIER) | {_IDENTIFIER}

    def __contains__(self, type_: object) -> bool:
        return type_ in self.supertypes

    def is_a(self, type_: str, ancestor: str) -> bool:
        return ancestor in self.supertypes.get(type_, frozenset())

    def sub_properties(self, prop: str) -> frozenset[str]:
        return self.narrower.get(prop, frozenset())

    def specific_first(self, names: Sequence[str]) -> tuple[str, ...]:
        """The vocabulary's types among `names`, each once, most specific first: a type that another listed type is a
        subtype of follows it."""
        known = list(dict.fromkeys(name for name in names if name in self))
        return tuple(sorted(known, key=lambda t: any(o != t and self.is_a(o, t) for o in known)))


@cache
def default_vocabulary() -> Vocabulary:
    """The vocabulary from the engine directory's `data/`, read once."""
    data = engine_data_dir()
    if data is None:
        raise VocabularyMissing("no engine directory: the schema.org vocabulary is read from its data/")
    return Vocabulary.read(data / VOCABULARY_FILE)


def _term_name(node: Mapping[str, JsonValue], kind: str) -> str | None:
    """The schema.org term a vocabulary node defines when it is typed `kind` (`rdfs:Class`, `rdf:Property`)."""
    types = node.get("@type")
    is_kind = types == kind or (isinstance(types, list) and kind in types)
    node_id = node.get("@id")
    if is_kind and isinstance(node_id, str) and node_id.startswith(_SCHEMA_PREFIX):
        return node_id.removeprefix(_SCHEMA_PREFIX)
    return None


def _schema_names(references: JsonValue) -> list[str]:
    names = []
    for ref in references if isinstance(references, list) else [references]:
        ref_id = ref.get("@id") if isinstance(ref, dict) else None
        if isinstance(ref_id, str) and ref_id.startswith(_SCHEMA_PREFIX):
            names.append(ref_id.removeprefix(_SCHEMA_PREFIX))
    return names


def _ancestors(name: str, parents: Mapping[str, frozenset[str]]) -> frozenset[str]:
    seen = {name}
    pending = [name]
    while pending:
        for parent in parents.get(pending.pop(), frozenset()):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return frozenset(seen)


class MappedPath(NamedTuple):
    root: str  # the type the path starts at
    steps: tuple[str, ...]  # the properties followed, the last one holding the value
    joined: str | None  # `+r`: a property of the last node joined to the value


def parse_paths(path: str) -> tuple[MappedPath, ...]:
    """A `schema_org` path's alternatives, already checked by the schema document's pattern (SPEC-04 §4.2)."""
    return tuple(_parse_alternative(alternative) for alternative in path.split("|"))


def _parse_alternative(path: str) -> MappedPath:
    path, _, joined = path.partition("+")
    root, *steps = path.split(".")
    return MappedPath(root, tuple(steps), joined or None)


def named_property(path: MappedPath) -> str:
    """The schema.org property whose value a path reaches: its last step, or the step before a final `.name`, since
    the text standing in for a thing names it (`_NAME`): `Product.brand.name` names `brand`."""
    if len(path.steps) > 1 and path.steps[-1:] == _NAME and path.joined is None:
        return path.steps[-2]
    return path.steps[-1]


@dataclass(frozen=True, slots=True)
class Value:
    """One value of a property: `raw` as the page states it (a node's JSON object for a node), where it is, and the
    node when the value is one whose properties a path can follow."""

    raw: JsonValue
    locator: str
    node: "Node | None" = None


class Node(Protocol):
    """A structured-data node: a JSON-LD object, or a microdata item."""

    @property
    def node_id(self) -> str | None:
        """The IRI that names the node (a JSON-LD `@id`, a microdata `itemid`), resolved."""
        ...

    def values(self, prop: str) -> Sequence[Value]: ...

    def every_value(self, prop: str) -> Sequence[Value]:
        """The values a list field reads: `values`, unless the source states one of them as the main value and lists
        all of them elsewhere (an adapter's `Shape.every`)."""
        ...


@dataclass(frozen=True, slots=True)
class Selected:
    raw: JsonValue
    locator: str


# schema.org data model ("Conformance"): where a property expects a Thing, a text value is accepted; the text names
# that thing. So a path ending in `.name` takes the text that stands in for the thing.
_NAME = ("name",)


def select(node: Node, path: MappedPath, *, as_list: bool) -> list[Selected]:
    """The values `path` (after its root type) reaches from `node`: those on nodes first, then text standing in for a
    named thing, each in document order. Each value is its own selection; for a list field (`as_list`), a node's values
    of the last property are one selection, located at the first value."""
    holders: list[Node] = [node]
    named: list[Selected] = []
    for i, step in enumerate(path.steps[:-1]):
        names_thing = path.steps[i + 1 :] == _NAME and path.joined is None
        reached: list[Node] = []
        for holder in holders:
            for value in holder.values(step):
                if value.node is not None:
                    reached.append(value.node)
                elif names_thing and isinstance(value.raw, str):
                    named.append(Selected(value.raw, value.locator))
        holders = reached
    selected = [s for holder in holders for s in _last(holder, path, as_list=as_list)]
    return selected + named


def _last(holder: Node, path: MappedPath, *, as_list: bool) -> list[Selected]:
    values = holder.every_value(path.steps[-1]) if as_list else holder.values(path.steps[-1])
    if not values:
        return []
    if as_list:
        return [Selected([v.raw for v in values], values[0].locator)]
    if path.joined is None:
        return [Selected(v.raw, v.locator) for v in values]
    companions = [c.raw for c in holder.values(path.joined)]
    extra: dict[str, JsonValue] = {}
    if companions:
        extra[path.joined] = companions[0] if len(companions) == 1 else companions
    return [Selected({path.steps[-1]: v.raw} | extra, v.locator) for v in values]


@dataclass(frozen=True, slots=True)
class Typed:
    """A node that is an entity: its entity id and its schema.org types, most specific first."""

    id: str
    types: tuple[str, ...]
    node: Node


def field_candidates(
    entities: Sequence[Typed],
    schema: SchemaDef,
    ctx: Context,
    *,
    vocabulary: Vocabulary,
    source_kind: SourceKind,
    diagnostics: list[str],
) -> Iterator[Candidate]:
    """A candidate per value each field's path reaches on each entity of its type. A row-mapped field's path names its
    rows, which resolution finds (SPEC-13 §4.3); each of its sub-fields is read as a field of its own."""
    for name, spec, paths in mapped_fields(schema):
        as_list = spec.type is FieldType.LIST
        if spec.type is FieldType.IDENTIFIER:
            paths = _with_sub_properties(paths, vocabulary)
        for entity_id, selected in _selections(entities, paths, vocabulary, as_list=as_list):
            found = candidate(name, spec, entity_id, source_kind, selected.raw, selected.locator, ctx, diagnostics)
            if found is not None:
                yield found


def mapped_fields(schema: SchemaDef) -> Iterator[tuple[str, FieldSpec, tuple[MappedPath, ...]]]:
    """The fields whose values a `schema_org` path reaches, by candidate field name, with the path's alternatives: each
    field with a path, except a row-mapped one, whose path reaches rows, not values; in its place, its sub-fields with
    a path, as `<field>.<sub-field>` (SPEC-13 §4.2; `Name` allows no `.`, so these never clash with a field's name)."""
    for name, spec in schema.fields.items():
        if spec.row_mapped and spec.item is not None:
            for sub_name, sub in (spec.item.fields or {}).items():
                if sub.schema_org is not None:
                    yield f"{name}.{sub_name}", sub, parse_paths(sub.schema_org)
        elif spec.schema_org is not None:
            yield name, spec, parse_paths(spec.schema_org)


def _with_sub_properties(paths: Sequence[MappedPath], vocabulary: Vocabulary) -> tuple[MappedPath, ...]:
    """Each alternative, then the same path ending in each sub-property of its last property. RDF Schema 1.1 §3.5
    (`rdfs:subPropertyOf`): a value of a sub-property is a value of the property, so a `gtin13` is a `gtin`. Only an
    identifier field reads them: an identifier's sub-properties name its schemes (GTIN-13 of GTIN), while others
    narrow what the value is (`logo` of `image`), which the field's own property does not mean."""
    return tuple(
        widened
        for path in paths
        for widened in (path, *(_ending_in(path, sub) for sub in sorted(vocabulary.sub_properties(path.steps[-1]))))
    )


def _ending_in(path: MappedPath, prop: str) -> MappedPath:
    return path._replace(steps=(*path.steps[:-1], prop))


def _selections(
    entities: Sequence[Typed], paths: Sequence[MappedPath], vocabulary: Vocabulary, *, as_list: bool
) -> Iterator[tuple[str, Selected]]:
    """What each alternative reaches on each entity of its root type, by entity id. The same value of one entity that
    two alternatives reach is one selection (SPEC-13 §4.1): its locator names it. One alternative's selections are
    all kept, as a path's are."""
    earlier: set[tuple[str, str]] = set()
    for path in paths:
        reached: set[tuple[str, str]] = set()
        for entity in entities:
            if not any(vocabulary.is_a(t, path.root) for t in entity.types):
                continue
            for selected in select(entity.node, path, as_list=as_list):
                if (entity.id, selected.locator) not in earlier:
                    reached.add((entity.id, selected.locator))
                    yield entity.id, selected
        earlier |= reached


def candidate(
    field: str,
    spec: FieldSpec,
    entity_id: str,
    source_kind: SourceKind,
    raw: JsonValue,
    locator: str,
    ctx: Context,
    diagnostics: list[str],
) -> Candidate | None:
    """The independent candidate of one value a collector read from a source's own structure, normalized as `spec`.
    A value the candidate model refuses (nested deeper than its validator recurses) is skipped with a diagnostic: a
    collector never raises on page content (SPEC-05 §4.5)."""
    try:
        return Candidate(
            field=field,
            entity_id=entity_id,
            source_kind=source_kind,
            raw=raw,
            normalized=normalize(raw, spec, ctx),
            locator=locator,
            independent=True,
        )
    except ValidationError as e:
        diagnostics.append(f"value at {locator} skipped ({e.errors()[0]['type']})")
        return None


def entity_urls(node: Node, ctx: Context) -> tuple[str, ...]:
    """The canonical URLs that name the page an entity is on (SPEC-05 §4.2): its own (`item_urls`) and its offers'
    (`offer_urls`)."""
    return tuple(dict.fromkeys((*item_urls(node, ctx), *offer_urls(node, ctx))))


def offer_urls(node: Node, ctx: Context) -> tuple[str, ...]:
    """The canonical `url` values of the entity's offers."""
    return canonical_urls(
        (v.raw for value in node.values("offers") if value.node is not None for v in value.node.values("url")), ctx
    )


def item_urls(node: Node, ctx: Context) -> tuple[str, ...]:
    """The canonical URLs that name the item itself: its `url` and its own IRI, and its `mainEntityOfPage`."""
    return canonical_urls(_item_names(node), ctx)


def _item_names(node: Node) -> list[JsonValue]:
    written: list[JsonValue] = _page_names(node)
    for value in node.values("mainEntityOfPage"):
        written.extend(_page_names(value.node) if value.node is not None else [value.raw])
    return written


def canonical_urls(written: Iterable[JsonValue], ctx: Context) -> tuple[str, ...]:
    """The values of `written` that normalize as URLs, canonicalized, each once, in order."""
    results = [normalize(raw, _URL, ctx) for raw in written]
    return tuple(dict.fromkeys(r.value for r in results if isinstance(r, Ok) and isinstance(r.value, str)))


def _page_names(node: Node) -> list[JsonValue]:
    names: list[JsonValue] = [v.raw for v in node.values("url")]
    # RFC 3986 §3.5: an IRI with a fragment names a part of a document, not the page itself.
    if node.node_id is not None and not urlsplit(node.node_id).fragment:
        names.append(node.node_id)
    return names
