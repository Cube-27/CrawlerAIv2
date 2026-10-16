"""The structural DOM collector (SPEC-05 §4.5, ARCHITECTURE §8.1; the §22 candidate "generic structural DOM
collectors", label-value pairs, admitted by the owner on 2026-10-16): values a detail page shows in HTML structures
whose meaning the HTML Standard defines, for pages whose structured data leaves fields without candidates.

- **Label-value pairs.** A table row of exactly two cells, the first its header (HTML Standard §4.9: a `th`, or a
  `td` heading its row), and a description list's terms with their descriptions (§4.4.9: groups of `dt` then `dd`,
  each group optionally wrapped in a `div`). A label names a field when its words are the field's name
  (`review_count`: "Review count") or the words of the schema.org property its `schema_org` path names
  (`reviewCount`, `brand` for `Product.brand.name`), lower-cased (`named_property`). These words come from the
  schema and the pinned schema.org vocabulary it is validated against, never from a list (C4), so only labels written
  in those words match.
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
from urllib.parse import urldefrag, urljoin, urlsplit

from selectolax.lexbor import LexborNode

from crawlerai.collect.base import PAGE, CollectResult
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, named_property, parse_paths
from crawlerai.content.page import ParsedPage, node_xpath
from crawlerai.content.text import CELLS, shown
from crawlerai.normalize.base import Context
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
# RFC 9110 §4.2: the schemes whose URIs identify documents a hyperlink leads to.
_WEB_SCHEMES = frozenset({"http", "https"})
# RFC 6838 top-level type `image`, by the standard library's built-in extension map (no system registry, so every
# platform reads the same table).
_MEDIA_TYPES = mimetypes.MimeTypes()
_IMAGE_TYPE = "image/"
# schema.org `Thing.image`: the property an image field's path names.
_IMAGE = "image"
# RFC 2397: a `data:` URL carries its content inline; it addresses no image resource.
_INLINE = "data:"
# Words of a label or a name: runs of letters and digits; a lower-case letter or digit followed by a capital starts a
# new word, as schema.org's lowerCamelCase property names join theirs (schema.org, "Data model": naming conventions).
_WORD = re.compile(r"[^\W_]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

Words = tuple[str, ...]


class DomCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        if schema.page_kind != "detail":
            return CollectResult(entities=(), candidates=())
        diagnostics: list[str] = []
        candidates = []
        for name, raw, xpath in (*_pairs_found(page, schema), *_image_found(page, schema, ctx)):
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
    seen: set[tuple[str, str]] = set()
    for label, value in _pairs(page):
        fields = labels.get(words(label.text(deep=True, separator=" ")))
        if not fields:
            continue
        raw = value.text(deep=True, separator=" ").strip()
        if not raw or not page.visible_values.visible(raw):
            continue
        xpath = node_xpath(value)
        for name in fields:
            if (name, xpath) not in seen:
                seen.add((name, xpath))
                yield name, raw, xpath


def _pairs(page: ParsedPage) -> Iterator[tuple[LexborNode, LexborNode]]:
    """Each label with its value: table rows of two cells, then description list groups, in document order."""
    for row in page.tree.css("tr"):
        cells = _children(row)
        if len(cells) == 2 and all(cell.tag in CELLS for cell in cells):
            yield cells[0], cells[1]
    for described in page.tree.css("dl"):
        yield from _groups(described)


def _groups(dl: LexborNode) -> Iterator[tuple[LexborNode, LexborNode]]:
    """HTML Standard §4.4.9: a `dl` is groups of one or more terms followed by one or more descriptions; every term of a
    group labels every description of it."""
    terms: list[LexborNode] = []
    described = False
    for item in _list_items(dl):
        if item.tag == "dt":
            if described:
                terms, described = [], False
            terms.append(item)
        elif item.tag == "dd":
            described = True
            yield from ((term, item) for term in terms)


def _list_items(dl: LexborNode) -> Iterator[LexborNode]:
    # HTML Standard §4.4.9: a `div` child of a `dl` wraps one group.
    for child in _children(dl):
        yield from _children(child) if child.tag == "div" else (child,)


def _children(node: LexborNode) -> list[LexborNode]:
    return [child for child in node.iter(include_text=False) if child.is_element_node]


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
    for image in region.css("img"):
        source = _source(image)
        if (
            source is not None
            and shown(image)
            and not _decorative(image)
            and not _set_apart(image, region)
            and not _link_card(image, region, ctx)
        ):
            return image, source
    return None


def _source(image: LexborNode) -> str | None:
    """The image's `src`, else the URL of its first `srcset` candidate (HTML Standard §4.8.4.3: a URL, then optional
    descriptors, candidates separated by commas); an inline `data:` URL is none."""
    attributes = image.attributes
    sources = [attributes.get("src") or "", *(attributes.get("srcset") or "").split()[:1]]
    for source in (s.strip().rstrip(",") for s in sources):
        if source and not source.lower().startswith(_INLINE):
            return source
    return None


def _decorative(image: LexborNode) -> bool:
    attributes = image.attributes
    return attributes.get("alt") == "" or not _PRESENTATIONAL.isdisjoint(_roles(image))


def _set_apart(image: LexborNode, region: LexborNode) -> bool:
    """Whether the image is in the region's tangential content, in a dialog, or a media element's fallback."""
    node: LexborNode | None = image.parent
    while node is not None and node != region:
        if node.tag in _TANGENTIAL or node.tag in _MEDIA or _is_dialog(node):
            return True
        node = node.parent
    return False


def _is_dialog(node: LexborNode) -> bool:
    return node.tag == "dialog" or not _DIALOG_ROLES.isdisjoint(_roles(node))


def _roles(node: LexborNode) -> list[str]:
    # WAI-ARIA 1.2 §4.1: `role` is a list of space-separated tokens.
    return (node.attributes.get("role") or "").split()


def _link_card(image: LexborNode, region: LexborNode, ctx: Context) -> bool:
    """Whether the nearest block around the image that holds a hyperlink to another document holds no other image and
    leads to one document only: the card of that document, whose image is the document's, not this page's entity."""
    node: LexborNode | None = image.parent
    while node is not None and node != region:
        if len(node.css("img")) > 1:
            return False
        targets = _link_targets(node, ctx)
        if targets:
            return len(targets) == 1
        node = node.parent
    return False


def _link_targets(block: LexborNode, ctx: Context) -> set[str]:
    """The other documents the block's hyperlinks (HTML Standard §4.6.1: an `a` with `href`) lead to: web URLs,
    without their fragment (RFC 3986 §3.5), other than this page and other than images (a larger copy of one)."""
    anchors = block.css("a[href]")
    if block.tag == "a" and "href" in block.attributes:
        anchors.append(block)
    base = ctx.base_url or ctx.page_url or ""
    here = urldefrag(ctx.page_url or "").url
    targets: set[str] = set()
    for anchor in anchors:
        target = urldefrag(urljoin(base, (anchor.attributes.get("href") or "").strip())).url
        if urlsplit(target).scheme in _WEB_SCHEMES and target != here and not _is_image(target):
            targets.add(target)
    return targets


def _is_image(url: str) -> bool:
    media_type, _ = _MEDIA_TYPES.guess_type(urlsplit(url).path)
    return media_type is not None and media_type.startswith(_IMAGE_TYPE)
