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
  (`nav`, `header`, `footer`, `aside`, §4.3), whose source is not inline `data:` (RFC 2397). It fills an
  `image_url` field whose path names schema.org `image`.

A value must be shown on the page (`VisibleIndex`). Every candidate is the page's, like an Open Graph value, and
independent; it goes through normalization and resolution like any other (no trust of its own). Listing schemas are
skipped: a page-level pair says nothing of one row.
"""

import re
import unicodedata
from collections.abc import Iterator, Mapping, Sequence

from selectolax.lexbor import LexborNode

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import named_property, parse_paths
from crawlerai.content.page import ParsedPage, node_xpath
from crawlerai.normalize.base import Context
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# HTML Standard §4.9.9-10: the cells of a table row.
_CELLS = frozenset({"th", "td"})
# HTML Standard §4.3: sectioning content of a region that is not its main content (navigation, headers, footers and
# content tangential to it).
_TANGENTIAL = frozenset({"nav", "header", "footer", "aside"})
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
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> tuple[Candidate, ...]:
        if schema.page_kind != "detail":
            return ()
        pairs = _pair_candidates(page, _labels(schema), schema, ctx)
        return (*pairs, *_image_candidates(page, schema, ctx))


def _labels(schema: SchemaDef) -> dict[Words, list[str]]:
    """The fields each label's words name. A list or an object holds several values, and a table cell is one."""
    labels: dict[Words, list[str]] = {}
    for name, spec in schema.fields.items():
        if spec.type in (FieldType.LIST, FieldType.OBJECT):
            continue
        paths = parse_paths(spec.schema_org) if spec.schema_org is not None else ()
        for form in dict.fromkeys([words(name), *(words(named_property(p)) for p in paths)]):
            labels.setdefault(form, []).append(name)
    return labels


def words(text: str) -> Words:
    """`text`'s words, case-folded, after Unicode NFKC (UAX #15): "Review count:", `review_count` and `reviewCount`
    are all ("review", "count")."""
    spaced = _CAMEL.sub(" ", unicodedata.normalize("NFKC", text))
    return tuple(word.casefold() for word in _WORD.findall(spaced))


def _pair_candidates(
    page: ParsedPage, labels: Mapping[Words, Sequence[str]], schema: SchemaDef, ctx: Context
) -> Iterator[Candidate]:
    seen: set[tuple[str, str]] = set()
    for label, value in _pairs(page):
        fields = labels.get(words(label.text(deep=True, separator=" ")))
        raw = value.text(deep=True, separator=" ").strip() if fields else ""
        if not raw or not page.visible_values.visible(raw):
            continue
        xpath = node_xpath(value)
        for name in fields or ():
            if (name, xpath) not in seen:
                seen.add((name, xpath))
                yield _candidate(name, schema.fields[name], raw, xpath, ctx)


def _pairs(page: ParsedPage) -> Iterator[tuple[LexborNode, LexborNode]]:
    """Each label with its value: table rows of two cells, then description list groups, in document order."""
    for row in page.tree.css("tr"):
        cells = _children(row)
        if len(cells) == 2 and all(cell.tag in _CELLS for cell in cells):
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


def _image_candidates(page: ParsedPage, schema: SchemaDef, ctx: Context) -> Iterator[Candidate]:
    fields = [name for name, spec in schema.fields.items() if _names_image(spec)]
    region = _main_region(page) if fields else None
    found = None if region is None else _main_image(region)
    if found is not None:
        image, source = found
        for name in fields:
            yield _candidate(name, schema.fields[name], source, node_xpath(image), ctx)


def _names_image(spec: FieldSpec) -> bool:
    paths = parse_paths(spec.schema_org) if spec.schema_org is not None else ()
    return spec.type is FieldType.IMAGE_URL and any(named_property(p) == _IMAGE for p in paths)


def _main_region(page: ParsedPage) -> LexborNode | None:
    """The `main` element, else the `role="main"` landmark, else the one `article`; none when the page has several."""
    for selector in ("main", '[role="main"]', "article"):
        found = page.tree.css(selector)
        if found:
            return found[0] if len(found) == 1 else None
    return None


def _main_image(region: LexborNode) -> tuple[LexborNode, str] | None:
    for image in region.css("img"):
        source = _source(image)
        if source is not None and not _tangential(image, region):
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


def _tangential(node: LexborNode, region: LexborNode) -> bool:
    ancestor = node.parent
    while ancestor is not None and ancestor != region:
        if ancestor.tag in _TANGENTIAL:
            return True
        ancestor = ancestor.parent
    return False


def _candidate(name: str, spec: FieldSpec, raw: str, xpath: str, ctx: Context) -> Candidate:
    return Candidate(
        field=name,
        entity_id=PAGE,
        source_kind="dom",
        raw=raw,
        normalized=normalize(raw, spec, ctx),
        locator=format_locator("dom", xpath),
        independent=True,
    )
