"""Block classification from HTTP status and document structure only (SPEC-02 §4.3, ARCHITECTURE §7.1, INV-24).

No body text is ever compared with a string: challenge pages served with 200 are not detected by content (that
would need vendor strings, C3/C4). They mostly present as shells and get a browser retry. An error or challenge page
served with 200 that has text enough not to be a shell is told by its shape instead: it links nowhere. A site's pages
are connected by hyperlinks (HTML Standard §4.6), so a page without one, whatever scripts, images or forms it holds,
is not one of them.

A page fetched as a listing is a shell too when nothing on it lists items: no repeated items (`_lists_items`) and no
structured data that lists them (`_structured_rows`). Its grid loads by script after the page (an XHR), so the
browser may render what HTTP did not. Only the HTTP rung passes the page kind: the
browser is the last rung, and its page is extracted whatever its links.
"""

import json

from lxml import etree
from lxml import html as lxml_html
from selectolax.lexbor import LexborHTMLParser

from crawlerai.acquire.items import MIN_ITEMS, item_blocks
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
# HTML Standard §4.6.1: `a` and `area` elements with an `href` are hyperlinks.
_HYPERLINKS = "a[href], area[href]"
# Structured data a listing's rows are read from without its grid (SPEC-05 §4.7): as many microdata items (HTML
# Standard §5.2) as a grid's items (`MIN_ITEMS`), or a schema.org ItemList in a JSON-LD script data block (W3C JSON-LD
# 1.1 §7.3) whose media type, before parameters and in any case (RFC 9110 §8.3.1), is `_JSON_LD`.
_MICRODATA = "[itemscope]"
_JSON_LD = "application/ld+json"
_ITEM_LIST = "ItemList"
_TYPE = "@type"  # JSON-LD 1.1 §3.5: a node's type, a string or an array of them


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
    # Read before the shell rule strips script data blocks from the tree.
    structured = page_kind == "listing" and _structured_rows(tree)
    if _is_shell(tree):
        return "shell"
    # After the shell rule: hyperlinks inside a `template` are not in the document, and the rule strips them.
    if tree.css_first(_HYPERLINKS) is None:
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


def _structured_rows(tree: LexborHTMLParser) -> bool:
    if len(tree.css(_MICRODATA)) >= MIN_ITEMS:
        return True
    blocks = (s.text() for s in tree.css("script[type]") if _media_type(s.attributes.get("type")) == _JSON_LD)
    return any(_lists(_json(block)) for block in blocks)


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _json(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:  # a block that is not JSON states nothing
        return None


def _lists(document: object) -> bool:
    """Whether a JSON-LD document holds a node typed ItemList, at any depth (walked with a stack, not recursion)."""
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            types = value.get(_TYPE)
            if types == _ITEM_LIST or (isinstance(types, list) and _ITEM_LIST in types):
                return True
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


def _lists_items(body: bytes) -> bool:
    """Whether the page shows repeated items (`item_blocks`); lxml reads it, as the markdown format does."""
    try:
        root = lxml_html.document_fromstring(body)
    except (etree.ParserError, ValueError):  # a document lxml finds no element in
        return False
    return bool(item_blocks(root))
