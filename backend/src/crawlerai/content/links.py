"""The `links` content format (SPEC-07 §4.5, ARCHITECTURE §8.5): the page's links, absolute and canonical.

Every `a[href]` and every `link[href]` whose `rel` names canonical, next, prev or alternate, canonicalized by the url
type's rules (SPEC-04 §4.4) against the document base URL, deduplicated, in document order. A reference that is not
an http(s) URL (`mailto:`, `javascript:`, an unparsable one) is not a link of the format.
"""

from crawlerai.content.dom import document_base_url, tokens
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.url import canonical_url

# HTML Living Standard §4.6.7, link types: the types of `link` that name another URL of the same document or of its
# sequence (`canonical`, RFC 6596) or another version of it (`alternate`).
_LINK_TYPES = frozenset({"canonical", "next", "prev", "alternate"})


def links(page: ParsedPage, final_url: str) -> tuple[str, ...]:
    """The page's links (module docstring); `final_url` is the capture's final URL."""
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
    return tuple(dict.fromkeys(url for url in resolved.values() if url is not None))
