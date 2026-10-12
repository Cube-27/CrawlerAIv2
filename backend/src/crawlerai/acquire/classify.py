"""Block classification from HTTP status and document structure only (SPEC-02 §4.3, ARCHITECTURE §7.1, INV-24).

No body text is ever compared with a string: challenge pages served with 200 are not detected by content (that
would need vendor strings, C3/C4). They mostly present as shells and get a browser retry.
"""

from selectolax.lexbor import LexborHTMLParser

from crawlerai.acquire.types import BlockClass
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


def classify(status: int, headers: HeaderList, body: bytes) -> BlockClass:
    if status in _NOT_FOUND:
        return "not_found"
    if status in _BLOCKED:
        return "blocked"
    if status >= 400:
        return "error"
    if 200 <= status < 300 and _is_html(headers) and _is_shell(body):
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
