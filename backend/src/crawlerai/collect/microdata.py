"""The microdata collector (extraction spec): HTML Standard microdata, and RDFa Lite 1.1 read by the
same rules.

An item is an element with `itemscope` (microdata) or `typeof` (RDFa Lite); an element with both is one item. Its
properties are the elements with `property` whose nearest enclosing item it is, the elements with `itemprop` whose
nearest enclosing `itemscope` element it is (HTML Standard, "Associating names with items": microdata knows no
`typeof`, so an RDFa-only item between them does not take a microdata name), and the elements `itemref` names. A
property element that is itself an item is a nested item: its value is that item, and it is the holder's child. An
item that is no property is a top-level item, so DOM nesting alone makes no parent.

Names are schema.org terms only where schema.org is the vocabulary: a microdata item typed with a schema.org
`itemtype` (an untyped item is in no vocabulary), RDFa terms under a schema.org `vocab`, the `schema:` prefix of the
RDFa initial context, and full schema.org IRIs anywhere. An item with a schema.org type from the vocabulary file is an
entity. Entities and locators are addressed as `microdata:<xpath>` in the page's selectolax tree.
"""

import re
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import count
from urllib.parse import urljoin, urlsplit

from pydantic import JsonValue
from selectolax.lexbor import LexborNode

from crawlerai.collect.base import CollectResult, descends
from crawlerai.collect.property_values import labelled_values
from crawlerai.collect.schema_org_map import (
    NAMESPACES,
    Typed,
    Value,
    Vocabulary,
    entity,
    field_candidates,
    schema_term,
)
from crawlerai.content.page import ParsedPage
from crawlerai.content.text import xpath_step
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

# RDFa Core 1.1 initial context (W3C): the prefix `schema` names http://schema.org/.
_RDFA_PREFIX = "schema:"
_RDFA_VOCABULARIES = frozenset(n.rstrip("/") for n in NAMESPACES)
# HTML Standard, microdata "Values": the attribute that holds the property value of these elements; a URL attribute
# that is absent gives the empty string.
_URL_ATTRIBUTES = {
    **dict.fromkeys(("audio", "embed", "iframe", "img", "source", "track", "video"), "src"),
    **dict.fromkeys(("a", "area", "link"), "href"),
    "object": "data",
}
_VALUE_ATTRIBUTES = {"meta": "content", "data": "value", "meter": "value"}
# RDFa Core 1.1 §7.5 step 11, as RDFa Lite 1.1 uses it: `content` gives a literal, then (HTML+RDFa 1.1 §3.1) a
# `time` element's `datetime`; `resource`, `href` and `src` give an IRI; otherwise the text content.
_RDFA_IRI_ATTRIBUTES = ("resource", "href", "src")
# Infra Standard: ASCII whitespace is tab, LF, FF, CR and space.
_ASCII_WHITESPACE = re.compile(r"[\t\n\f\r ]+")


@dataclass(eq=False, slots=True)
class _Element:
    node: LexborNode
    xpath: str
    order: int  # tree order
    rdfa_schema: bool  # whether the RDFa `vocab` in scope is schema.org
    enclosing: "_Element | None"  # the nearest item element it is inside, not counting itself
    scope: "_Element | None"  # the nearest `itemscope` element it is inside, not counting itself: its microdata item


@dataclass(frozen=True, slots=True)
class _Property:
    names: tuple[str, ...]  # schema.org property names, in the order written
    element: _Element
    rdfa: bool  # named by RDFa `property`, not microdata `itemprop`


@dataclass(eq=False, slots=True)
class _Item:
    element: _Element
    types: tuple[str, ...]  # schema.org types from the vocabulary, most specific first
    in_schema: bool  # whether its microdata names are schema.org terms
    node_id: str | None
    properties: list[_Property] = field(default_factory=list)
    holders: list["_Item"] = field(default_factory=list)  # the items it is a property value of

    @property
    def id(self) -> str:
        return f"microdata:{self.element.xpath}"


@dataclass
class _Document:
    items: dict[str, _Item] = field(default_factory=dict)  # by element xpath, in tree order
    elements: list[_Element] = field(default_factory=list)  # every element with `itemprop` or `property`
    # The same elements by the xpath of their microdata item element ("" for none), in tree order.
    by_enclosing: defaultdict[str, list[_Element]] = field(default_factory=lambda: defaultdict(list))
    by_html_id: dict[str, _Element] = field(default_factory=dict)  # the first element with each `id`
    raws: dict[str, JsonValue] = field(default_factory=dict)  # each item's JSON object, built once


@dataclass(frozen=True, slots=True)
class _Node:
    """An item as `schema_org_map` reads it."""

    item: _Item
    document: _Document

    @property
    def node_id(self) -> str | None:
        return self.item.node_id

    def values(self, prop: str) -> Sequence[Value]:
        return [self._value(p) for p in self.item.properties if prop in p.names]

    def _value(self, prop: _Property) -> Value:
        locator = f"microdata:{prop.element.xpath}"
        nested = self.document.items.get(prop.element.xpath)
        if nested is not None:
            return Value(_raw(nested, self.document), locator, _Node(nested, self.document))
        return Value(_scalar(prop), locator, url=_is_url(prop))


@dataclass(frozen=True, slots=True)
class MicrodataCollector:
    vocabulary: Vocabulary

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        document = self._read(page, ctx)
        entities = [item for item in document.items.values() if item.types]
        parents, vias = _parents(entities)
        typed = [Typed(item.id, item.types, _Node(item, document)) for item in entities]
        diagnostics: list[str] = []
        candidates = (
            *field_candidates(
                typed, schema, ctx, vocabulary=self.vocabulary, source_kind="microdata", diagnostics=diagnostics
            ),
            *labelled_values(typed, schema, ctx, source_kind="microdata", diagnostics=diagnostics),
        )
        return CollectResult(
            entities=tuple(entity(t, ctx, self.vocabulary, parent=parents[t.id], via=vias[t.id]) for t in typed),
            candidates=tuple(candidates),
            diagnostics=tuple(diagnostics),
        )

    def _read(self, page: ParsedPage, ctx: Context) -> _Document:
        document = _Document()
        root = page.tree.root
        if root is None:
            return document
        for element in _walk(root):
            attributes = element.node.attributes
            if (html_id := attributes.get("id")) is not None:
                document.by_html_id.setdefault(html_id, element)
            if "itemprop" in attributes or "property" in attributes:
                document.elements.append(element)
                document.by_enclosing[_xpath(element.scope)].append(element)
            if "itemscope" in attributes or "typeof" in attributes:
                document.items[element.xpath] = self._item(element, ctx)
        for element in document.elements:
            _add_properties(element, document)
        for item in document.items.values():
            _add_referenced(item, document)
            item.properties.sort(key=lambda p: p.element.order)
        return document

    def _item(self, element: _Element, ctx: Context) -> _Item:
        attributes = element.node.attributes
        microdata = [n for t in _tokens(attributes.get("itemtype")) if (n := schema_term(t)) is not None]
        rdfa = [n for t in _tokens(attributes.get("typeof")) if (n := _rdfa_term(t, element.rdfa_schema)) is not None]
        written_id = attributes.get("itemid") if "itemscope" in attributes else None
        return _Item(
            element=element,
            types=self.vocabulary.specific_first([*microdata, *rdfa]),
            in_schema=bool(microdata),
            node_id=_resolve(written_id or attributes.get("resource"), ctx),
        )


def property_scalars(page: ParsedPage, prop: str) -> Iterator[str]:
    """The values of the schema.org property `prop` written on elements of the page, in tree order, by the names rules
    of the module docstring: a microdata `itemprop` in an item with a schema.org `itemtype` or as a full IRI, an RDFa
    `property` under a schema.org `vocab`, as `schema:` or as a full IRI. Properties added through `itemref` are not
    read: this reads what the page states, not which item holds it."""
    root = page.tree.root
    if root is None:
        return
    for element in _walk(root):
        attributes = element.node.attributes
        in_schema = _typed_in_schema(element.scope)
        if prop in (_microdata_term(t, in_schema) for t in _tokens(attributes.get("itemprop"))):
            yield _microdata_text(element.node)
        if prop in (_rdfa_term(t, element.rdfa_schema) for t in _tokens(attributes.get("property"))):
            yield _rdfa_text(element.node)


def _typed_in_schema(item: _Element | None) -> bool:
    """Whether the item element has a schema.org `itemtype`, so its microdata names are schema.org terms."""
    attributes = item.node.attributes if item is not None else {}
    return any(schema_term(t) is not None for t in _tokens(attributes.get("itemtype")))


def _walk(root: LexborNode) -> Iterator[_Element]:
    """Every element in tree order, with its XPath, its RDFa vocabulary scope and its nearest enclosing item. Explicit
    stack, not recursion: document depth is not bounded by the interpreter's recursion limit."""
    order = count()
    stack: list[tuple[LexborNode, str, bool, _Element | None, _Element | None]] = [
        (root, "/" + xpath_step(root.tag or "", 1), False, None, None)
    ]
    while stack:
        node, xpath, rdfa_schema, enclosing, scope = stack.pop()
        attributes = node.attributes
        if "vocab" in attributes:  # RDFa Core 1.1 §7.5 step 2: `vocab` sets the vocabulary; an empty one clears it
            rdfa_schema = (attributes["vocab"] or "").strip().rstrip("/") in _RDFA_VOCABULARIES
        element = _Element(node, xpath, next(order), rdfa_schema, enclosing, scope)
        yield element
        inner = element if "itemscope" in attributes or "typeof" in attributes else enclosing
        inner_scope = element if "itemscope" in attributes else scope
        children = [(child, f"{xpath}/{step}", rdfa_schema, inner, inner_scope) for child, step in _children(node)]
        stack.extend(reversed(children))


def _children(node: LexborNode) -> list[tuple[LexborNode, str]]:
    counts: dict[str, int] = {}
    children = []
    for child in node.iter():
        if child.is_element_node and child.tag:
            counts[child.tag] = counts.get(child.tag, 0) + 1
            children.append((child, xpath_step(child.tag, counts[child.tag])))
    return children


def _add_properties(element: _Element, document: _Document) -> None:
    """Add `element`'s microdata properties to its microdata item and its RDFa properties to its nearest enclosing
    item."""
    if element.scope is not None:
        _add_microdata(document.items[element.scope.xpath], element, document)
    if element.enclosing is None:
        return
    holder = document.items[element.enclosing.xpath]
    rdfa = tuple(
        n for t in _tokens(element.node.attributes.get("property")) if (n := _rdfa_term(t, element.rdfa_schema))
    )
    if rdfa:
        holder.properties.append(_Property(rdfa, element, rdfa=True))
        _hold(holder, element, document)


def _add_referenced(item: _Item, document: _Document) -> None:
    """HTML Standard, "Associating names with items": the elements `itemref` names, and their descendants that are in
    no other item, are the item's too. Each element is added once."""
    if "itemscope" not in item.element.node.attributes:
        return
    seen = {p.element.xpath for p in item.properties if not p.rdfa}
    for html_id in _tokens(item.element.node.attributes.get("itemref")):
        start = document.by_html_id.get(html_id)
        if start is None:
            continue
        for element in _referenced(start, document):
            if element.xpath not in seen:
                seen.add(element.xpath)
                _add_microdata(item, element, document)


def _referenced(start: _Element, document: _Document) -> Iterator[_Element]:
    """`start` and, unless it is an item, the property elements below it that it shares its enclosing item with."""
    yield start
    if start.xpath in document.items:
        return
    below = start.xpath + "/"
    yield from (e for e in document.by_enclosing[_xpath(start.scope)] if e.xpath.startswith(below))


def _xpath(element: _Element | None) -> str:
    return "" if element is None else element.xpath


def _add_microdata(item: _Item, element: _Element, document: _Document) -> None:
    names = tuple(
        n for t in _tokens(element.node.attributes.get("itemprop")) if (n := _microdata_term(t, item.in_schema))
    )
    if not names or element is item.element:
        return
    item.properties.append(_Property(names, element, rdfa=False))
    _hold(item, element, document)


def _hold(holder: _Item, element: _Element, document: _Document) -> None:
    nested = document.items.get(element.xpath)
    if nested is not None and holder not in nested.holders:
        nested.holders.append(holder)


def _tokens(value: str | None) -> list[str]:
    # HTML Standard: `itemprop`, `itemtype` and `itemref` are unordered sets of unique space-separated tokens, split on
    # ASCII whitespace; RDFa's `typeof` and `property` are split the same way.
    return list(dict.fromkeys(t for t in _ASCII_WHITESPACE.split(value or "") if t))


def _microdata_term(token: str, in_schema: bool) -> str | None:
    # HTML Standard: a property name is an absolute URL or, in a typed item, a name in the item type's vocabulary.
    if ":" in token:
        return schema_term(token)
    return token if in_schema else None


def _rdfa_term(token: str, vocab_is_schema: bool) -> str | None:
    # RDFa Core 1.1 §7.4.3: a term (no `:`) is appended to the vocabulary in scope; a CURIE uses a prefix; anything else
    # is an IRI.
    if token.startswith(_RDFA_PREFIX):
        return token.removeprefix(_RDFA_PREFIX)
    if ":" in token:
        return schema_term(token)
    return token if vocab_is_schema else None


def _resolve(written: str | None, ctx: Context) -> str | None:
    # HTML Standard: `itemid` is a URL, parsed against the document's base; RDFa `resource` is an IRI reference.
    # A blank one names nothing: resolved, it would be the base URL itself.
    written = (written or "").strip()
    if not written:
        return None
    try:
        resolved = written if ctx.base_url is None else urljoin(ctx.base_url, written)
        urlsplit(resolved)
    except ValueError:  # not a URL (an unclosed IPv6 bracket), so it names nothing
        return None
    return resolved


def _scalar(prop: _Property) -> str:
    return _rdfa_text(prop.element.node) if prop.rdfa else _microdata_text(prop.element.node)


def _is_url(prop: _Property) -> bool:
    """Whether the property's value is a URL its element names (`_URL_ATTRIBUTES`; RDFa's IRI attributes), not text."""
    node = prop.element.node
    if not prop.rdfa:
        return (node.tag or "") in _URL_ATTRIBUTES
    attributes = node.attributes
    literal = "content" in attributes or (node.tag == "time" and "datetime" in attributes)
    return not literal and any(a in attributes for a in _RDFA_IRI_ATTRIBUTES)


def _microdata_text(node: LexborNode) -> str:
    """HTML Standard, microdata "Values": a property's value by its element."""
    tag, attributes = node.tag or "", node.attributes
    attribute = _URL_ATTRIBUTES.get(tag) or _VALUE_ATTRIBUTES.get(tag)
    if attribute is not None:
        return attributes.get(attribute) or ""
    if tag == "time" and "datetime" in attributes:
        return attributes["datetime"] or ""
    return node.text(deep=True)


def _rdfa_text(node: LexborNode) -> str:
    attributes = node.attributes
    if "content" in attributes:
        return attributes["content"] or ""
    if node.tag == "time" and "datetime" in attributes:
        return attributes["datetime"] or ""
    iri = next((attributes[a] for a in _RDFA_IRI_ATTRIBUTES if a in attributes), None)
    return iri or node.text(deep=True)


def _raw(item: _Item, document: _Document) -> JsonValue:
    """An item's value as JSON-LD would write it (what the normalizers read): `@type`, `@id`, then each property's
    values, one value bare and several as an array, nested items as objects. Each item appears once in the object, so
    `itemref` cycles and items shared between holders keep it as large as the page."""
    if item.id in document.raws:
        return document.raws[item.id]
    root: dict[str, JsonValue] = {}
    expanded = {item.id}
    pending = [(item, root)]
    while pending:
        current, written = pending.pop()
        pending.extend(_write(current, written, expanded, document))
    document.raws[item.id] = root
    return root


def _write(
    item: _Item, written: dict[str, JsonValue], expanded: set[str], document: _Document
) -> list[tuple[_Item, dict[str, JsonValue]]]:
    """Write `item`'s own members into `written`; the nested items not yet expanded are returned with the empty objects
    that stand for them, to be written next."""
    if item.types:
        written["@type"] = item.types[0] if len(item.types) == 1 else list(item.types)
    if item.node_id is not None:
        written["@id"] = item.node_id
    nested_items: list[tuple[_Item, dict[str, JsonValue]]] = []
    by_name: dict[str, list[JsonValue]] = {}
    for prop in item.properties:
        nested = document.items.get(prop.element.xpath)
        value: JsonValue
        if nested is None:
            value = _scalar(prop)
        elif nested.id in expanded:
            continue
        else:
            expanded.add(nested.id)
            value = {}
            nested_items.append((nested, value))
        for name in prop.names:
            by_name.setdefault(name, []).append(value)
    written.update({name: values[0] if len(values) == 1 else values for name, values in by_name.items()})
    return nested_items


def _parents(entities: Sequence[_Item]) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Each entity's parent, and the parent's property it is under: the nearest entity up its chain of single holders
    (an untyped item in between is skipped), unless that would make a cycle. An item two items hold has no parent."""
    parents: dict[str, str | None] = dict.fromkeys((item.id for item in entities), None)
    vias: dict[str, str | None] = dict.fromkeys(parents, None)
    for item in entities:
        held = _entity_holder(item, parents)
        if held is not None and not descends(held[0].id, item.id, parents):
            parents[item.id] = held[0].id
            vias[item.id] = _via(*held)
    return parents, vias


def _entity_holder(item: _Item, entities: Mapping[str, str | None]) -> tuple[_Item, _Item] | None:
    """The nearest entity up `item`'s chain of single holders, and the item it holds on that chain."""
    seen = {item.id}
    current = item
    while len(current.holders) == 1:
        below, current = current, current.holders[0]
        if current.id in seen:
            return None
        if current.id in entities:
            return current, below
        seen.add(current.id)
    return None


def _via(holder: _Item, held: _Item) -> str | None:
    """The one property name `holder` holds `held` under; an element naming several (`itemprop="a b"`) names none."""
    names = {name for prop in holder.properties if prop.element is held.element for name in prop.names}
    return names.pop() if len(names) == 1 else None
