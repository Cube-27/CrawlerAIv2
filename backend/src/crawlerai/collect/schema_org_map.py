"""The schema.org map (extraction spec), shared by the structured-data collectors (JSON-LD, microdata): a schema
field's `schema_org` path read against a node, with the type hierarchy of `collect.vocabulary`.

A path `T.p[.q][+r]` (schemas spec, grammar in `schemas.paths`) applies to every entity of type `T` or a subtype of it
(`rdfs:subClassOf`). It follows `p`, then `q`, through the nodes the values name, keeping at each step only the nodes
its filter predicates match; each `+r` joins the last node's `r` to the value as one object.
A path of alternatives `A|B` (variants spec) reaches what each alternative reaches. A row-mapped field's sub-fields are
read as fields of their own, named `<field>.<sub-field>` (variants spec).
"""

import html
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import JsonValue, ValidationError

from crawlerai.acquire.public_suffix import default_suffixes
from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.vocabulary import IDENTIFIER, Vocabulary, schema_term
from crawlerai.content.text import fragment_text
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.paths import NAME, Filters, MappedPath, Predicate, parse_paths
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

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
# schema.org AggregateOffer: `lowPrice` "the lowest price of all offers available", `highPrice` the highest, each a
# Number (or Text) written with a `.` decimal point, in `priceCurrency`.
_AGGREGATE_OFFER = "AggregateOffer"
_LOW_PRICE, _HIGH_PRICE, _CURRENCY = "lowPrice", "highPrice", "priceCurrency"
# JSON-LD 1.1 §4.5.1: a blank node identifier is scoped to its document, so it identifies nothing across blocks.
_BLANK = "_:"


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


def select(node: Node, path: MappedPath, *, as_list: bool, as_url: bool) -> list[Selected]:
    """The values `path` (after its root type) reaches from `node`: those on nodes first, then text standing in for a
    named thing, each in document order. Each value is its own selection; for a list field (`as_list`), a node's values
    of the last property are one selection, located at the first value. A step's predicates keep the nodes its values
    are (`matches`); text standing in for a thing states nothing else, so it is kept only by a step without them. With
    `as_url` (a url or image field), a last value that is a node is the URL it states (`_media_url`)."""
    holders: list[Node] = [node]
    named: list[Selected] = []
    for i in range(len(path.steps) - 1):
        holders = list(_step(holders, path, i, named))
    # The last step's value is a scalar: its predicates read the node holding it (`Offer.price{!priceType}`).
    last = path.where(len(path.steps) - 1)
    selected = [
        s for holder in holders if matches(holder, last) for s in _last(holder, path, as_list=as_list, as_url=as_url)
    ]
    return selected + named


def _step(holders: Iterable[Node], path: MappedPath, i: int, named: list[Selected]) -> Iterator[Node]:
    """The nodes step `i` reaches from `holders` that its predicates keep; text standing in for a thing named by the
    step before a final `.name` is added to `named`."""
    names_thing = path.steps[i + 1 :] == NAME and not path.joined and not path.where(i) and not path.where(i + 1)
    for holder in holders:
        for value in holder.values(path.steps[i]):
            if value.node is not None and matches(value.node, path.where(i)):
                yield value.node
            elif names_thing and value.node is None and isinstance(value.raw, str):
                named.append(Selected(value.raw, value.locator, value.url))


def matches(node: Node, filters: Filters) -> bool:
    """Whether the node meets every predicate (schemas spec, "schema.org paths"): `{name}` it states `name`, `{!name}`
    it does not, `{name=Value}` one of its `name` values is `Value`, as a term or as an IRI in either schema.org
    namespace, written as text or as a node's `@id` (JSON-LD 1.1 §4.1.1: an IRI value may be a node reference)."""
    return all(_meets(node.values(p.name), p) for p in filters)


def _meets(values: Sequence[Value], predicate: Predicate) -> bool:
    if predicate.absent:
        return not values
    if predicate.value is None:
        return bool(values)
    return any(predicate.value in _terms(value) for value in values)


def _terms(value: Value) -> tuple[str, ...]:
    written = value.node.node_id if value.node is not None else value.raw
    if not isinstance(written, str):
        return ()
    term = schema_term(written)
    return (written,) if term is None else (written, term)


def _last(holder: Node, path: MappedPath, *, as_list: bool, as_url: bool) -> list[Selected]:
    values = [_media_url(v) for v in holder.values(path.steps[-1])] if as_url else holder.values(path.steps[-1])
    if not values:
        return []
    if as_list:
        return [Selected([v.raw for v in values], values[0].locator, all(v.url for v in values))]
    if not path.joined:
        return [Selected(v.raw, v.locator, v.url) for v in values]
    extra = _joined(holder, path.joined)
    return [Selected({path.steps[-1]: v.raw} | extra, v.locator) for v in values]


# schema.org: `image` (and `logo`, `thumbnail`) ranges over ImageObject and URL, and a MediaObject's `contentUrl` is
# "actual bytes of the media object"; any Thing's `url` is "URL of the item". So a node where a URL is read names the
# URL by its `contentUrl`, else its `url`.
_NODE_URLS: tuple[str, ...] = ("contentUrl", "url")


def _media_url(value: Value) -> Value:
    """`value`, or for a node the first URL it states by `_NODE_URLS` (as a URL, at its own place); a node stating none
    stays the node."""
    if value.node is None:
        return value
    for prop in _NODE_URLS:
        if stated := [v for v in value.node.values(prop) if v.node is None and isinstance(v.raw, str)]:
            return stated[0]
    return value


def _joined(holder: Node, joined: Sequence[str]) -> dict[str, JsonValue]:
    """The values of the joined properties the holder states: one value as itself, several as a list."""
    extra: dict[str, JsonValue] = {}
    for prop in joined:
        if companions := [c.raw for c in holder.values(prop)]:
            extra[prop] = companions[0] if len(companions) == 1 else companions
    return extra


@dataclass(frozen=True, slots=True)
class Typed:
    """A node that is an entity: its entity id and its schema.org types, most specific first."""

    id: str
    types: tuple[str, ...]
    node: Node


# A URL is not prose: the text types (schemas spec `text`, `long_text`) take no value a source gives as a URL.
_TEXT_TYPES = frozenset({FieldType.TEXT, FieldType.LONG_TEXT})
# The types whose values are URLs (schemas spec `url`, `image_url`).
_URL_TYPES = frozenset({FieldType.URL, FieldType.IMAGE_URL})
# RFC 9110 §4.2: the http and https URI schemes name resources on the Web.
_WEB_SCHEMES = frozenset({"http", "https"})


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
    rows, which resolution finds (variants spec); each of its sub-fields is read as a field of its own. A listing row's
    item URL field reads, last, an entity's own IRI (`_item_iri`)."""
    for name, spec, mapped in mapped_fields(schema):
        entries = schema.page_kind == "listing" and spec.scope == "row"
        paths = _read_paths(spec, mapped, vocabulary, entries=entries)
        found = list(
            _path_candidates(name, spec, entities, paths, vocabulary, source_kind, ctx, diagnostics, entries=entries)
        )
        yield from found
        if entries and is_item_url(spec):
            read_on = {c.entity_id for c in found if isinstance(c.normalized, Ok)}
            unread = [e for e in entities if e.id not in read_on and any(_reads(e, p, vocabulary, True) for p in paths)]
            yield from (c for e in unread for c in _item_iri(name, spec, e, source_kind, ctx, diagnostics))


def _path_candidates(
    name: str,
    spec: FieldSpec,
    entities: Sequence[Typed],
    paths: Sequence[MappedPath],
    vocabulary: Vocabulary,
    source_kind: SourceKind,
    ctx: Context,
    diagnostics: list[str],
    *,
    entries: bool,
) -> Iterator[Candidate]:
    """A candidate per value the field's `paths` reach on each entity of their types (`_selections`)."""
    for entity_id, selected in _selections(entities, paths, vocabulary, spec=spec, entries=entries):
        if selected.url and _holds_text(spec):
            continue
        read = fragment_read(selected.raw, spec)
        if read is None:
            read = _member_read(selected.raw, spec, vocabulary)
        found = candidate(
            name, spec, entity_id, source_kind, selected.raw, selected.locator, ctx, diagnostics, read=read
        )
        if found is not None:
            yield found


def _member_read(raw: JsonValue, spec: FieldSpec, vocabulary: Vocabulary) -> str | None:
    """What a text field reads of a value that is the IRI of a schema.org enumeration member (a property whose range
    is an enumeration or Text, `suggestedGender`: `https://schema.org/Male`): the member's name, as an enum field
    publishes it (normalization spec, enum). The IRI names the member; it is not text the page states. `None` for any
    other value."""
    if spec.type not in _TEXT_TYPES or not isinstance(raw, str):
        return None
    term = schema_term(raw.strip())
    return term if term is not None and term in vocabulary.members else None


def _item_iri(
    name: str, spec: FieldSpec, entity: Typed, source_kind: SourceKind, ctx: Context, diagnostics: list[str]
) -> Iterator[Candidate]:
    """The item URL a listing row's node names only as its own IRI (JSON-LD 1.1 §4.1.2 `@id`, microdata `itemid`),
    read when no `url`, Offer URL or main entity page gave one: an absolute http(s) IRI with no fragment (RFC 3986 §3.5:
    a fragment names a part of a document, not the item's page), on the page's site (HTML Standard §7.1.1, the same
    registrable domain), and not the page's own URL, which names the list."""
    iri = entity.node.node_id
    page = ctx.page_url
    if iri is None or page is None:
        return
    split = urlsplit(iri)
    if split.scheme not in _WEB_SCHEMES or not split.hostname or split.fragment or not same_site(split.hostname, page):
        return
    found = candidate(name, spec, entity.id, source_kind, iri, entity.id, ctx, diagnostics)
    own = normalize(page, _URL, ctx)
    named = found.normalized if found is not None else None
    if found is not None and not (isinstance(own, Ok) and isinstance(named, Ok) and own.value == named.value):
        yield found


def same_site(host: str, page_url: str) -> bool:
    """Whether `host` is on the site of `page_url` (HTML Standard §7.1.1, the same registrable domain)."""
    page_host = urlsplit(page_url).hostname
    suffixes = default_suffixes()
    return page_host is not None and suffixes.site(host) == suffixes.site(page_host)


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
    decodes them. A value whose markup is written escaped (`&lt;p&gt;…&lt;/p&gt;`, a
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


def names_item_url(path: MappedPath) -> bool:
    """Whether the path alternative names its type's own schema.org `url` ("URL of the item"), straight from it."""
    return path.steps == _ITEM_URL and not path.joined


def is_item_url(spec: FieldSpec) -> bool:
    """Whether a field holds a listing row's item URL, the one predicate of the engine, the record row key and the
    recurring listing diff alike: a row url field one of whose path's alternatives names the item's own schema.org
    `url` (`names_item_url`). Its other alternatives (`Offer.url`) read the same item's URL another way."""
    return (
        spec.scope == "row"
        and spec.type is FieldType.URL
        and spec.schema_org is not None
        and any(names_item_url(path) for path in parse_paths(spec.schema_org))
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
        path._replace(steps=steps, rank=later + offset, filters=())
        for path in paths
        if path.steps == _ITEM_URL and not path.joined
        for offset, alternatives in enumerate(_ITEM_PAGES)
        for steps in alternatives
    ]
    return (*paths, *widened)


def _widening(prop: str, vocabulary: Vocabulary, scheme: str | None) -> frozenset[str]:
    subs = vocabulary.sub_properties(prop)
    if prop != IDENTIFIER:
        return subs
    if scheme not in subs:
        return frozenset()
    return frozenset({scheme}) | vocabulary.sub_properties(scheme)


def _ending_in(path: MappedPath, prop: str) -> MappedPath:
    return path._replace(steps=(*path.steps[:-1], prop))


def _selections(
    entities: Sequence[Typed], paths: Sequence[MappedPath], vocabulary: Vocabulary, *, spec: FieldSpec, entries: bool
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
    as_list = spec.type is FieldType.LIST
    item = spec.item if as_list else spec
    as_url = item is not None and item.type in _URL_TYPES
    for path in paths:
        if path.rank != rank:
            rank, held = path.rank, held | stated
        readable = [e for e in entities if e.id not in held and _reads(e, path, vocabulary, entries)]
        reached = list(_reached(readable, path, as_list=as_list, as_url=as_url, earlier=earlier))
        earlier |= {(entity_id, selected.locator) for entity_id, selected in reached}
        stated |= {entity_id for entity_id, selected in reached if isinstance(selected.raw, str | int | float)}
        yield from reached


def _reached(
    entities: Sequence[Typed], path: MappedPath, *, as_list: bool, as_url: bool, earlier: set[tuple[str, str]]
) -> Iterator[tuple[str, Selected]]:
    """What `path` reaches on each entity that no earlier alternative reached."""
    for entity in entities:
        for selected in select(entity.node, path, as_list=as_list, as_url=as_url):
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
    """The entity of a node: its URLs (`entity_urls`), its own URLs (`item_urls`), what identifies it (`identity`), the
    product groups it names (`group_ids`, `variant_of`) and an AggregateOffer's price range (`price_range`)."""
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
        price_range=price_range(typed, vocabulary),
    )


def price_range(typed: Typed, vocabulary: Vocabulary) -> tuple[Decimal, Decimal, str | None] | None:
    """An AggregateOffer's `lowPrice` and `highPrice`, each its one number, when the low is below the high, with its one
    `priceCurrency` (None when it states none or several); None for another node, or one stating no such range."""
    if not any(vocabulary.is_a(t, _AGGREGATE_OFFER) for t in typed.types):
        return None
    low, high = _number(typed.node, _LOW_PRICE), _number(typed.node, _HIGH_PRICE)
    if low is None or high is None or low >= high:  # equal bounds state one price; a low above the high, no range
        return None
    currencies = list(dict.fromkeys(_scalar_texts(typed.node, _CURRENCY)))
    return low, high, currencies[0] if len(currencies) == 1 else None


def _number(node: Node, prop: str) -> Decimal | None:
    """The one finite number `prop` states on the node (a JSON number, or text of one with a `.` decimal point)."""
    texts = list(dict.fromkeys(_scalar_texts(node, prop)))
    if len(texts) != 1:
        return None
    try:
        number = Decimal(texts[0])
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


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
