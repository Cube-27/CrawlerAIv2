"""The item layer's links: which document a block of a group of repeated items
leads to, its item URL (`collect.items.align`'s module docstring, **item URL**), and whether a block stands for the
page itself. URLs are compared by `normalize.url_key`'s `document_key` and `item_key`, never published so: a block's
item URL publishes as its canonical URL, with the `href` the page writes.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Final
from urllib.parse import urlsplit

from lxml.html import HtmlElement

from crawlerai.acquire.items import Group, hyperlinks, is_hyperlink
from crawlerai.collect.dom_images import is_image_url
from crawlerai.content.dom import tokens
from crawlerai.content.segment import text_path
from crawlerai.normalize.url import canonical_url
from crawlerai.normalize.url_key import DocumentKey, document_key, item_key

# HTML Standard §4.3.6: heading content; WAI-ARIA 1.2 role `heading`.
_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_HEADING_ROLE: Final = "heading"
# A hyperlink's place in its block: its tag path and its parent's rank among those of the block's hyperlinks at that
# path (`_link_places`).
Place = tuple[str, int]
# The kind of document a URL names (`url_kind`): its host, its number of path segments and its first one.
Kind = tuple[str, int, str]
# RFC 3986 §2.3: the unreserved delimiters a path segment's words are written apart with.
_WORD_BREAK: Final = re.compile(r"[-._~]")
# WAI-ARIA 1.2 `aria-current` token: "represents the current page within a set of pages".
_CURRENT_PAGE: Final = "page"


def leads_to(anchor: HtmlElement, link: str, base: str | None) -> bool:
    """Whether the hyperlink leads to the item at `link` (`normalize.url_key.item_key`): to that item, or, for a URL
    without a query, to its document refined with one (RFC 3986 §3.4: a query refines the resource the path names,
    such as a variant a card's picture links to while its button links to the product, as `without_queries` reads a
    block's links)."""
    mine, item = item_key(anchor.get("href") or "", base), item_key(link)
    return mine is not None and item is not None and (mine == item or (not item[1] and mine[0] == item[0]))


def current_page(block: HtmlElement, base: str | None, here: str | None) -> bool:
    """Whether the block stands for the page itself in a set of pages: a hyperlink of it is marked as the current page
    (WAI-ARIA 1.2 `aria-current="page"`), or every one of its hyperlinks leads to this very item, query included
    (`normalize.url_key.item_key`; a same-document `#` reference aside: HTML Standard, navigating to a fragment). A
    listing's items never include the listing, so a group holding such a block lists documents of the page's own kind:
    the other categories, cities or sorts of a link hub, the site's navigation rather than the page's items."""
    anchors = [a for a in hyperlinks(block) if not (a.get("href") or "").strip().startswith("#")]
    if any((a.get("aria-current") or "").strip().lower() == _CURRENT_PAGE for a in anchors):
        return True
    page = item_key(here) if here is not None else None
    return page is not None and bool(anchors) and all(item_key(a.get("href") or "", base) == page for a in anchors)


def _heading_links(block: HtmlElement, sublists: frozenset[HtmlElement]) -> list[HtmlElement]:
    """The block's hyperlinks inside its headings: a heading labels the content it heads (HTML Standard §4.3.6), so
    its link is the item's, not the other documents the block links to (its seller, its employer)."""
    headings = [element for element in block.iter() if isinstance(element.tag, str) and is_heading(element)]
    return [a for heading in headings for a in hyperlinks(heading) if a not in sublists]


def _content_links(
    block: HtmlElement, anchors: Sequence[HtmlElement], base: str | None, spans: Mapping[str, tuple[int, int]]
) -> list[HtmlElement]:
    """The block's hyperlinks to the one document whose hyperlinks hold more than half of the block's shown text (by
    their spans of the cleaned text); none when no document's do."""
    block_span = spans.get(text_path(block))
    if block_span is None:
        return []
    held: Counter[str] = Counter()
    for anchor in anchors:
        target = canonical_url(anchor.get("href") or "", base)
        if target is not None and (span := spans.get(text_path(anchor))) is not None:
            held[target] += span[1] - span[0]
    top = held.most_common(1)
    if not top or 2 * top[0][1] <= block_span[1] - block_span[0]:
        return []
    return [anchor for anchor in anchors if canonical_url(anchor.get("href") or "", base) == top[0][0]]


def is_heading(element: HtmlElement) -> bool:
    return element.tag in _HEADINGS or _HEADING_ROLE in tokens(element.get("role"))


def one_link(
    block: HtmlElement,
    base: str | None,
    here: str | None,
    sublists: frozenset[HtmlElement] = frozenset(),
    spans: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[str, str] | None:
    """The `href` and canonical URL of the one document the block's hyperlinks lead to, those of its
    own lists (`sublists`) aside (module docstring). When they lead to several: the one without a query the others
    refine, else the one its headings link to, else, with the cleaned text's `spans`, the one whose hyperlinks hold
    more than half of the block's shown text (HTML Standard §4.5.1: an `a` element's content labels its link, so the
    link the block's content labels is the block's; a logo's link to the seller labels little). None when there is no
    such one document."""
    anchors = [a for a in hyperlinks(block) if a not in sublists]
    targets = link_targets(anchors, base, here)
    if len(targets) > 1:
        targets = without_queries(targets) or link_targets(_heading_links(block, sublists), base, here)
    if len(targets) != 1 and spans is not None:
        targets = link_targets(_content_links(block, anchors, base, spans), base, here)
    if len(targets) != 1:
        return None
    ((url, (href, _)),) = targets.items()
    return href, url


def item_links(
    group: Group,
    base: str | None,
    here: str | None,
    sublists: frozenset[HtmlElement],
    spans: Mapping[str, tuple[int, int]],
    needed: int,
) -> list[tuple[HtmlElement, tuple[str, str] | None]]:
    """Each block of the group with the `href` and canonical URL of its item (`one_link`), else of the document its
    links at the group's item link place, where `needed` of its blocks link to one document, lead to (`_group_place`);
    None for a block with neither."""
    found = [one_link(block, base, here, sublists, spans) for block in group]
    if all(found):
        return list(zip(group, found, strict=True))
    placed = [_placed_targets(block, base, here, sublists) for block in group]
    shared = _shared_targets(placed)
    own = [_without(block, shared) for block in placed]
    pictured = [_pictured_places(block, base, here, sublists) for block in group]
    place = _group_place(own, pictured, needed)
    for i, targets in enumerate(own):
        at = targets.get(place) if place is not None and found[i] is None else None
        if at is not None and len(at) == 1:
            ((url, href),) = at.items()
            found[i] = href, url
    return list(zip(group, found, strict=True))


def _placed_targets(
    block: HtmlElement, base: str | None, here: str | None, sublists: frozenset[HtmlElement]
) -> dict[Place, dict[str, str]]:
    """The documents the block's hyperlinks lead to (`link_targets`) by the links' places (`_link_places`), each with
    its first `href`, places in document order."""
    placed: dict[Place, dict[str, str]] = {}
    for place, _, targets in _link_places(block, base, here, sublists):
        for url, (href, _) in targets.items():
            placed.setdefault(place, {}).setdefault(url, href)
    return placed


def _link_places(
    block: HtmlElement, base: str | None, here: str | None, sublists: frozenset[HtmlElement]
) -> list[tuple[Place, HtmlElement, dict[str, tuple[str, HtmlElement]]]]:
    """The block's hyperlinks that lead to a document (`link_targets`), those of its own lists aside, each at its
    place, with its targets: its tag path from the block and the rank of its parent among the parents of those
    hyperlinks at that path, in document order. One template writes a card's title, author and "more" links into like
    elements, so their tag paths, positions aside, are one; the order of those elements tells them apart (DEPTA aligns
    the sibling records of a template in order). Links in one element share its place: inline in one run of text (HTML
    Standard §3.2.5.2.5, phrasing content), they are that text's, as the links of a paragraph are. Like elements whose
    links lead to two documents of one kind (`url_kind`) are not one record's title and "more" link but records of
    their own, or one field's values: order does not tell them apart, and those links share their first one's place."""
    parents: dict[str, list[HtmlElement | None]] = {}
    kinds: dict[tuple[str, Kind, str], tuple[int, set[DocumentKey | None]]] = {}
    places: list[tuple[Place, HtmlElement, dict[str, tuple[str, HtmlElement]]]] = []
    for anchor in hyperlinks(block):
        targets = link_targets((anchor,), base, here) if anchor not in sublists else {}
        if not targets:
            continue
        path, parent = tag_path(block, anchor), anchor.getparent()
        seen = parents.setdefault(path, [])
        if parent not in seen:
            seen.append(parent)
        rank = seen.index(parent)
        kinds.setdefault(_kind_at(path, targets), (rank, set()))[1].update(map(document_key, targets))
        places.append(((path, rank), anchor, targets))
    # Like elements whose links lead to two documents of one kind are records, or one field's several values (a
    # column of cards, a book's authors), not one record's fields apart: those links share their first one's place.
    return [
        ((path, _shared(kinds[_kind_at(path, targets)], rank)), anchor, targets)
        for (path, rank), anchor, targets in places
    ]


def _kind_at(path: str, targets: Mapping[str, object]) -> tuple[str, Kind, str]:
    """A link's tag path with the kind (`url_kind`) and leading word (`leading_word`) of the first document it leads
    to: `/p-1` and `/author-1` are one `url_kind` but two kinds of link."""
    first = next(iter(targets))
    return path, url_kind(first), leading_word(first)


def _shared(kind: tuple[int, set[DocumentKey | None]], rank: int) -> int:
    first, documents = kind
    return first if len(documents) > 1 else rank


def leading_word(url: str) -> str:
    """The first word of a URL's first path segment, words split at the unreserved delimiters `-`, `.`, `_` and `~`
    (RFC 3986 §2.3), lowercased: `job` of `/job-7-welder/`, `p` of `/p/7`."""
    segment = next((segment for segment in urlsplit(url).path.split("/") if segment), "")
    return _WORD_BREAK.split(segment, maxsplit=1)[0].lower()


def url_kind(url: str) -> Kind:
    """The kind of document a URL names, as a site lays its items out: its host, its number of path segments and its
    first one when it has more (RFC 3986 §3.3: a path's segments are its hierarchy), so `/p/7` is `/p/3`'s kind,
    while a category page, an article or another site's page is not."""
    split = urlsplit(url)
    segments = [segment for segment in split.path.split("/") if segment]
    return split.netloc, len(segments), segments[0] if len(segments) > 1 else ""


def _shared_targets(placed: Sequence[Mapping[Place, Mapping[str, str]]]) -> frozenset[str]:
    """The documents two or more blocks link to: the template's (a vendor's, an author's, a category's page), as an
    item is listed once (DEPTA: what repeats across records is the template, not a record's data)."""
    counts = Counter(url for block in placed for url in {u for targets in block.values() for u in targets})
    return frozenset(url for url, count in counts.items() if count >= 2)


def _without(placed: Mapping[Place, Mapping[str, str]], shared: frozenset[str]) -> dict[Place, dict[str, str]]:
    """The block's placed targets without the `shared` ones, places left with none dropped."""
    kept = {
        place: {url: href for url, href in targets.items() if url not in shared} for place, targets in placed.items()
    }
    return {place: targets for place, targets in kept.items() if targets}


def _group_place(
    own: Sequence[Mapping[Place, Mapping[str, str]]], pictured: Sequence[set[Place]], needed: int
) -> Place | None:
    """The place (`_link_places`) at which a quorum of the blocks link to one document no other block links to: the
    group's item link place, where the template puts each item's link (DEPTA alignment). Of several, the one that
    comes first in the most blocks, a place whose link holds an image before the others (HTML Standard §4.8.4: an
    `img` in a hyperlink is the link's content; a card pictures its item, not its author or seller); None when no
    place does."""
    counts = Counter(place for block in own for place, targets in block.items() if len(targets) == 1)
    qualified = {place for place, count in counts.items() if count >= needed}
    firsts = Counter(_first_place(block, held, qualified) for block, held in zip(own, pictured, strict=True))
    firsts.pop(None, None)
    return firsts.most_common(1)[0][0] if firsts else None


def _first_place(places: Iterable[Place], pictured: set[Place], qualified: set[Place]) -> Place | None:
    """The block's first qualified place, those whose link holds an image first."""
    return next(
        (place for place in sorted(places, key=lambda place: place not in pictured) if place in qualified), None
    )


def _pictured_places(
    block: HtmlElement, base: str | None, here: str | None, sublists: frozenset[HtmlElement]
) -> set[Place]:
    """The places of the block's hyperlinks that hold an image."""
    return {
        place
        for place, anchor, _ in _link_places(block, base, here, sublists)
        if next(anchor.iter("img"), None) is not None
    }


def tag_path(block: HtmlElement, element: HtmlElement) -> str:
    """The tag path from `block` down to `element` (the align step's place: positions aside)."""
    tags: list[str] = []
    node: HtmlElement | None = element
    while node is not None and node is not block:
        tags.append(str(node.tag))
        node = node.getparent()
    return "/".join(reversed(tags))


def link_targets(
    anchors: Iterable[HtmlElement], base: str | None, here: str | None
) -> dict[str, tuple[str, HtmlElement]]:
    """The documents `anchors` lead to other than this page (in any state of its query: RFC 3986 §3.3, the path names
    the resource, so a pager's or a sort's link is the page again) and image files, each with its first anchor's
    `href` and that anchor."""
    page = document_key(here) if here is not None else None
    targets: dict[str, tuple[str, HtmlElement]] = {}
    for anchor in anchors:
        if not is_hyperlink(anchor):
            continue
        href = anchor.get("href") or ""
        target = canonical_url(href, base)
        if target is not None and document_key(target) != page and not is_image_url(target):
            targets.setdefault(target, (href, anchor))
    return targets


def without_queries(targets: dict[str, tuple[str, HtmlElement]]) -> dict[str, tuple[str, HtmlElement]]:
    """The one target without a query when every other target names its document with a query added
    (`normalize.url_key.document_key`): the block links to one path (RFC 3986 §3.3: the path names the resource within
    its authority), which some of its links refine with a query, such as a variant chosen by a swatch; else
    empty."""
    bare = [url for url in targets if not urlsplit(url).query]
    if len(bare) != 1:
        return {}
    (one,) = bare
    document = document_key(one)
    if all(document_key(url) == document for url in targets):
        return {one: targets[one]}
    return {}
