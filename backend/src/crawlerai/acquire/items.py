"""The repeated item structure of a page (ARCHITECTURE §8.6): the blocks a listing shows its items in, read from the
document's structure only (C2, C4). `classify` reads it to tell a listing whose grid has not loaded (SPEC-02 §4.3),
and the `markdown` format to keep a listing's items (SPEC-07 §4.5).

Items are at least `MIN_ITEMS` sibling elements of one shape (tag and class list: one template renders them all) that
each are or hold a hyperlink (HTML Standard §4.6). They are looked for in the page's content: its main landmark
(§4.4.14), else its body, without the site's chrome.
"""

from typing import Final

from lxml.html import HtmlElement

# A listing lists at least this many items, as resolution takes rows without an ItemList (SPEC-05 §4.7, its
# MIN_TOP_LEVEL_ROWS): fewer is what a detail page's related items look like.
MIN_ITEMS: Final = 3
# A site's chrome, not its content: the HTML Standard's navigation, header, footer and aside elements (§4.3, §4.4) and
# the WAI-ARIA 1.2 landmark roles they map to (§5.3.4).
_CHROME_TAGS: Final = frozenset({"nav", "header", "footer", "aside"})
_CHROME_ROLES: Final = frozenset({"navigation", "banner", "contentinfo", "complementary"})
# HTML Standard §4.6.1: `a` and `area` elements with an `href` are hyperlinks.
_LINKS: Final = ("a", "area")


def item_blocks(root: HtmlElement) -> tuple[HtmlElement, ...]:
    """The largest group of repeated items in the document `root`, in document order; empty when it shows none."""
    content = _content(root)
    # One walk up from each hyperlink gathers the link-holding elements by parent and shape; an element already
    # gathered had its ancestors gathered with it, so each element is gathered once.
    groups: dict[tuple[HtmlElement, object, str | None], list[HtmlElement]] = {}
    gathered: set[HtmlElement] = set()
    for node in (link for link in content.iter(*_LINKS) if link.get("href") is not None):
        while node is not content and node not in gathered and (parent := node.getparent()) is not None:
            gathered.add(node)
            groups.setdefault((parent, node.tag, node.get("class")), []).append(node)
            node = parent
    largest: list[HtmlElement] = []
    for (parent, _, _), items in groups.items():
        if len(items) >= max(MIN_ITEMS, len(largest) + 1) and not _chrome(parent):
            largest = items
    return tuple(largest)


def _content(root: HtmlElement) -> HtmlElement:
    main = next(root.iter("main"), None)
    if main is not None:
        return main
    body = root.find("body")
    return root if body is None else body


def _chrome(node: HtmlElement | None) -> bool:
    """Whether `node` is in the site's chrome. Chrome above the main landmark holds no content, so it is not asked."""
    while node is not None and node.tag != "main":
        if node.tag in _CHROME_TAGS or node.get("role") in _CHROME_ROLES:
            return True
        node = node.getparent()
    return False
