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


def is_hyperlink(element: HtmlElement) -> bool:
    return element.tag in _LINKS and element.get("href") is not None


def _tokens(value: str | None) -> tuple[str, ...]:
    """HTML Standard §2.3.2: a set of space-separated tokens (`class`, `role`)."""
    return tuple((value or "").split())


def item_blocks(root: HtmlElement) -> tuple[HtmlElement, ...]:
    """The largest group of repeated items in the document `root`, in document order; empty when it shows none."""
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
    largest: list[HtmlElement] = []
    for (parent, _), nodes in siblings.items():
        for items in _shapes(nodes):
            if len(items) >= max(MIN_ITEMS, len(largest) + 1) and not _chrome(parent):
                largest = items
    return tuple(largest)


def _shapes(nodes: list[HtmlElement]) -> list[list[HtmlElement]]:
    """Sibling elements of one tag, grouped by shape, each group in document order: those carrying every class token
    that more than half of them carry are one group, and each other class list is a group of its own."""
    tokens = [frozenset(_tokens(node.get("class"))) for node in nodes]
    counts = Counter(token for own in tokens for token in own)
    shared = frozenset(token for token, count in counts.items() if 2 * count > len(nodes))
    groups: dict[object, list[HtmlElement]] = {}
    for node, own in zip(nodes, tokens, strict=True):
        groups.setdefault(shared if shared and shared <= own else own, []).append(node)
    return list(groups.values())


def _content(root: HtmlElement) -> HtmlElement:
    main = next(root.iter("main"), None)
    if main is not None:
        return main
    body = root.find("body")
    return root if body is None else body


def _chrome(node: HtmlElement | None) -> bool:
    """Whether `node` is in the site's chrome. Chrome above the main landmark holds no content, so it is not asked."""
    while node is not None and node.tag != "main":
        if node.tag in _CHROME_TAGS or not _CHROME_ROLES.isdisjoint(_tokens(node.get("role"))):
            return True
        node = node.getparent()
    return False
