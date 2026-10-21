"""The repeated item structure of a page, as the document's structure shows it (C2, C4; item layer, owner #67): the
groups of sibling blocks a listing shows its items in. This is the structural walk only; which group is the page's
items is the segment step's (`content.segment`). Acquisition reads the walk before any page is parsed: its shell rule
(`acquire.classify`) and the browser rung's item geometry (`acquire.browser_capture`).

Items are at least `MIN_ITEMS` sibling elements of one shape that each are or hold a hyperlink (HTML Standard §4.6).
One template renders them all, so siblings of one tag share the class tokens the template writes; a template may add a
token of an item's own (its position, a state), so a shape is the tag and the tokens most of those siblings carry, not
the whole class list. They are looked for in the page's content: its main landmark (§4.4.14), else its body, without
the site's chrome.

A list split into sections (a job board's teams, a grid's rows: each section a label and then its items) renders each
section with one template and its items with another: the items of one shape in sibling sections of one shape are one
group, in document order, however few items a section holds, when two or more sections hold them and one holds several
(a part each item shows once, the wrapper of its title or its image, is no section's run).
"""

from collections import Counter
from typing import Final

from lxml import etree
from lxml import html as lxml_html
from lxml.html import HtmlElement

# A listing shows at least this many items; resolution takes as many top-level entities for a listing's rows
# (`resolve.listing.MIN_TOP_LEVEL_ROWS`): fewer is what a detail page's related items look like.
MIN_ITEMS: Final = 3
# A site's chrome, not its content: the HTML Standard's navigation, header, footer and aside elements (§4.3, §4.4)
# and its `search` element, the WAI-ARIA 1.2 landmark roles they map to (§5.3.4; `search` is "a collection of items
# and objects that, as a whole, combine to create a search facility": its filters and facets, not its results), and
# its `menubar` and `menu` roles (§5.3.2, composite widgets "offering a list of choices to the user"): a menu is the
# site's navigation, not a list of the page's items.
_CHROME_TAGS: Final = frozenset({"nav", "header", "footer", "aside", "search"})
_CHROME_ROLES: Final = frozenset({"navigation", "banner", "contentinfo", "complementary", "search", "menubar", "menu"})
# HTML Standard §4.6.1: `a` and `area` elements with an `href` are hyperlinks.
LINKS: Final = ("a", "area")

# A group of repeated items, in document order.
Group = tuple[HtmlElement, ...]


def lxml_root(text: str) -> HtmlElement:
    """The lxml tree of a decoded document. lxml refuses a str that carries an XML encoding declaration, so it reads
    the text again as UTF-8 with the encoding named, and the declaration is ignored: both parsers read the same
    characters."""
    try:
        return lxml_html.document_fromstring(text.encode("utf-8"), parser=lxml_html.HTMLParser(encoding="utf-8"))
    except etree.ParserError:  # an empty or all-whitespace document has no root element
        return lxml_html.Element("html")


def is_hyperlink(element: HtmlElement) -> bool:
    return element.tag in LINKS and element.get("href") is not None


def _tokens(value: str | None) -> tuple[str, ...]:
    """HTML Standard §2.3.2: a set of space-separated tokens (`class`, `role`)."""
    return tuple((value or "").split())


def item_groups(root: HtmlElement) -> tuple[Group, ...]:
    """Every group of repeated items in the document `root` (at least `MIN_ITEMS` siblings of one shape, outside the
    chrome), each in document order."""
    content = content_root(root)
    # One walk up from each hyperlink gathers the link-holding elements by parent and tag; an element already
    # gathered had its ancestors gathered with it, so each element is gathered once.
    siblings: dict[tuple[HtmlElement, object], list[HtmlElement]] = {}
    gathered: set[HtmlElement] = set()
    for node in filter(is_hyperlink, content.iter(*LINKS)):
        while node is not content and node not in gathered and (parent := node.getparent()) is not None:
            gathered.add(node)
            siblings.setdefault((parent, node.tag), []).append(node)
            node = parent
    runs = [items for nodes in siblings.values() for items in _shapes(nodes)]
    return tuple(
        tuple(items) for items in _sectioned(runs) if len(items) >= MIN_ITEMS and not in_chrome(items[0].getparent())
    )


def _sectioned(runs: list[list[HtmlElement]]) -> list[list[HtmlElement]]:
    """The runs of sibling items, those of one shape in sibling sections of one shape joined into one group (module
    docstring) where the first of them was, the others' items as they are."""
    joined = {id(node): group for group in _joined(runs) for node in group}
    groups: list[list[HtmlElement]] = []
    emitted: set[int] = set()
    for run in runs:
        for group in {id(joined[id(node)]): joined[id(node)] for node in run if id(node) in joined}.values():
            if id(group) not in emitted:
                emitted.add(id(group))
                groups.append(group)
        if rest := [node for node in run if id(node) not in joined]:
            groups.append(rest)
    return groups


def _joined(runs: list[list[HtmlElement]]) -> list[list[HtmlElement]]:
    """The groups that join runs of sibling sections (`_sectioned`)."""
    sections: dict[tuple[HtmlElement | None, object, object], list[HtmlElement]] = {}
    for run in runs:
        if (parent := run[0].getparent()) is not None:
            sections.setdefault((parent.getparent(), parent.tag, run[0].tag), []).extend(run)
    return [group for (container, _, _), nodes in sections.items() for group in _section_groups(container, nodes)]


def _section_groups(container: HtmlElement | None, nodes: list[HtmlElement]) -> list[list[HtmlElement]]:
    """The items `nodes` of the sibling sections of `container` (children of one tag) joined by section shape and
    item shape, in document order, where they span sections (`_spans_sections`)."""
    parent_of = {node: parent for node in nodes if (parent := node.getparent()) is not None}
    parents = list(dict.fromkeys(parent_of.values()))
    if container is None or len(parents) < 2:
        return []
    order = {child: i for i, child in enumerate(container)}
    groups: list[list[HtmlElement]] = []
    for shaped in map(set, _shapes(parents)):
        held = sorted((node for node in parent_of if parent_of[node] in shaped), key=lambda n: order[parent_of[n]])
        groups.extend(items for items in _shapes(held) if _spans_sections(items))
    return groups


def _spans_sections(items: list[HtmlElement]) -> bool:
    """Whether the items lie in two or more sections and one section holds several of them."""
    per_section = Counter(item.getparent() for item in items)
    return len(per_section) >= 2 and max(per_section.values()) >= 2


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


def content_root(root: HtmlElement) -> HtmlElement:
    """Where the page's content is: its main landmark (HTML Standard §4.4.14), else its body."""
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


def element_path(element: HtmlElement) -> str:
    """The element's element-index XPath 1.0 path from the document root (`/*[1]/*[2]`): one step per ancestor,
    counting element siblings only (lxml also iterates comments and processing instructions). The browser reads the
    same serialized document, so the path names the same element there (DOM Standard `document.evaluate`)."""
    steps: list[str] = []
    node: HtmlElement | None = element
    while node is not None:
        preceding = sum(1 for sibling in node.itersiblings(preceding=True) if isinstance(sibling.tag, str))
        steps.append(f"*[{1 + preceding}]")
        node = node.getparent()
    return "/" + "/".join(reversed(steps))
