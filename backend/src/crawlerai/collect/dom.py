"""The structural DOM collector (SPEC-05 §4.5, ARCHITECTURE §8.1; the §22 candidate "generic structural DOM
collectors", label-value pairs, admitted by the owner on 2026-10-16): values a detail page shows in HTML structures
whose meaning the HTML Standard defines, for pages whose structured data leaves fields without candidates.

- **Label-value pairs.** In the page's main region (the `main` element, else the one `role="main"` landmark, else the
  one `article`, else the body) outside its tangential content, dialogs and media fallback: a table row of exactly two
  cells, the first its header (HTML Standard §4.9: a `th`, or a `td` heading its row); a description list's terms with
  their descriptions (§4.4.9: groups of `dt` then `dd`, each group optionally wrapped in a `div`); an element that
  starts with a label and a colon, the value being the text after it or the one element holding it; and sibling
  containers of one shape (two or more) that each hold a label element then a value element. A label names a field
  when its words are the field's name (`review_count`: "Review count") or the words of the schema.org property its
  `schema_org` path names (`reviewCount`, `brand` for `Product.brand.name`), lower-cased (`named_property`). These
  words come from the schema and the pinned schema.org vocabulary it is validated against, never from a list (C4), so
  only labels written in those words match. Lines and sibling pairs repeat for the items a page lists besides its own
  (related products, variants), so a field they give several values reads none from them.
- **Typed values.** A money field's or a checked identifier's value the main region shows once, read with the item
  layer's spotting (`collect.items.spot`): the text an element holds itself that the field's normalizer parses, not
  struck through (`s`, `del`), not set apart, shown. Several distinct values read none.
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
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from selectolax.lexbor import LexborNode

from crawlerai.collect.base import PAGE, CollectResult
from crawlerai.collect.items.spot import is_typed, spots
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, named_property, parse_paths
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
# Words of a label or a name: runs of letters and digits; a lower-case letter or digit followed by a capital starts a
# new word, as schema.org's lowerCamelCase property names join theirs (schema.org, "Data model": naming conventions).
_WORD = re.compile(r"[^\W_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
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

Words = tuple[str, ...]


class DomCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        if schema.page_kind != "detail" or page.json_body:
            return CollectResult(entities=(), candidates=())
        diagnostics: list[str] = []
        candidates = []
        for name, raw, xpath in (
            *_pairs_found(page, schema),
            *_typed_found(page, schema, ctx),
            *_image_found(page, schema, ctx),
        ):
            locator = format_locator("dom", xpath)
            found = candidate(name, schema.fields[name], PAGE, "dom", raw, locator, ctx, diagnostics)
            if found is not None:
                candidates.append(found)
        return CollectResult(entities=(), candidates=tuple(candidates), diagnostics=tuple(diagnostics))


def _labels(schema: SchemaDef) -> dict[Words, list[str]]:
    """The fields each label's words name. A list or an object holds several values, and a table cell is one."""
    labels: dict[Words, list[str]] = {}
    for name, spec in schema.fields.items():
        if spec.type in (FieldType.LIST, FieldType.OBJECT):
            continue
        for form in dict.fromkeys([words(name), *map(words, _properties(spec))]):
            labels.setdefault(form, []).append(name)
    return labels


def _properties(spec: FieldSpec) -> list[str]:
    """The schema.org properties a field's paths name (`named_property`)."""
    return [named_property(p) for p in parse_paths(spec.schema_org)] if spec.schema_org is not None else []


def words(text: str) -> Words:
    """`text`'s words, case-folded, after Unicode NFKC (UAX #15): "Review count:", `review_count` and `reviewCount`
    are all ("review", "count")."""
    spaced = _CAMEL.sub(" ", unicodedata.normalize("NFKC", text))
    return tuple(word.casefold() for word in _WORD.findall(spaced))


Found = tuple[str, str, str]  # a field, the raw value, the XPath of the element it came from


def _pairs_found(page: ParsedPage, schema: SchemaDef) -> Iterator[Found]:
    labels: Mapping[Words, Sequence[str]] = _labels(schema)
    region = _content(page)
    if region is None:
        return
    # A value's wrappers read it too: of the elements giving a field the same value, the innermost (last in document
    # order) is its place.
    apart = _apart_ids(region)
    found: dict[tuple[str, str], LexborNode] = {}
    kinds: dict[tuple[str, str], set[str]] = {}
    for label, value, raw, kind in _pairs(region):
        fields = labels.get(words(label))
        if not fields or not raw or value.mem_id in apart or not page.visible_values.visible(raw):
            continue
        for name in fields:
            found[(name, raw)] = value
            kinds.setdefault((name, kind), set()).add(raw)
    for (name, raw), value in found.items():
        # Lines and sibling pairs repeat for the items a page lists besides its own (related products, variants): a
        # field they give several values is ambiguous there. Rows and description lists are the page's own.
        stated = raw in kinds.get((name, _TABLE), ())
        if stated or all(len(kinds[(name, kind)]) == 1 for kind in _REPEATING if raw in kinds.get((name, kind), ())):
            yield name, raw, node_xpath(value)


def _content(page: ParsedPage) -> LexborNode | None:
    """The page's main content: its main region, else the document body."""
    return _main_region(page) or page.tree.body


def _own_text(node: LexborNode) -> str:
    """The text the element holds itself, not its children's: a struck or hidden child's amount is not the parent's."""
    return " ".join(node.text(deep=False, separator=" ").split())


def _text(node: LexborNode) -> str:
    return " ".join(node.text(deep=True, separator=" ").split())


Pair = tuple[str, LexborNode, str, str]  # a label's text, the element holding its value, its text and the kind


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


def _typed_found(page: ParsedPage, schema: SchemaDef, ctx: Context) -> Iterator[Found]:
    """A money or checked-identifier field's value the main region shows once: the elements whose own text the field's
    normalizer parses (`items.spot`), current (not struck), not set apart and shown. Several distinct values are
    ambiguous (a price among related products' prices): nothing is read."""
    fields = [n for n, spec in schema.fields.items() if is_typed(spec) and spec.type in _SPOTTED_TYPES]
    region = _main_region(page) if fields else None
    if region is None:
        return
    texts = _short_texts(region)
    for name in fields:
        spec = schema.fields[name]
        hits = [(element, spot) for element, text in texts for spot in spots(text, spec, ctx, "", "") if shown(element)]
        if len({equality_key(spot.normalized.value, spec) for _, spot in hits}) == 1:
            yield name, hits[0][1].raw, node_xpath(hits[0][0])


def _short_texts(region: LexborNode) -> list[tuple[LexborNode, str]]:
    """The region's elements with the short text each holds itself, outside struck text and set-apart content."""
    excluded = _apart_ids(region, _STRUCK)
    texts = ((element, _own_text(element)) for element in (region, *region.css("*")) if element.mem_id not in excluded)
    return [(element, text) for element, text in texts if text and len(text) <= _SPOT_LENGTH]


def _apart_ids(region: LexborNode, extra: frozenset[str] = frozenset()) -> frozenset[int]:
    """The elements in the region's tangential content, in a dialog or a media element's fallback, or inside one of
    the `extra` tags."""
    selector = ",".join(
        (*_TANGENTIAL, *_MEDIA, *extra, "dialog", *(f'[role~="{role}"]' for role in sorted(_DIALOG_ROLES)))
    )
    return frozenset(inside.mem_id for root in region.css(selector) for inside in (root, *root.css("*")))


def _image_found(page: ParsedPage, schema: SchemaDef, ctx: Context) -> Iterator[Found]:
    fields = [
        n for n, spec in schema.fields.items() if spec.type is FieldType.IMAGE_URL and _IMAGE in _properties(spec)
    ]
    region = _main_region(page) if fields else None
    found = _main_image(region, ctx) if region is not None else None
    if found is None:
        return
    image, source = found
    xpath = node_xpath(image)
    for name in fields:
        yield name, source, xpath


def _main_region(page: ParsedPage) -> LexborNode | None:
    """The `main` element, else the `role="main"` landmark, else the one `article`; none when the page has several."""
    for selector in ("main", '[role="main"]', "article"):
        found = page.tree.css(selector)
        if found:
            return found[0] if len(found) == 1 else None
    return None


def _main_image(region: LexborNode, ctx: Context) -> tuple[LexborNode, str] | None:
    here = canonical_url(ctx.page_url, None) if ctx.page_url is not None else None
    base = ctx.base_url or ctx.page_url
    apart = _apart_ids(region)
    for image in region.css("img"):
        source = image_source(image.attributes)
        if (
            source is not None
            and shown(image)
            and not decorative(image.attributes)
            and image.mem_id not in apart
            and not _link_card(image, region, here, base)
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


def _link_card(image: LexborNode, region: LexborNode, here: str | None, base: str | None) -> bool:
    """Whether the nearest block around the image that holds a hyperlink to another document holds no other image and
    leads to one document only: the card of that document, whose image is the document's, not this page's entity."""
    node: LexborNode | None = image.parent
    while node is not None and node != region:
        if len(node.css("img")) > 1:
            return False
        targets = _link_targets(node, here, base)
        if targets:
            return len(targets) == 1
        node = node.parent
    return False


def _link_targets(block: LexborNode, here: str | None, base: str | None) -> set[str]:
    """The other documents the block's hyperlinks (HTML Standard §4.6.1: an `a` with `href`) lead to, canonical
    (`canonical_url`: http(s), without the fragment), other than this page and other than images (a larger copy)."""
    anchors = block.css("a[href]")
    if block.tag == "a" and "href" in block.attributes:
        anchors.append(block)
    targets = {canonical_url(anchor.attributes.get("href") or "", base) for anchor in anchors}
    return {t for t in targets if t is not None and t != here and not is_image_url(t)}


def is_image_url(url: str) -> bool:
    """Whether the URL's path names an image file (RFC 6838: the top-level type `image`, by its extension)."""
    media_type, _ = _MEDIA_TYPES.guess_type(urlsplit(url).path)
    return media_type is not None and media_type.startswith("image/")
