"""The `links` content format: the page's links, absolute and canonical.

Every `a[href]` and every `link[href]` whose `rel` names canonical, next, prev or alternate, canonicalized by the url
type's rules against the document base URL, deduplicated, in document order. A reference that is not
an http(s) URL (`mailto:`, `javascript:`, an unparsable one) is not a link of the format.

A JSON body (an `api` capture's) is not HTML: markup inside its string values is text, and the
body has no link elements. Its links are its string values that are absolute http(s) URLs (RFC 3986 §4.3), canonicalized
by the same rules, deduplicated, in document order.
"""

from collections.abc import Iterator

from pydantic import JsonValue
from selectolax.lexbor import LexborNode

from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.page import ParsedPage
from crawlerai.core import json_text
from crawlerai.normalize.strings import collapse
from crawlerai.normalize.url import canonical_url

# HTML Living Standard §4.6.7, link types: the types of `link` that name another URL of the same document or of its
# sequence (`canonical`, RFC 6596) or another version of it (`alternate`).
_LINK_TYPES = frozenset({"canonical", "next", "prev", "alternate"})


def links(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The page's links (module docstring); `final_url` is the capture's final URL."""
    if page.json_body:
        return _json_links(page.html)
    return tuple(dict.fromkeys(url for _, url in _link_nodes(page, final_url)))


def anchor_texts(page: ParsedPage, final_url: str) -> dict[str, str]:
    """The words that describe each link of `links`: its anchors' visible text, `title` and `aria-label` (HTML §4.6;
    WAI-ARIA 1.2 §6.2.4), joined, whitespace collapsed, for every anchor that points at it."""
    described: dict[str, list[str]] = {}
    for node, url in _link_nodes(page, final_url):
        if node.tag != "a":
            continue
        parts = (node.text(separator=" "), node.attributes.get("title"), node.attributes.get("aria-label"))
        described.setdefault(url, []).extend(collapse(part or "") for part in parts)
    return {url: " ".join(filter(None, parts)) for url, parts in described.items()}


def _link_nodes(page: ParsedPage, final_url: str) -> Iterator[tuple[LexborNode, str]]:
    """Each link element of the format with its canonical URL, in document order; none in a JSON body."""
    if page.json_body:
        return
    base_url = document_base_url(page, final_url)
    # One canonicalization per distinct reference: navigation and listings repeat the same `href` many times.
    resolved: dict[str, str | None] = {}
    for node in page.tree.css("a[href], link[href]"):
        # HTML §4.6.1: `rel` is a set of space-separated tokens, compared ASCII case-insensitively.
        if node.tag == "link" and _LINK_TYPES.isdisjoint(tokens((node.attributes.get("rel") or "").lower())):
            continue
        href = node.attributes.get("href") or ""
        if href not in resolved:
            resolved[href] = canonical_url(href, base_url)
        url = resolved[href]
        if url is not None:
            yield node, url


def _json_links(text: str) -> tuple[str, ...]:
    try:
        document = json_text.parse(text)
    except ValueError:  # a body that is not JSON states no value to read a link from
        return ()
    # With no base, a relative reference declines: only absolute http(s) URLs are links (RFC 3986 §4.3).
    found = (canonical_url(value, None) for value in _strings(document))
    return tuple(dict.fromkeys(url for url in found if url is not None))


def _strings(document: JsonValue) -> Iterator[str]:
    """Every string value of the document, in document order (RFC 8259 §4: members in the order the text states)."""
    stack: list[JsonValue] = [document]
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            stack.extend(reversed(value.values()))
        elif isinstance(value, list):
            stack.extend(reversed(value))
