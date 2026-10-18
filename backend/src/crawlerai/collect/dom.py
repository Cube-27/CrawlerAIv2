"""The structural DOM collector (extraction spec; the §22 candidate "generic structural DOM
collectors", label-value pairs, admitted by the owner on 2026-10-16): values a detail page shows in HTML structures
whose meaning the HTML Standard defines, for pages whose structured data leaves fields without candidates.

- **Label-value pairs.** In the page's main region (the `main` element, else the one `role="main"` landmark, else the
  one `article`, else the body) outside its tangential content, dialogs and media fallback: a table row of exactly two
  cells, the first its header (HTML Standard §4.9: a `th`, or a `td` heading its row); a description list's terms with
  their descriptions (§4.4.9: groups of `dt` then `dd`, each group optionally wrapped in a `div`); an element that
  starts with a label and a colon, the value being the text after it or the one element holding it; and sibling
  containers of one shape (two or more) that each hold a label element then a value element. A label names a field
  when its words are one of the field's labels (`collect.labels`: its name, the schema.org property its path names,
  its description and the synonyms role S drafted for the schema), never words from a list in code (C4). Lines and
  sibling pairs repeat for the items a page lists besides its own (related products, variants), so a field they give
  several values reads none from them; an identifier field that pairs of any kind give two values reads none.
- **Other items.** Values held by other items than the page's own are not read: schema.org microdata's related and
  similar items and reviews, and sibling blocks that each link to one other document (a list of cards). Nor is an
  identifier inside a hyperlink to another document, which names that document's item.
- **Typed values.** A money field's or a checked identifier's value the main region shows once, read with the item
  layer's spotting (`collect.items.spot`): the text an element holds itself that the field's normalizer parses, not
  struck through (`s`, `del`), not set apart, shown; for a checked identifier (a GS1 or ISO 2108 check digit), also
  the value of a pair whose label names no field. Several distinct values read none. An identifier without a check
  digit (sku, mpn) is read only next to one of its labels.
- **The main image.** The first image of the page's main region (the `main` element, else the one `role="main"`
  landmark, WAI-ARIA 1.2; else the document's one `article`, §4.3.2), outside the region's tangential content
  (`nav`, `header`, `footer`, `aside`, §4.3), its dialogs (`dialog`, roles `dialog` and `alertdialog`) and the
  fallback content of media elements (§4.8), shown by the cleaned text's rules, whose source is not inline `data:`
  (RFC 2397). A decorative image (an empty `alt`, §4.8.4.4; roles `none` and `presentation`, WAI-ARIA 1.2) is not
  it, and neither is a link card's: an image whose nearest block holding a hyperlink holds no other image, and whose
  hyperlinks lead to one other document, illustrates that document (a teaser of another product, a promotion). It
  fills an `image_url` field whose path names schema.org `image`.

A value must be shown on the page (`VisibleIndex`). Every candidate is the page's, like an Open Graph value, and
independent; it goes through normalization and resolution like any other (no trust of its own). Listing schemas are
skipped: a page-level pair says nothing of one row.
"""

import mimetypes
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from selectolax.lexbor import LexborNode

from crawlerai.collect.base import PAGE, CollectResult
from crawlerai.collect.items.spot import is_typed, spots
from crawlerai.collect.labels import Words, field_labels, properties, words
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import NAMESPACES, candidate
from crawlerai.content.dom import tokens
from crawlerai.content.page import ParsedPage, node_xpath
from crawlerai.content.text import CELLS, shown
from crawlerai.normalize.base import Context
from crawlerai.normalize.dispatch import equality_key
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# HTML Standard §4.3: sectioning content of a region that is not its main content (navigation, headers, footers and
# content tangential to it).
_TANGENTIAL = frozenset({"nav", "header", "footer", "aside"})
# HTML Standard §4.11.4 (`dialog`) and WAI-ARIA 1.2 §5.4 (roles `dialog`, `alertdialog`): a window apart from the
# page's content, such as a drawer or a modal, whose images are its own, not the main content's. A closed `dialog` is
# not rendered at all (`content.text.shown`); an open one or a dialog role is still apart.
_DIALOG_ROLES = frozenset({"dialog", "alertdialog"})
# HTML Standard §4.8.7 (`object`), §4.8.9 (`video`, `audio`), §4.12.5 (`canvas`): their children are fallback content,
# shown only where the element itself cannot be.
_MEDIA = frozenset({"video", "audio", "object", "canvas"})
# WAI-ARIA 1.2 §5.4: roles `none` and `presentation` remove an element's meaning; for an image, it is decorative.
_PRESENTATIONAL = frozenset({"none", "presentation"})
# RFC 6838 top-level type `image`, by the standard library's built-in extension map (no system registry, so every
# platform reads the same table).
_MEDIA_TYPES = mimetypes.MimeTypes()
# schema.org `Thing.image`: the property an image field's path names.
_IMAGE = "image"
# RFC 2397: a `data:` URL carries its content inline; it addresses no image resource.
_INLINE = "data:"
# A label's end: a colon (U+003A, or the fullwidth U+FF1A that CJK text writes) after optional white space.
_COLON = re.compile(r"\s*[:\uff1a]")

# The structures a pair is read from: rows and description lists (HTML Standard §4.9, §4.4.9), `Label: value` lines,
# and sibling containers of one shape.
_TABLE, _LINE, _SIBLINGS = "table", "line", "siblings"
_REPEATING = (_LINE, _SIBLINGS)
# HTML Standard §4.9 (tables) and §4.4.9 (description lists): the elements whose rows and groups `_pairs` reads itself.
_TABULAR = frozenset({"table", "thead", "tbody", "tfoot", "tr", "dl"})
# Sibling containers repeat from two on.
_MIN_REPEATS = 2
# The typed fields read without a label: dates and datetimes have sources of their own.
_SPOTTED_TYPES = frozenset({FieldType.MONEY, FieldType.IDENTIFIER})
# The longest text a typed value is spotted in: an amount or an identifier is short, a longer text is prose around one.
_SPOT_LENGTH = 64
# HTML Standard §4.5.4 `s` and §4.7.2 `del`: text that is no longer accurate or was removed is no current value.
_STRUCK = frozenset({"s", "del"})
# schema.org properties whose values are other things than the page's item: `review`, `isRelatedTo`, `isSimilarTo`,
# as an `itemprop` token names them, bare or as an IRI in either namespace; and a Review item, whose `itemtype` URL ends
# with `/Review` (HTML Standard §5.4: microdata).
OTHER_ITEMS = ",".join(
    (
        *(
            f'[itemprop~="{namespace}{prop}"]'
            for prop in ("review", "isRelatedTo", "isSimilarTo")
            for namespace in ("", *NAMESPACES)
        ),
        '[itemtype$="/Review"]',
    )
)


class DomCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        if schema.page_kind != "detail" or page.json_body:
            return CollectResult(entities=(), candidates=())
        diagnostics: list[str] = []
        candidates = []
        content = _Content.of(page, ctx)
        labels = field_labels(schema)
        pairs = content.pairs(page) if content is not None else []
        unlabelled = [pair for pair in pairs if words(pair[0]) not in labels]
        for name, raw, xpath, read in (
            *_pairs_found(pairs, labels, schema, content),
            *_typed_found(page, schema, ctx, content, unlabelled),
            *_image_found(page, schema, ctx),
        ):
            locator = format_locator("dom", xpath)
            found = candidate(name, schema.fields[name], PAGE, "dom", raw, locator, ctx, diagnostics, read=read or None)
            if found is not None:
                candidates.append(found)
        return CollectResult(entities=(), candidates=tuple(candidates), diagnostics=tuple(diagnostics))


# A hyperlink (HTML Standard §4.6.1: an `a` element with an `href` attribute).
A_HREF = "a[href]"

# A field, the raw value, the XPath of the element it came from, and what the field reads of it when that is not the
# raw value (a list field's items).
Found = tuple[str, str, str, list[str] | None]
Pair = tuple[str, LexborNode, str, str]  # a label's text, the element holding its value, its text and the kind


@dataclass(frozen=True, slots=True)
class _Content:
    """The page's content region with the elements of it whose values are not the page's own: those `apart` (its
    tangential content, dialogs and media fallback, and other items' content, `_other_items`), and those `linked`
    (the content of a hyperlink to another document, which names that document's item)."""

    region: LexborNode
    apart: frozenset[int]
    linked: frozenset[int]

    @classmethod
    def of(cls, page: ParsedPage, ctx: Context) -> "_Content | None":
        region = content_region(page)
        if region is None:
            return None
        links = _Links.of(region, ctx)
        apart = _apart_ids(region) | _inside(_other_items(region, links))
        return cls(region, apart, _inside(a for a in region.css(A_HREF) if links.of_block(a)))

    def links_out(self, element: LexborNode) -> bool:
        """Whether the element is or holds content of a hyperlink to another document."""
        return element.mem_id in self.linked or any(a.mem_id in self.linked for a in element.css(A_HREF))

    def pairs(self, page: ParsedPage) -> list[Pair]:
        """The region's label-value pairs whose value is shown and is not set apart."""
        return [
            pair
            for pair in _pairs(self.region)
            if pair[2] and pair[1].mem_id not in self.apart and _shown(page, pair[1], pair[2])
        ]


def _shown(page: ParsedPage, value: LexborNode, text: str) -> bool:
    """Whether a pair's value is shown: its text, or, for a value that is a list, each of its items (a list's items are
    lines of their own, so the text joining them is on none)."""
    visible = page.visible_values.visible
    return visible(text) or (bool(items := list_items(value)) and all(map(visible, items)))


def _pairs_found(
    pairs: Sequence[Pair], labels: Mapping[Words, Sequence[str]], schema: SchemaDef, content: "_Content | None"
) -> Iterator[Found]:
    # A value's wrappers read it too: of the elements giving a field the same value, the innermost (last in document
    # order) is its place.
    found: dict[tuple[str, str], LexborNode] = {}
    kinds: dict[tuple[str, str], set[str]] = {}
    for label, value, raw, kind in pairs:
        for name in labels.get(words(label), ()):
            if schema.fields[name].type is FieldType.IDENTIFIER and content is not None and content.links_out(value):
                continue
            found[(name, raw)] = value
            kinds.setdefault((name, kind), set()).add(raw)
    for (name, raw), value in found.items():
        if _unambiguous(name, raw, kinds, schema.fields[name]):
            yield (
                name,
                raw,
                node_xpath(value),
                list_items(value) if schema.fields[name].type is FieldType.LIST else None,
            )


def _unambiguous(name: str, raw: str, kinds: Mapping[tuple[str, str], set[str]], spec: FieldSpec) -> bool:
    """Whether a field's pair value is the page's own. Lines and sibling pairs repeat for the items a page lists
    besides its own (related products, variants): a field they give several values is ambiguous there, while rows and
    description lists are the page's own. An identifier identifies one thing (GS1, ISO 2108, a seller's sku), so a
    field that pairs of any kind give two identifiers reads neither: one may be another item's."""
    if spec.type is FieldType.IDENTIFIER:
        return all(given <= {raw} for (field, _), given in kinds.items() if field == name)
    if raw in kinds.get((name, _TABLE), ()):
        return True
    return all(len(kinds[(name, kind)]) == 1 for kind in _REPEATING if raw in kinds.get((name, kind), ()))


def content_region(page: ParsedPage) -> LexborNode | None:
    """The page's main content: its main region, else the document body."""
    return _main_region(page) or page.tree.body


def _own_text(node: LexborNode) -> str:
    """The text the element holds itself, not its children's: a struck or hidden child's amount is not the parent's."""
    return " ".join(node.text(deep=False, separator=" ").split())


def _text(node: LexborNode) -> str:
    return " ".join(node.text(deep=True, separator=" ").split())


# HTML Standard §4.4.5-§4.4.7: the list elements, whose `li` children are their items.
_LISTS = frozenset({"ul", "ol", "menu"})


def list_items(element: LexborNode) -> list[str]:
    """The text of each item of the lists an element is or holds (HTML Standard §4.4.5-§4.4.8: the `li` children of a
    `ul`, `ol` or `menu`), in document order. A list inside an item is part of that item, not a list of its own."""
    lists = [element] if element.tag in _LISTS else element.css(",".join(_LISTS))
    items = [
        item
        for lst in lists
        if not any(ancestor.tag == "li" for ancestor in _up_to(lst, element))
        for item in _children(lst)
        if item.tag == "li"
    ]
    return [text for text in map(_text, items) if text]


def _up_to(node: LexborNode, top: LexborNode) -> Iterator[LexborNode]:
    """The ancestors of `node` below `top`."""
    parent = node.parent if node != top else None
    while parent is not None and parent != top:
        yield parent
        parent = parent.parent


def _pairs(region: LexborNode) -> Iterator[Pair]:
    """Each label with its value, in the two-column structures of the region: table rows of two cells, description
    list groups, elements that start with `Label:` and sibling containers of one shape that each hold a label element
    and a value element."""
    for row in region.css("tr"):
        cells = _children(row)
        if len(cells) == 2 and all(cell.tag in CELLS for cell in cells):
            yield _text(cells[0]), cells[1], _text(cells[1]), _TABLE
    for described in region.css("dl"):
        for term, description in _groups(described):
            yield _text(term), description, _text(description), _TABLE
    for element in (region, *region.css("*")):
        yield from _colon_line(element)
        yield from _repeated_pairs(element)


def _groups(dl: LexborNode) -> Iterator[tuple[LexborNode, LexborNode]]:
    """HTML Standard §4.4.9: a `dl` is groups of one or more terms followed by one or more descriptions; every term of a
    group labels every description of it. A `div` child of a `dl` wraps one group."""
    terms: list[LexborNode] = []
    described = False
    items = (grand for child in _children(dl) for grand in (_children(child) if child.tag == "div" else (child,)))
    for item in items:
        if item.tag == "dt":
            if described:
                terms, described = [], False
            terms.append(item)
        elif item.tag == "dd":
            described = True
            yield from ((term, item) for term in terms)


def _colon_line(element: LexborNode) -> Iterator[Pair]:
    """An element whose text starts with a label and a colon, in its first non-blank child (`Model: <span>x</span>`, a
    label element and a value element, `<b>Model:</b> x`): the label is the text before the colon, the value what
    follows it. A value with another colon in it holds another label (`Brand: x SKU: y`): nothing is read."""
    first = None if _structured(element) else next((c for c in element.iter(include_text=True) if _text(c)), None)
    if first is None or _structured(first):
        return
    lead, full = _text(first), _text(element)
    cut = _COLON.search(full)
    if cut is None or cut.start() > len(lead):
        return
    value = _line_value(element, first, full[cut.end() :].strip(), lead[cut.end() :].strip())
    if value is not None and not _COLON.search(value[1]):
        yield full[: cut.start()], value[0], value[1], _LINE


def _line_value(element: LexborNode, first: LexborNode, rest: str, inner: str) -> tuple[LexborNode, str] | None:
    """The element holding a line's value and the value: what follows the colon in the first child when it holds some
    (`inner`), else the rest of the element (`rest`), held by its one other child when that child fills it."""
    if inner:
        return (first if first.is_element_node else element), inner
    if not rest:
        return None
    others = [child for child in _children(element) if child != first]
    return (others[0] if len(others) == 1 and _text(others[0]) == rest else element), rest


def _structured(element: LexborNode) -> bool:
    """Whether the element is part of a table or a description list, whose rows and groups are read as such."""
    parent = element.parent
    return element.is_element_node and (element.tag in _TABULAR or (parent is not None and parent.tag == "dl"))


def _repeated_pairs(parent: LexborNode) -> Iterator[Pair]:
    """Sibling containers of one shape (the same tag, each with two children of the same tags) hold a label and its
    value: the first child labels the second. One such container is no repetition, so no structure."""
    shapes: dict[tuple[str, ...], list[LexborNode]] = {}
    for child in () if _structured(parent) else _children(parent):
        parts = _children(child)
        if len(parts) == 2:
            shapes.setdefault((child.tag or "", parts[0].tag or "", parts[1].tag or ""), []).append(child)
    for group in shapes.values():
        if len(group) >= _MIN_REPEATS:
            for container in group:
                label, value = _children(container)
                yield _text(label), value, _text(value), _SIBLINGS


def _children(node: LexborNode) -> list[LexborNode]:
    return [child for child in node.iter(include_text=False) if child.is_element_node]


def _typed_found(
    page: ParsedPage, schema: SchemaDef, ctx: Context, content: _Content | None, unlabelled: Sequence[Pair]
) -> Iterator[Found]:
    """A money or checked-identifier field's value the main region shows once: the elements whose own text the field's
    normalizer parses (`items.spot`), current (not struck), not set apart and shown; for an identifier, also the value
    of a pair whose label names no field (`EAN: <digits>`), outside hyperlinks to other documents. A check digit (GS1,
    ISO 2108) makes the syntax checkable; an identifier without one needs a label (`_pairs_found`). Several distinct
    values are ambiguous (a price among related products' prices): nothing is read."""
    fields = [n for n, spec in schema.fields.items() if is_typed(spec) and spec.type in _SPOTTED_TYPES]
    if not fields or content is None or _main_region(page) is None:
        return
    shorts = _short_texts(content.region, _apart_ids(content.region, _STRUCK) | content.apart)
    for name in fields:
        spec = schema.fields[name]
        texts = _identifier_texts(shorts, unlabelled, content) if spec.type is FieldType.IDENTIFIER else shorts
        if (one := _one_value(texts, spec, ctx)) is not None:
            yield name, *one, None


def _one_value(texts: Sequence[tuple[LexborNode, str]], spec: FieldSpec, ctx: Context) -> tuple[str, str] | None:
    """The raw value and the XPath of its element when the shown texts the field's normalizer parses give one value."""
    hits = [(element, spot) for element, text in texts for spot in spots(text, spec, ctx, "", "") if shown(element)]
    if len({equality_key(spot.normalized.value, spec) for _, spot in hits}) != 1:
        return None
    return hits[0][1].raw, node_xpath(hits[0][0])


def _identifier_texts(
    shorts: Sequence[tuple[LexborNode, str]], unlabelled: Sequence[Pair], content: _Content
) -> list[tuple[LexborNode, str]]:
    """The short texts and the short values of pairs no field's label names, neither in nor holding hyperlinks to
    other documents."""
    values = ((value, raw) for _, value, raw, _ in unlabelled if len(raw) <= _SPOT_LENGTH)
    return [(element, text) for element, text in (*shorts, *values) if not content.links_out(element)]


def _short_texts(region: LexborNode, excluded: frozenset[int]) -> list[tuple[LexborNode, str]]:
    """The region's elements with the short text each holds itself, outside the `excluded` elements."""
    texts = ((element, _own_text(element)) for element in (region, *region.css("*")) if element.mem_id not in excluded)
    return [(element, text) for element, text in texts if text and len(text) <= _SPOT_LENGTH]


def _inside(roots: Iterable[LexborNode]) -> frozenset[int]:
    """The elements `roots` are and hold."""
    return frozenset(inside.mem_id for root in roots for inside in (root, *root.css("*")))


def _other_items(region: LexborNode, links: "_Links") -> Iterator[LexborNode]:
    """The region's elements holding items besides the page's own: what schema.org microdata marks as a related or
    similar item or a review (`itemprop` `isRelatedTo`, `isSimilarTo`, `review`; a `Review` item), and sibling blocks
    of one tag (two or more) that each link to one other document, a different one each: a list of other documents'
    cards (related products), whose values are theirs (HTML Standard §4.6.1: a hyperlink leads to its document)."""
    yield from region.css(OTHER_ITEMS)
    for parent in (region, *region.css("*")):
        groups: dict[str, list[LexborNode]] = {}
        for child in _children(parent):
            groups.setdefault(child.tag or "", []).append(child)
        for group in groups.values():
            if len(group) >= _MIN_REPEATS and _cards(group, links):
                yield from group


def _cards(group: Sequence[LexborNode], links: "_Links") -> bool:
    targets = [links.of_block(block) for block in group]
    return all(len(t) == 1 for t in targets) and len(set().union(*targets)) == len(group)


def _apart_ids(region: LexborNode, extra: frozenset[str] = frozenset()) -> frozenset[int]:
    """The elements in the region's tangential content, in a dialog or a media element's fallback, or inside one of
    the `extra` tags."""
    selector = ",".join(
        (*_TANGENTIAL, *_MEDIA, *extra, "dialog", *(f'[role~="{role}"]' for role in sorted(_DIALOG_ROLES)))
    )
    return frozenset(inside.mem_id for root in region.css(selector) for inside in (root, *root.css("*")))


def _image_found(page: ParsedPage, schema: SchemaDef, ctx: Context) -> Iterator[Found]:
    fields = [n for n, spec in schema.fields.items() if spec.type is FieldType.IMAGE_URL and _IMAGE in properties(spec)]
    region = _main_region(page) if fields else None
    found = _main_image(region, ctx) if region is not None else None
    if found is None:
        return
    image, source = found
    xpath = node_xpath(image)
    for name in fields:
        yield name, source, xpath, None


def _main_region(page: ParsedPage) -> LexborNode | None:
    """The `main` element, else the `role="main"` landmark, else the one `article`; none when the page has several."""
    for selector in ("main", '[role="main"]', "article"):
        found = page.tree.css(selector)
        if found:
            return found[0] if len(found) == 1 else None
    return None


def _main_image(region: LexborNode, ctx: Context) -> tuple[LexborNode, str] | None:
    links = _Links.of(region, ctx)
    apart = _apart_ids(region)
    for image in region.css("img"):
        source = image_source(image.attributes)
        if (
            source is not None
            and shown(image)
            and not decorative(image.attributes)
            and image.mem_id not in apart
            and not _link_card(image, region, links)
        ):
            return image, source
    return None


def image_source(attributes: Mapping[str, str | None]) -> str | None:
    """An `img` element's `src`, else the URL of its first `srcset` candidate (HTML Standard §4.8.4.3: a URL, then
    optional descriptors, candidates separated by commas); an inline `data:` URL is none."""
    sources = [attributes.get("src") or "", *(attributes.get("srcset") or "").split()[:1]]
    for source in (s.strip().rstrip(",") for s in sources):
        if source and not source.lower().startswith(_INLINE):
            return source
    return None


def decorative(attributes: Mapping[str, str | None]) -> bool:
    """Whether an `img` is decorative: an empty `alt` (HTML Standard §4.8.4.4), or roles `none`/`presentation`."""
    return attributes.get("alt") == "" or not _PRESENTATIONAL.isdisjoint(tokens(attributes.get("role")))


def _link_card(image: LexborNode, region: LexborNode, links: "_Links") -> bool:
    """Whether the nearest block around the image that holds a hyperlink to another document holds no other image and
    leads to one document only: the card of that document, whose image is the document's, not this page's entity."""
    node: LexborNode | None = image.parent
    while node is not None and node != region:
        if len(node.css("img")) > 1:
            return False
        targets = links.of_block(node)
        if targets:
            return len(targets) == 1
        node = node.parent
    return False


@dataclass(frozen=True, slots=True)
class _Links:
    """The other document each hyperlink of a region leads to (HTML Standard §4.6.1: an `a` with `href`), by element:
    canonical (`canonical_url`: http(s), without the fragment), other than the page itself and other than images (a
    larger copy)."""

    targets: Mapping[int, str]

    @classmethod
    def of(cls, region: LexborNode, ctx: Context) -> "_Links":
        here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
        base = ctx.base_url or ctx.page_url
        found = {a.mem_id: canonical_url(a.attributes.get("href") or "", base) for a in region.css(A_HREF)}
        return cls({key: t for key, t in found.items() if t is not None and t != here and not is_image_url(t)})

    def of_block(self, block: LexborNode) -> set[str]:
        """The other documents the block's hyperlinks lead to, the block's own included when it is one."""
        return {self.targets[a.mem_id] for a in (block, *block.css(A_HREF)) if a.mem_id in self.targets}


def is_image_url(url: str) -> bool:
    """Whether the URL's path names an image file (RFC 6838: the top-level type `image`, by its extension)."""
    media_type, _ = _MEDIA_TYPES.guess_type(urlsplit(url).path)
    return media_type is not None and media_type.startswith("image/")
