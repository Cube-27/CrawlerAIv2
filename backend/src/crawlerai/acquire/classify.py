"""Block classification from HTTP status and document structure only (SPEC-02 §4.3, ARCHITECTURE §7.1, INV-24).

No body text is ever compared with a string: challenge pages served with 200 are not detected by content (that
would need vendor strings, C3/C4). They mostly present as shells and get a browser retry. An error page served with
200 that has text enough not to be a shell is told by its shape instead (`_is_terminal`): a small document with a
message and nothing else, which no site's page is.

A page fetched as a listing is a shell too when nothing on it lists items (`_lists_items`): its grid loads by script
after the page (an XHR), so the browser may render what HTTP did not.
"""

from collections import Counter

from selectolax.lexbor import LexborHTMLParser
from selectolax.lexbor import LexborNode as Node

from crawlerai.acquire.types import BlockClass
from crawlerai.db.models import PageKind
from crawlerai.storage.capture_bundle import HeaderList

# RFC 9110 §15.5.5 (404 Not Found), §15.5.11 (410 Gone).
_NOT_FOUND = frozenset({404, 410})
# RFC 9110 §15.5.2 (401), §15.5.4 (403), §15.5.8 (407), §15.6.4 (503); RFC 6585 §4 (429); RFC 7725 §3 (451).
_BLOCKED = frozenset({401, 403, 407, 429, 451, 503})
# HTML Standard: these elements' contents are never rendered as page text (script data, style sheets, fallback
# for script-disabled user agents, inert template contents).
_INVISIBLE = ["script", "style", "noscript", "template"]
# HTML media types (HTML Standard §16.1 text/html; RFC 3236 application/xhtml+xml). A response without a declared
# type is treated as HTML, as browsers sniff it (WHATWG MIME Sniffing §7).
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
# Shell thresholds: unmeasured starting points, to be confirmed on dev (SPEC-02 §4.3, D-0008).
_SHELL_MAX_TEXT_CHARS = 200
_SHELL_MAX_LINKS = 5
# What a page of a site carries and an error stub does not (HTML Standard): hyperlinks (§4.6, `a`/`area` with `href`),
# scripts (§4.12.1), external resources and style sheets (`link`, §4.2.4), embedded content (§4.8) and forms (§4.10).
_PAGE_PARTS = "a[href], area[href], script, link, img, picture, video, audio, iframe, embed, object, svg, canvas, form"
# A terminal document is at most this many bytes: an unmeasured starting point like the shell thresholds, to be
# confirmed on dev (SPEC-02 §4.3, D-0008).
TERMINAL_MAX_BYTES = 1024
# Structured data a listing's rows are read from without its grid (SPEC-05 §4.7): JSON-LD (W3C JSON-LD 1.1 §7.3,
# script data blocks) and microdata items (HTML Standard §5.2).
_STRUCTURED_DATA = 'script[type="application/ld+json"], [itemscope]'
# A site's chrome, not its content: the HTML Standard's navigation, header, footer and aside elements (§4.3, §4.4) and
# the WAI-ARIA 1.2 landmark roles they map to (§5.3.4).
_CHROME = "nav, header, footer, aside, [role=navigation], [role=banner], [role=contentinfo], [role=complementary]"
# A listing lists at least this many items, as resolution takes rows without an ItemList (SPEC-05 §4.7, its
# MIN_TOP_LEVEL_ROWS): fewer is what a detail page's related items look like.
_MIN_ITEMS = 3


def classify(status: int, headers: HeaderList, body: bytes, page_kind: PageKind | None = None) -> BlockClass:
    """The response's block class; `page_kind` is the kind the page is fetched as, when its task names one."""
    if status in _NOT_FOUND:
        return "not_found"
    if status in _BLOCKED:
        return "blocked"
    if status >= 400:
        return "error"
    if not 200 <= status < 300 or not _is_html(headers):
        return "ok"
    if _is_shell(body):
        return "shell"
    if _is_terminal(body):
        return "blocked"
    if page_kind == "listing" and not _lists_items(body):
        return "shell"
    return "ok"


def _is_html(headers: HeaderList) -> bool:
    # RFC 9110 §8.3: the media type is the Content-Type value before any parameters, case-insensitive.
    types = [value.split(";", 1)[0].strip().lower() for name, value in headers if name.lower() == "content-type"]
    return not types or types[-1] in _HTML_TYPES


def _is_shell(body: bytes) -> bool:
    tree = LexborHTMLParser(body)
    tree.strip_tags(_INVISIBLE)
    # Links first: most pages have enough of them, and then the body text need not be built.
    if len(tree.css("a[href]")) >= _SHELL_MAX_LINKS:
        return False
    # Visible text is counted in non-whitespace characters: HTML rendering collapses whitespace, and counting
    # only non-whitespace makes the count independent of how text nodes are joined.
    text = tree.body.text() if tree.body is not None else ""
    return len("".join(text.split())) < _SHELL_MAX_TEXT_CHARS


def _is_terminal(body: bytes) -> bool:
    """A small document that links, loads, runs and embeds nothing: an error message answered as success (an edge's
    refusal, an origin's error stub). The shell rule runs first, so the document has visible text."""
    if len(body) > TERMINAL_MAX_BYTES:
        return False
    return LexborHTMLParser(body).css_first(_PAGE_PARTS) is None


def _lists_items(body: bytes) -> bool:
    """Whether the page lists items: structured data, or a repeated item structure in its content. Items are at least
    `_MIN_ITEMS` siblings of one shape (tag and class list, as one template renders them) that each are or hold a
    hyperlink. Content is the main landmark (HTML Standard §4.4.14), else the body, without the site's chrome."""
    tree = LexborHTMLParser(body)
    if tree.css_first(_STRUCTURED_DATA) is not None:
        return True
    content = tree.css_first("main") or tree.body
    if content is None:
        return False
    # One walk up from each hyperlink counts the link-holding elements by parent and shape; an element already
    # counted had its ancestors counted with it, so every element is counted once.
    shapes: Counter[tuple[Node, str | None, str | None]] = Counter()
    counted: set[Node] = set()
    for link in content.css("a[href]"):
        node = link
        while node != content and node not in counted and (parent := node.parent) is not None:
            counted.add(node)
            shapes[parent, node.tag, node.attributes.get("class")] += 1
            node = parent
    return any(n >= _MIN_ITEMS and not _in_chrome(parent, content) for (parent, _, _), n in shapes.items())


def _in_chrome(node: Node | None, content: Node) -> bool:
    while node is not None and node != content:
        if node.css_matches(_CHROME):
            return True
        node = node.parent
    return False
