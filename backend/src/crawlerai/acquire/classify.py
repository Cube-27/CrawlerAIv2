"""Block classification from HTTP status and document structure only (SPEC-02 §4.3, ARCHITECTURE §7.1, INV-24).

No body text is ever compared with a string: challenge pages served with 200 are not detected by content (that
would need vendor strings, C3/C4). They mostly present as shells and get a browser retry. An error page served with
200 that has text enough not to be a shell is told by its shape instead (a terminal document): a small document with
a message and nothing that links, loads, runs or embeds anything, which no site's page is.

A page fetched as a listing is a shell too when nothing on it lists items (`_lists_items`): its grid loads by script
after the page (an XHR), so the browser may render what HTTP did not. Only the HTTP rung passes the page kind: the
browser is the last rung, and its page is extracted whatever its links.
"""

from lxml import etree
from lxml import html as lxml_html
from selectolax.lexbor import LexborHTMLParser

from crawlerai.acquire.items import item_blocks
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
# Structured data a listing's rows are read from without its grid (SPEC-05 §4.7): microdata items (HTML Standard
# §5.2), and JSON-LD script data blocks (W3C JSON-LD 1.1 §7.3) whose media type, before parameters and in any case
# (RFC 9110 §8.3.1), is `_JSON_LD`.
_MICRODATA = "[itemscope]"
_JSON_LD = "application/ld+json"
# JSON script data blocks (RFC 8259 §11, the `application/json` media type): the page's script state, which the
# js_state collector reads rows from (SPEC-05 §4.5).
_JSON = "application/json"


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
    tree = LexborHTMLParser(body)
    # Read before the shell rule strips scripts from the tree.
    terminal = len(body) <= TERMINAL_MAX_BYTES and tree.css_first(_PAGE_PARTS) is None
    structured = page_kind == "listing" and _has_structured_data(tree)
    if _is_shell(tree):
        return "shell"
    if terminal:
        return "blocked"
    if page_kind == "listing" and not structured and not _lists_items(body):
        return "shell"
    return "ok"


def _is_html(headers: HeaderList) -> bool:
    # RFC 9110 §8.3: the media type is the Content-Type value before any parameters, case-insensitive.
    types = [value.split(";", 1)[0].strip().lower() for name, value in headers if name.lower() == "content-type"]
    return not types or types[-1] in _HTML_TYPES


def _is_shell(tree: LexborHTMLParser) -> bool:
    tree.strip_tags(_INVISIBLE)
    # Links first: most pages have enough of them, and then the body text need not be built.
    if len(tree.css("a[href]")) >= _SHELL_MAX_LINKS:
        return False
    # Visible text is counted in non-whitespace characters: HTML rendering collapses whitespace, and counting
    # only non-whitespace makes the count independent of how text nodes are joined.
    text = tree.body.text() if tree.body is not None else ""
    return len("".join(text.split())) < _SHELL_MAX_TEXT_CHARS


def _has_structured_data(tree: LexborHTMLParser) -> bool:
    if tree.css_first(_MICRODATA) is not None:
        return True
    types = (script.attributes.get("type") or "" for script in tree.css("script[type]"))
    return any(type_.split(";", 1)[0].strip().lower() in (_JSON_LD, _JSON) for type_ in types)


def _lists_items(body: bytes) -> bool:
    """Whether the page shows repeated items (`item_blocks`); lxml reads it, as the markdown format does."""
    try:
        root = lxml_html.document_fromstring(body)
    except (etree.ParserError, ValueError):  # a document lxml finds no element in
        return False
    return bool(item_blocks(root))
