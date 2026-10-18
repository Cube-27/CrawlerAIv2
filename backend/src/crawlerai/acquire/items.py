"""The repeated item structure of a page (ARCHITECTURE §8.6): the blocks a listing shows its items in, read from the
document's structure only (C2, C4). `classify` reads it to tell a listing whose grid has not loaded (SPEC-02 §4.3),
and the `markdown` format to keep a listing's items (SPEC-07 §4.5).

Items are at least `MIN_ITEMS` sibling elements of one shape that each are or hold a hyperlink (HTML Standard §4.6).
One template renders them all, so siblings of one tag share the class tokens the template writes; a template may add a
token of an item's own (its position, a state), so a shape is the tag and the tokens most of those siblings carry, not
the whole class list. They are looked for in the page's content: its main landmark
(§4.4.14), else its body, without the site's chrome.
"""

from collections import Counter
from typing import Final

from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

# A listing shows at least this many items; resolution takes as many top-level entities for a listing's rows (SPEC-05
# §4.7, `resolve.listing.MIN_TOP_LEVEL_ROWS`): fewer is what a detail page's related items look like.
MIN_ITEMS: Final = 3
# A site's chrome, not its content: the HTML Standard's navigation, header, footer and aside elements (§4.3, §4.4) and
# the WAI-ARIA 1.2 landmark roles they map to (§5.3.4).
_CHROME_TAGS: Final = frozenset({"nav", "header", "footer", "aside"})
_CHROME_ROLES: Final = frozenset({"navigation", "banner", "contentinfo", "complementary"})
# HTML Standard §4.6.1: `a` and `area` elements with an `href` are hyperlinks.
_LINKS: Final = ("a", "area")
_VISIBLE_TEXT: Final = "descendant-or-self::text()[not(ancestor::script or ancestor::style or ancestor::template)]"


def lxml_root(text: str) -> HtmlElement:
    """The lxml tree of a decoded document. lxml refuses a str that carries an XML encoding declaration, so it reads
    the text again as UTF-8 with the encoding named, and the declaration is ignored: both parsers read the same
    characters."""
    try:
        return lxml_html.document_fromstring(text.encode("utf-8"), parser=lxml_html.HTMLParser(encoding="utf-8"))
    except etree.ParserError:  # an empty or all-whitespace document has no root element
        return lxml_html.Element("html")


def is_hyperlink(element: HtmlElement) -> bool:
    return element.tag in _LINKS and element.get("href") is not None


def _tokens(value: str | None) -> tuple[str, ...]:
    """HTML Standard §2.3.2: a set of space-separated tokens (`class`, `role`)."""
    return tuple((value or "").split())


def item_blocks(root: HtmlElement) -> tuple[HtmlElement, ...]:
    """The group of repeated items in the document `root` with the most structural evidence of being the page's items
    (`_evidence`, then size), in document order; empty when it shows none."""
    return max(item_groups(root), key=lambda items: (_evidence(items), len(items)), default=())


def shown_items(root: HtmlElement) -> int:
    """How many of the page's items (`item_blocks`) show more than their link: an image, or text in two or more runs
    (`_evidence`). A list of bare links (a tag cloud, related posts, a pager) shows a link and its label only."""
    return sum(1 for item in item_blocks(root) if _holds_image(item) or _holds_several_texts(item))


def _evidence(items: tuple[HtmlElement, ...]) -> int:
    """How much the items show beyond their link: each item scores one for holding an image and one for holding text
    in two or more runs (a label and something besides it: a title and a price, a name and a description). A bare tag
    cloud or pager, whose items are a link and its label, scores nothing however many they are, so it cannot outrank a
    grid of items that show more (D-1277)."""
    return sum(_holds_image(item) + _holds_several_texts(item) for item in items)


def _holds_image(item: HtmlElement) -> bool:
    return next(item.iter("img", "picture"), None) is not None


def _holds_several_texts(item: HtmlElement) -> bool:
    """Whether the item holds visible text in two or more runs: script data, style sheets and templates are never
    rendered (HTML Standard §15.3.1), so their text is no run."""
    return sum(1 for text in item.xpath(_VISIBLE_TEXT) if text.strip()) >= 2


def item_groups(root: HtmlElement) -> tuple[tuple[HtmlElement, ...], ...]:
    """Every group of repeated items in the document `root` (at least `MIN_ITEMS` siblings of one shape, outside the
    chrome), each in document order. The browser's paging driver ranks them by rendered area (`crawl.paging`)."""
    content = _content(root)
    # One walk up from each hyperlink gathers the link-holding elements by parent and tag; an element already
    # gathered had its ancestors gathered with it, so each element is gathered once.
    siblings: dict[tuple[HtmlElement, object], list[HtmlElement]] = {}
    gathered: set[HtmlElement] = set()
    for node in filter(is_hyperlink, content.iter(*_LINKS)):
        while node is not content and node not in gathered and (parent := node.getparent()) is not None:
            gathered.add(node)
            siblings.setdefault((parent, node.tag), []).append(node)
            node = parent
    return tuple(
        tuple(items)
        for (parent, _), nodes in siblings.items()
        for items in _shapes(nodes)
        if len(items) >= MIN_ITEMS and not in_chrome(parent)
    )


def _shapes(nodes: list[HtmlElement]) -> list[list[HtmlElement]]:
    """Sibling elements of one tag, grouped by shape, each group in document order: those carrying every class token
    that more than half of them carry are one group, and each other class list is a group of its own."""
    tokens = [frozenset(_tokens(node.get("class"))) for node in nodes]
    counts = Counter(token for own in tokens for token in own)
    shared = frozenset(token for token, count in counts.items() if 2 * count > len(nodes))
    groups: dict[frozenset[str], list[HtmlElement]] = {}
    for node, own in zip(nodes, tokens, strict=True):
        groups.setdefault(shared if shared and shared <= own else own, []).append(node)
    return list(groups.values())


def _content(root: HtmlElement) -> HtmlElement:
    main = next(root.iter("main"), None)
    if main is not None:
        return main
    body = root.find("body")
    return root if body is None else body


def in_chrome(node: HtmlElement | None) -> bool:
    """Whether `node` is in the site's chrome. Chrome above the main landmark holds no content, so it is not asked."""
    while node is not None and node.tag != "main":
        if node.tag in _CHROME_TAGS or not _CHROME_ROLES.isdisjoint(_tokens(node.get("role"))):
            return True
        node = node.getparent()
    return False
