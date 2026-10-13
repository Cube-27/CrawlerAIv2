"""The `links` content format (SPEC-07 §4.5, ARCHITECTURE §8.5): the page's links, absolute and canonical.

Every `a[href]` and every `link[href]` whose `rel` names canonical, next, prev or alternate, canonicalized by the url
type's rules (SPEC-04 §4.4) against the document base URL, deduplicated, in document order. A reference that is not
an http(s) URL (`mailto:`, `javascript:`, an unparsable one) is not a link of the format.
"""

import re

from selectolax import lexbor

from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Ok
from crawlerai.normalize.url import canonical

# HTML Living Standard §4.6.7, link types: the types of `link` that name another URL of the same document or of its
# sequence (`canonical`, RFC 6596) or another version of it (`alternate`).
_LINK_TYPES = frozenset({"canonical", "next", "prev", "alternate"})
# HTML Living Standard §2.3.2: ASCII whitespace separates the tokens of a set of space-separated tokens.
_ASCII_WHITESPACE = re.compile(r"[\t\n\f\r ]+")


def rel_types(node: lexbor.LexborNode) -> frozenset[str]:
    """The link types in `node`'s `rel` (HTML §4.6.1: a set of space-separated tokens, ASCII case-insensitive)."""
    return frozenset(_ASCII_WHITESPACE.split((node.attributes.get("rel") or "").lower())) - {""}


def document_base_url(page: ParsedPage, final_url: str) -> str:
    """HTML Living Standard §2.4.1, document base URL: the `href` of the first `base` element that has one, resolved
    against the document's URL; the document's URL when there is none or it does not parse."""
    base = page.tree.css_first("base[href]")
    if base is not None:
        resolved = canonical(base.attributes.get("href") or "", final_url)
        if isinstance(resolved, Ok) and isinstance(resolved.value, str):
            return resolved.value
    return final_url


def absolute_url(href: str, base_url: str) -> str | None:
    """`href` as a canonical absolute http(s) URL, or `None` when it is not one."""
    result = canonical(href, base_url)
    return result.value if isinstance(result, Ok) and isinstance(result.value, str) else None


def links(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The page's links (module docstring); `final_url` is the capture's final URL."""
    base_url = document_base_url(page, final_url)
    seen: dict[str, None] = {}
    for node in page.tree.css("a[href], link[href]"):
        if node.tag == "link" and rel_types(node).isdisjoint(_LINK_TYPES):
            continue
        url = absolute_url(node.attributes.get("href") or "", base_url)
        if url is not None:
            seen.setdefault(url)
    return tuple(seen)
