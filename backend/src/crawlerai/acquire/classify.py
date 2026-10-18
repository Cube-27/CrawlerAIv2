"""Block classification from HTTP status and document structure only (SPEC-02 §4.3, ARCHITECTURE §7.1, INV-24).

Every rule reads the body as text, decoded once at acquisition by HTML encoding sniffing
(`storage.capture_bundle.decode_html`): a parser handed the raw bytes of a page in a legacy encoding would read its
attributes as UTF-8 and fail on them.

This module compares no body text with a string: vendor strings are site data (C3/C4), so a vendor's stand-in marker on
a 200 page is read in `acquire.challenge` from the adapter package's signature data, the one exception to INV-24's
structure-only rule. Other challenge pages served with 200 mostly present as shells and get a browser retry. An error or
challenge page served with 200 that has text enough not to be a shell is told by its shape instead: it links nowhere. A
site's pages are connected by hyperlinks (HTML Standard §4.6), so a page without one, whatever scripts, images or forms
it holds, is not one of them. Nor is a document that declares a refresh (it navigates itself on, HTML Standard §4.2.5.3)
and whose hyperlinks all lead to no web page (`mailto:`, `tel:`, RFC 6068, RFC 3966): a stand-in for the page while the
site is busy or checking the client.

A page fetched as a listing is a shell too when nothing on it lists items: no repeated items (`_lists_items`) and no
structured data that lists them (`_structured_rows`). Its grid loads by script after the page (an XHR), so the
browser may render what HTTP did not. Only the HTTP rung passes the page kind: the
browser is the last rung, and its page is extracted whatever its links.
"""

from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from crawlerai.acquire.items import MIN_ITEMS, item_blocks, lxml_root
from crawlerai.acquire.types import BlockClass
from crawlerai.core import json_text
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
# Top-level microdata items (HTML Standard §5.2.2): an item that is no property of another (a breadcrumb's entries,
# a product's offer are).
_MICRODATA = "[itemscope]:not([itemprop])"
_JSON_LD = "application/ld+json"
_ITEM_LIST = "ItemList"
_ENTRIES = "itemListElement"  # schema.org ItemList: the list's entries
_TYPE = "@type"  # JSON-LD 1.1 §3.5: a node's type, a string or an array of them
# D-1206: a refusal a page's own script may lift: 403 (RFC 9110 §15.5.4), 429 (RFC 6585 §4), 503 (RFC 9110 §15.6.4);
# not 401/407, which ask for credentials (RFC 9110 §11.6), nor 451, a legal refusal (RFC 7725).
INTERSTITIAL_STATUS = frozenset({403, 429, 503})
# HTML Standard §4.2.5.3: the `refresh` pragma (`meta http-equiv`, an ASCII case-insensitive keyword), and §7.11.1:
# the `Refresh` header, which the same declarative refresh steps read. Either makes the document navigate on.
_REFRESH = "refresh"
# RFC 9110 §4.2: the URI schemes of resources served over HTTP, which a site's pages are.
_WEB_SCHEMES = ("http", "https")
# HTML Standard §4.12.1: `script` elements; script is the only other way a document navigates itself (the `Location`
# interface, §7.2.4, or a form it submits, §4.10.21).
_SCRIPT = "script"


def classify(status: int, headers: HeaderList, text: str, page_kind: PageKind | None = None) -> BlockClass:
    """The response's block class from its decoded `text`; `page_kind` is the kind the page is fetched as, when its
    task names one."""
    if status in _NOT_FOUND:
        return "not_found"
    if status in _BLOCKED:
        return "blocked"
    if status >= 400:
        return "error"
    if not 200 <= status < 300 or not is_html(headers):
        return "ok"
    tree = LexborHTMLParser(text)
    # Read before the shell rule strips script data blocks from the tree.
    structured = page_kind == "listing" and _structured_rows(tree)
    unstructured = _no_site_page(tree)
    if unstructured is not None:
        return unstructured
    if _refreshes(tree, headers) and not _links_to_web(tree):
        return "blocked"
    if page_kind == "listing" and not structured and not lists_items(text):
        return "shell"
    return "ok"


def lacks_site_structure(text: str) -> bool:
    """Whether an HTML document is no site page by its structure alone, whatever its status: a shell, or a document
    that links nowhere (the rules `classify` applies to a 2xx page)."""
    return _no_site_page(LexborHTMLParser(text)) is not None


def interstitial(status: int, headers: HeaderList, text: str, url: str) -> bool:
    """Whether a refusal at `url` is a document standing in for the page until it navigates on (D-1206, D-1262): its
    status is one a page's own script may lift (`INTERSTITIAL_STATUS`), it can navigate itself (a refresh, or a
    script) and it is no page of the site by structure: it declares a refresh, it lacks site structure
    (`lacks_site_structure`), or no hyperlink leads to another page of its own host. A document with neither a refresh
    nor a script can never replace itself, so waiting on it is time lost."""
    if status not in INTERSTITIAL_STATUS or not is_html(headers):
        return False
    tree = LexborHTMLParser(text)
    refresh = _refreshes(tree, headers)
    if not refresh and tree.css_first(_SCRIPT) is None:
        return False
    return refresh or _no_site_page(tree) is not None or not _links_within(tree, url)


def _refreshes(tree: LexborHTMLParser, headers: HeaderList) -> bool:
    if any(name.lower() == _REFRESH for name, _ in headers):
        return True
    return any((meta.attributes.get("http-equiv") or "").strip().lower() == _REFRESH for meta in tree.css("meta"))


def _links_to_web(tree: LexborHTMLParser) -> bool:
    """Whether a hyperlink leads to a web page: a relative reference, or an absolute one whose scheme is http or https
    (RFC 3986 §4.2, §3.1, the scheme compared case-insensitively). A `mailto:` or `tel:` link starts a message or a
    call, not a page of any site."""
    for link in tree.css(_HYPERLINKS):
        try:
            scheme = urlsplit(link.attributes.get("href") or "").scheme.lower()
        except ValueError:  # an authority no URL parser reads (RFC 3986 §3.2.2) leads nowhere
            continue
        if scheme in ("", *_WEB_SCHEMES):
            return True
    return False


def _links_within(tree: LexborHTMLParser, url: str) -> bool:
    """Whether a hyperlink leads to another page of `url`'s host (RFC 3986 §5 reference resolution, the host compared
    case-insensitively, §6.2.2.1): a site's pages link to each other (HTML Standard §4.6), a page standing in for one
    links nowhere on the site, or only to itself."""
    here = urlsplit(url)
    for link in tree.css(_HYPERLINKS):
        try:
            target = urlsplit(urljoin(url, link.attributes.get("href") or ""))
        except ValueError:  # an authority no URL parser reads (RFC 3986 §3.2.2) leads nowhere
            continue
        elsewhere = (target.path or "/", target.query) != (here.path or "/", here.query)
        if target.scheme in _WEB_SCHEMES and target.hostname == here.hostname and elsewhere:
            return True
    return False


def _no_site_page(tree: LexborHTMLParser) -> BlockClass | None:
    if _is_shell(tree):
        return "shell"
    # After the shell rule: hyperlinks inside a `template` are not in the document, and the rule strips them.
    if tree.css_first(_HYPERLINKS) is None:
        return "blocked"
    return None


def is_html(headers: HeaderList) -> bool:
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
    return len(tree.css(_MICRODATA)) >= MIN_ITEMS or bool(_item_lists(tree))


def structured_entries(tree: LexborHTMLParser) -> int:
    """How many items the page's structured data lists: its top-level microdata items, or the entries of its longest
    JSON-LD ItemList (schema.org `itemListElement`), whichever is more; 0 when it lists none."""
    return max(len(tree.css(_MICRODATA)), *_item_lists(tree), 0)


def _item_lists(tree: LexborHTMLParser) -> list[int]:
    """The entry count of each schema.org ItemList node in the page's JSON-LD script data blocks, at any depth."""
    blocks = (s.text() for s in tree.css("script[type]") if _media_type(s.attributes.get("type")) == _JSON_LD)
    return [count for block in blocks for count in _lists(_json(block))]


def _media_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _json(text: str) -> object:
    try:
        return json_text.parse(text)
    except ValueError:  # a block that is not JSON states nothing
        return None


def _lists(document: object) -> list[int]:
    """The entry count (`itemListElement`, one node or an array of them) of each node typed ItemList in a JSON-LD
    document, at any depth (walked with a stack, not recursion)."""
    counts: list[int] = []
    stack = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            types = value.get(_TYPE)
            if types == _ITEM_LIST or (isinstance(types, list) and _ITEM_LIST in types):
                entries = value.get(_ENTRIES)
                counts.append(len(entries) if isinstance(entries, list) else int(entries is not None))
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return counts


def lists_items(text: str) -> bool:
    """Whether the page shows repeated items (`item_blocks`); lxml reads it, as the markdown format does."""
    return bool(item_blocks(lxml_root(text)))
