"""The schema.org map (extraction spec), shared by the structured-data collectors (JSON-LD, microdata): the type
hierarchy from the pinned schema.org vocabulary file, and a schema field's `schema_org` path read against a node.

A path `T.p[.q][+r]` (schemas spec) applies to every entity of type `T` or a subtype of it (`rdfs:subClassOf`). It
follows `p`, then `q`, through the nodes the values name; `+r` joins the last node's `r` to the value as one object.
A path of alternatives `A|B` (variants spec) reaches what each alternative reaches. A row-mapped field's sub-fields are
read as fields of their own, named `<field>.<sub-field>` (variants spec).
"""

import html
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import NamedTuple, Protocol
from urllib.parse import urlsplit

from pydantic import JsonValue, ValidationError

from crawlerai.collect.base import Candidate, Entity
from crawlerai.content.text import fragment_text
from crawlerai.core.engine_version import engine_data_dir
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# The pinned schema.org release in `backend/data/manifest.json` (schemas spec, D-0018).
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
# schema.org `productGroupID`: "a textual identifier for a ProductGroup", so it identifies the group as `identifier`
# values identify an item; `inProductGroupWithID`: "the productGroupID for a ProductGroup that this product
# isVariantOf".
_GROUP_ID = "productGroupID"
_IN_GROUP = "inProductGroupWithID"
# schema.org `isVariantOf`: "Indicates the kind of product that this is a variant of", a ProductGroup or ProductModel.
_VARIANT_OF = "isVariantOf"
# schema.org ListItem: an item in a list; its `item` is "An entity represented by an entry in a list" (range Thing).
# An entry stating no `item` stands for the thing it lists with its own Thing properties (`name`, `url`), so a
# listing's row fields read them (`resolve.listing`).
ENTRY = "ListItem"
_ITEM = "item"
# JSON-LD 1.1 §4.5.1: a blank node identifier is scoped to its document, so it identifies nothing across blocks.
_BLANK = "_:"


def schema_term(iri: str) -> str | None:
    """The schema.org term an IRI names in either namespace (`http://schema.org/Product` is `Product`), else `None`."""
    return next((iri.removeprefix(n) for n in NAMESPACES if iri.startswith(n)), None)


class VocabularyMissing(RuntimeError):
    """The schema.org vocabulary file is not in the data directory: a deployment error, not bad input."""


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The schema.org types, each with itself and every type it is a subclass of, transitively; each property's
    sub-properties, transitively (`narrower`), among them the properties that identify a thing (`identifier` and
    its sub-properties: `sku`, `gtin13`); and the names of all properties."""

    supertypes: Mapping[str, frozenset[str]]
    narrower: Mapping[str, frozenset[str]] = field(default_factory=dict)
    properties: frozenset[str] = frozenset()

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
            frozenset(broader),
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


# schema.org: "An Enumeration is a type whose members are named instances of it" (`schema:Enumeration`).
_ENUMERATION = "Enumeration"


def reference_errors(fields: Mapping[str, FieldSpec], vocabulary: Vocabulary) -> list[tuple[str, str]]:
    """The `schema_org` paths and `schema:` enum references of a schema document's `fields` that the pinned schema.org
    vocabulary does not define, as (field path, reason) pairs (schemas spec). A path's root must be a type and each
    step and its `+` join a property; a `schema:` reference must be an enumeration. `type:` references name the
    shipped type vocabularies, which the normalizer declines on when unknown (`unknown_vocab`)."""
    errors: list[tuple[str, str]] = []
    for name, spec in fields.items():
        _reference_errors(f"fields.{name}", spec, vocabulary, errors)
    return errors


def _reference_errors(path: str, spec: FieldSpec, vocabulary: Vocabulary, errors: list[tuple[str, str]]) -> None:
    if spec.schema_org is not None:
        errors.extend((f"{path}.schema_org", reason) for reason in _path_problems(spec.schema_org, vocabulary))
    if spec.vocab is not None and spec.vocab.startswith("schema:"):
        enumeration = spec.vocab.removeprefix("schema:")
        if not vocabulary.is_a(enumeration, _ENUMERATION) or enumeration == _ENUMERATION:
            errors.append((f"{path}.vocab", f"{enumeration} is not a schema.org enumeration"))
    if spec.item is not None:
        _reference_errors(f"{path}.item", spec.item, vocabulary, errors)
    for sub_name, sub in (spec.fields or {}).items():
        _reference_errors(f"{path}.fields.{sub_name}", sub, vocabulary, errors)


def _path_problems(schema_org: str, vocabulary: Vocabulary) -> list[str]:
    problems = []
    for alternative in parse_paths(schema_org):
        if alternative.root not in vocabulary:
            problems.append(f"{alternative.root} is not a schema.org type")
        problems.extend(
            f"{prop} is not a schema.org property"
            for prop in (*alternative.steps, *([alternative.joined] if alternative.joined else []))
            if prop not in vocabulary.properties
        )
    return problems


def pinned_reference_errors(fields: Mapping[str, FieldSpec]) -> list[tuple[str, str]]:
    """`reference_errors` against the pinned vocabulary (`default_vocabulary`), for every path that stores a schema
    (schemas spec, "schema.org paths"). A process without the vocabulary file checks syntax only, as it extracts no
    records (`load_engine_data`)."""
    try:
        vocabulary = default_vocabulary()
    except VocabularyMissing:
        return []
    return reference_errors(fields, vocabulary)


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
    rank: int = 0  # how many `>` come before it: read on an entity only when no lower rank reaches a value there


def parse_paths(path: str) -> tuple[MappedPath, ...]:
    """A `schema_org` path's alternatives, in order, each with its rank, already checked by the schema document's
    pattern (schemas spec)."""
    return tuple(
        _parse_alternative(alternative, rank)
        for rank, ranked in enumerate(path.split(">"))
        for alternative in ranked.split("|")
    )


def _parse_alternative(path: str, rank: int) -> MappedPath:
    path, _, joined = path.partition("+")
    root, *steps = path.split(".")
    return MappedPath(root, tuple(steps), joined or None, rank)


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
    # Whether the source gives the value as a URL it names, not as text (HTML microdata "Values": a hyperlink's or an
    # embedded resource's URL attribute; RDFa's IRI attributes).
    url: bool = False


class Node(Protocol):
    """A structured-data node: a JSON-LD object, or a microdata item."""

    @property
    def node_id(self) -> str | None:
        """The IRI that names the node (a JSON-LD `@id`, a microdata `itemid`), resolved."""
        ...

    def values(self, prop: str) -> Sequence[Value]: ...


@dataclass(frozen=True, slots=True)
class Selected:
    raw: JsonValue
    locator: str
    url: bool = False  # `Value.url` of every value selected


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
                    named.append(Selected(value.raw, value.locator, value.url))
        holders = reached
    selected = [s for holder in holders for s in _last(holder, path, as_list=as_list)]
    return selected + named


def _last(holder: Node, path: MappedPath, *, as_list: bool) -> list[Selected]:
    values = holder.values(path.steps[-1])
    if not values:
        return []
    if as_list:
        return [Selected([v.raw for v in values], values[0].locator, all(v.url for v in values))]
    if path.joined is None:
        return [Selected(v.raw, v.locator, v.url) for v in values]
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


# A URL is not prose: the text types (schemas spec `text`, `long_text`) take no value a source gives as a URL.
_TEXT_TYPES = frozenset({FieldType.TEXT, FieldType.LONG_TEXT})


def _holds_text(spec: FieldSpec) -> bool:
    """Whether the field's values are prose: a text type, or a list of one."""
    item = spec.item if spec.type is FieldType.LIST else spec
    return item is not None and item.type in _TEXT_TYPES


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
    rows, which resolution finds (variants spec); each of its sub-fields is read as a field of its own."""
    for name, spec, mapped in mapped_fields(schema):
        as_list = spec.type is FieldType.LIST
        entries = schema.page_kind == "listing" and spec.scope == "row"
        paths = _read_paths(spec, mapped, vocabulary, entries=entries)
        for entity_id, selected in _selections(entities, paths, vocabulary, as_list=as_list, entries=entries):
            if selected.url and _holds_text(spec):
                continue
            read = fragment_read(selected.raw, spec)
            found = candidate(
                name, spec, entity_id, source_kind, selected.raw, selected.locator, ctx, diagnostics, read=read
            )
            if found is not None:
                yield found


def _read_paths(
    spec: FieldSpec, paths: tuple[MappedPath, ...], vocabulary: Vocabulary, *, entries: bool
) -> tuple[MappedPath, ...]:
    """The paths a field is read through: its own, an identifier's sub-properties, a listing row's item pages."""
    if spec.type is FieldType.IDENTIFIER:
        paths = _with_sub_properties(paths, vocabulary, spec.scheme)
    return _with_item_pages(paths) if entries and is_item_url(spec) else paths


def fragment_read(raw: JsonValue, spec: FieldSpec) -> str | None:
    """What a text field reads of a structured-data value holding element markup: the fragment's rendered text
    (`fragment_text`), its references already decoded once, so they are escaped again for the text normalizer, which
    decodes them (a literal `&amp;` stays text). A value whose markup is written escaped (`&lt;p&gt;…&lt;/p&gt;`, a
    fragment serialized with its `<` and `>` as character references, as an API that documents its text as escaped
    HTML writes it) is that fragment: its references decoded once (HTML Standard, character references) give elements,
    and their rendered text is what the value says. `None` for any other value: one that decodes to no element
    (`1 &lt; 2`) is text."""
    if spec.type not in _TEXT_TYPES or not isinstance(raw, str):
        return None
    text = fragment_text(raw)
    if text is None and "&" in raw:
        text = fragment_text(html.unescape(raw))
    return None if text is None else html.escape(text, quote=False)


def mapped_fields(schema: SchemaDef) -> Iterator[tuple[str, FieldSpec, tuple[MappedPath, ...]]]:
    """The fields whose values a `schema_org` path reaches, by candidate field name, with the path's alternatives: each
    field with a path, except a row-mapped one, whose path reaches rows, not values; in its place, its sub-fields with
    a path, as `<field>.<sub-field>` (variants spec; `Name` allows no `.`, so these never clash with a field's name)."""
    for name, spec in schema.fields.items():
        if spec.row_mapped and spec.item is not None:
            for sub_name, sub in (spec.item.fields or {}).items():
                if sub.schema_org is not None:
                    yield f"{name}.{sub_name}", sub, parse_paths(sub.schema_org)
        elif spec.schema_org is not None:
            yield name, spec, parse_paths(spec.schema_org)


def _with_sub_properties(
    paths: Sequence[MappedPath], vocabulary: Vocabulary, scheme: str | None
) -> tuple[MappedPath, ...]:
    """Each alternative, then the same path ending in each sub-property of its last property. RDF Schema 1.1 §3.5
    (`rdfs:subPropertyOf`): a value of a sub-property is a value of the property, so a `gtin13` is a `gtin`. Only an
    identifier field reads them: an identifier's sub-properties name its schemes (GTIN-13 of GTIN), while others
    narrow what the value is (`logo` of `image`), which the field's own property does not mean. A path ending in
    `identifier` itself names no scheme, so it widens only to the field's own scheme: the schema.org property of that
    name (`gtin` for scheme `gtin`) and its sub-properties, never the other schemes (D-1273)."""
    return tuple(
        widened
        for path in paths
        for widened in (
            path,
            *(_ending_in(path, sub) for sub in sorted(_widening(path.steps[-1], vocabulary, scheme))),
        )
    )


def is_item_url(spec: FieldSpec) -> bool:
    """Whether a field holds a listing row's item URL: a row url field whose path names the item's own schema.org
    `url` ("URL of the item"), straight from the row's type."""
    return (
        spec.scope == "row"
        and spec.type is FieldType.URL
        and spec.schema_org is not None
        and any(path.steps == _ITEM_URL and path.joined is None for path in parse_paths(spec.schema_org))
    )


def item_url_fields(schema: SchemaDef) -> tuple[str, ...]:
    """The schema's row fields holding the item's own URL (`is_item_url`)."""
    return tuple(name for name, spec in schema.fields.items() if is_item_url(spec))


# schema.org Thing.url, "URL of the item"; then, a rank later each, Offer.url (the offer's page, the one a listing's row
# links to) and Thing.mainEntityOfPage ("the Web page for which this thing is the main entity": a URL, or a
# CreativeWork stating its `url`).
_ITEM_URL = ("url",)
_ITEM_PAGES: tuple[tuple[tuple[str, ...], ...], ...] = (
    (("offers", "url"),),
    (("mainEntityOfPage",), ("mainEntityOfPage", "url")),
)


def _with_item_pages(paths: Sequence[MappedPath]) -> tuple[MappedPath, ...]:
    """An item URL field's alternatives, then the pages of `_ITEM_PAGES`, each a rank later, from the same type: a row
    whose structured data names its item's page only through its offer or as its main entity still has that page (the
    master plan's row key: block link, else `Offer.url`, else `mainEntityOfPage`)."""
    later = max(path.rank for path in paths) + 1
    widened = [
        path._replace(steps=steps, rank=later + offset)
        for path in paths
        if path.steps == _ITEM_URL and path.joined is None
        for offset, alternatives in enumerate(_ITEM_PAGES)
        for steps in alternatives
    ]
    return (*paths, *widened)


def _widening(prop: str, vocabulary: Vocabulary, scheme: str | None) -> frozenset[str]:
    subs = vocabulary.sub_properties(prop)
    if prop != _IDENTIFIER:
        return subs
    if scheme not in subs:
        return frozenset()
    return frozenset({scheme}) | vocabulary.sub_properties(scheme)


def _ending_in(path: MappedPath, prop: str) -> MappedPath:
    return path._replace(steps=(*path.steps[:-1], prop))


def _selections(
    entities: Sequence[Typed], paths: Sequence[MappedPath], vocabulary: Vocabulary, *, as_list: bool, entries: bool
) -> Iterator[tuple[str, Selected]]:
    """What each alternative reaches on each entity of its root type, by entity id, and with `entries` (a listing's
    row field) on each list entry without an item (`ENTRY`). The same value of one entity that two alternatives reach
    is one selection (variants spec): its locator names it. One alternative's selections are all kept, as a path's
    are. An alternative of a higher rank (after a `>`) reads no entity on which a lower rank reached a stated value
    (a string or a number: a node reaching the end of a path states none the field can read)."""
    earlier: set[tuple[str, str]] = set()
    held: set[str] = set()  # the entities a lower rank reached a stated value on
    stated: set[str] = set()
    rank = 0
    for path in paths:
        if path.rank != rank:
            rank, held = path.rank, held | stated
        readable = [e for e in entities if e.id not in held and _reads(e, path, vocabulary, entries)]
        reached = list(_reached(readable, path, as_list=as_list, earlier=earlier))
        earlier |= {(entity_id, selected.locator) for entity_id, selected in reached}
        stated |= {entity_id for entity_id, selected in reached if isinstance(selected.raw, str | int | float)}
        yield from reached


def _reached(
    entities: Sequence[Typed], path: MappedPath, *, as_list: bool, earlier: set[tuple[str, str]]
) -> Iterator[tuple[str, Selected]]:
    """What `path` reaches on each entity that no earlier alternative reached."""
    for entity in entities:
        for selected in select(entity.node, path, as_list=as_list):
            if (entity.id, selected.locator) not in earlier:
                yield entity.id, selected


def _reads(entity: Typed, path: MappedPath, vocabulary: Vocabulary, entries: bool) -> bool:
    return any(vocabulary.is_a(t, path.root) for t in entity.types) or (entries and _bare_entry(entity))


def _bare_entry(entity: Typed) -> bool:
    return ENTRY in entity.types and not entity.node.values(_ITEM)


def candidate(
    field: str,
    spec: FieldSpec,
    entity_id: str,
    source_kind: SourceKind,
    raw: JsonValue,
    locator: str,
    ctx: Context,
    diagnostics: list[str],
    *,
    read: JsonValue = None,
) -> Candidate | None:
    """The independent candidate of one value a collector read from a source's own structure, normalized as `spec`
    (from `read` when given: what the field reads of `raw`). A value the candidate model refuses (nested deeper than
    its validator recurses) is skipped with a diagnostic: a collector never raises on page content (extraction spec)."""
    try:
        return Candidate(
            field=field,
            entity_id=entity_id,
            source_kind=source_kind,
            raw=raw,
            normalized=normalize(raw if read is None else read, spec, ctx),
            locator=locator,
            independent=True,
        )
    except ValidationError as e:
        diagnostics.append(f"value at {locator} skipped ({e.errors()[0]['type']})")
        return None


def entity_urls(node: Node, ctx: Context) -> tuple[str, ...]:
    """The canonical URLs that name the page an entity is on (extraction spec): its own (`item_urls`) and its offers'
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


def entity(typed: Typed, ctx: Context, vocabulary: Vocabulary, *, parent: str | None, via: str | None) -> Entity:
    """The entity of a node: its URLs (`entity_urls`), its own URLs (`item_urls`), what identifies it (`identity`) and
    the product groups it names (`group_ids`, `variant_of`)."""
    return Entity(
        id=typed.id,
        types=typed.types,
        urls=entity_urls(typed.node, ctx),
        parent=parent,
        via=via,
        identity=identity(typed.node, vocabulary),
        item_urls=item_urls(typed.node, ctx),
        group_ids=tuple(dict.fromkeys(_scalar_texts(typed.node, _IN_GROUP))),
        variant_of=tuple(dict.fromkeys(_node_iris(typed.node, _VARIANT_OF))),
    )


def identity(node: Node, vocabulary: Vocabulary) -> tuple[tuple[str, str], ...]:
    """What identifies a node, as (property, value) pairs: its IRI (`@id`, `itemid`) unless it is a blank node, each
    scalar value of its identifier properties (`identifier` and its `rdfs:subPropertyOf` descendants: `sku`, `gtin13`),
    and a ProductGroup's `productGroupID`."""
    found: list[tuple[str, str]] = []
    node_id = node.node_id
    if node_id is not None and not node_id.startswith(_BLANK):
        found.append(("@id", node_id))
    for prop in sorted(vocabulary.identifiers | {_GROUP_ID}):
        found.extend((prop, text) for text in _scalar_texts(node, prop))
    return tuple(dict.fromkeys(found))


def _node_iris(node: Node, prop: str) -> Iterator[str]:
    """The IRIs of the nodes `prop` names on the node (a JSON-LD `{"@id": ...}` reference included); a blank node has
    none that names it beyond the page."""
    for value in node.values(prop):
        node_id = value.node.node_id if value.node is not None else None
        if node_id is not None and not node_id.startswith(_BLANK):
            yield node_id


def _scalar_texts(node: Node, prop: str) -> Iterator[str]:
    """The non-blank scalar values of `prop` on the node, as text; a node value (a `PropertyValue`) is no scalar."""
    for value in node.values(prop):
        raw = value.raw
        if value.node is None and raw is not None and not isinstance(raw, (dict, list)) and (text := str(raw).strip()):
            yield text
