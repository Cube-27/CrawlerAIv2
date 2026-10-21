"""The URLs an HTML page states about itself and links to (adapters spec), read from its document: the references an
adapter weighs to tell which platform page a page on another host stands for (`adapters.base.Referring`)."""

from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from crawlerai.acquire.types import FetchResult
from crawlerai.adapters.base import PageRefs
from crawlerai.core.derived import held

# The most links a page's references keep: a page with more is a listing of a size no single platform site is judged
# by, so it keeps none.
MAX_LINKS = 5000


def canonical_link(page: FetchResult) -> str | None:
    """The page's `link rel=canonical` target (`_canonical`), resolved against the document's base URL (HTML Standard
    §2.4.1: the first `base href`, else the page's URL)."""
    tree = LexborHTMLParser(page.bundle.text)
    return _canonical(tree, _base(tree, page))


def page_refs(page: FetchResult) -> PageRefs:
    """`_page_refs`, read once per fetched page: a referral asks it before its adapter answers and again as it does."""
    return held(page, "_refs", (page.bundle.body, page.bundle.manifest.final_url), lambda: _page_refs(page))


def _page_refs(page: FetchResult) -> PageRefs:
    """The URLs that name the page itself, strongest first: its final URL (after the redirects of its fetch), its
    canonical link (RFC 6596) and its `og:url` (Open Graph protocol, "og:url": the object's canonical URL); and the
    absolute `http` and `https` targets of its links (HTML Standard §4.6 `a href`), in document order, each once, none
    on a page with more than `MAX_LINKS`. A reference no URL parser reads is skipped."""
    tree = LexborHTMLParser(page.bundle.text)
    base = _base(tree, page)
    own = [page.bundle.manifest.final_url]
    if (canonical := _canonical(tree, base)) is not None:
        own.append(canonical)
    for meta in tree.css("meta[content]"):
        if (meta.attributes.get("property") or "").lower() == "og:url" and (
            url := _join(base, meta.attributes.get("content") or "")
        ):
            own.append(url)
    return PageRefs(own=tuple(own), links=_links(tree, base))


def _links(tree: LexborHTMLParser, base: str) -> tuple[str, ...]:
    """The page's distinct `http` and `https` link targets in document order, or none past `MAX_LINKS`: a part of a
    larger page's links could name one site where the whole names two."""
    links: dict[str, None] = {}
    for anchor in tree.css("a[href]"):
        target = _join(base, anchor.attributes.get("href") or "")
        if target is not None and urlsplit(target).scheme in {"http", "https"}:
            links[target] = None
            if len(links) > MAX_LINKS:
                return ()
    return tuple(links)


def _join(base: str, reference: str) -> str | None:
    """`reference` resolved against `base` (RFC 3986 §5), or None for one the URL parser refuses: an authority no URL
    parser reads (§3.2.2, an unmatched bracket)."""
    try:
        url = urljoin(base, reference.strip())
        urlsplit(url)
    except ValueError:
        return None
    return url


def _base(tree: LexborHTMLParser, page: FetchResult) -> str:
    base = page.bundle.manifest.final_url
    if (element := tree.css_first("base[href]")) is not None:
        base = _join(base, element.attributes.get("href") or "") or base
    return base


def _canonical(tree: LexborHTMLParser, base: str) -> str | None:
    """The page's canonical URL; links naming more than one URL designate none (RFC 6596 §3: one per resource), as
    `content.metadata.canonical_link` reads them."""
    named = {
        _join(base, link.attributes.get("href") or "")
        for link in tree.css("link[rel][href]")
        # HTML Standard §4.6.1: `rel` is a set of space-separated, ASCII case-insensitive keywords.
        if "canonical" in (link.attributes.get("rel") or "").lower().split()
    }
    named.discard(None)  # a target no URL parser reads names nothing
    return named.pop() if len(named) == 1 else None
