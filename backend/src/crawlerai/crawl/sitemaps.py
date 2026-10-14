"""Sitemaps (SPEC-10 §4.4; the sitemaps.org protocol): where a site's are, how one reads, and reading them through
their indexes.

The sitemaps are the ones robots.txt lists with `Sitemap:` on the start URL's host, else `/sitemap.xml` there. An
index is followed to the sitemaps it lists on that host, to depth 3. Page URLs are read up to a cap, in canonical form
and on any host: which of them a request keeps is its scope's (`crawl.rules`). A sitemap that is missing, malformed or
past the protocol's size is skipped.
"""

import asyncio
import zlib
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urljoin, urlsplit

from lxml import etree

from crawlerai.crawl.canonical import canonicalize

MAX_DEPTH: Final = 3  # SPEC-10 §4.4: indexes are followed to depth 3 (a root is depth 0)
MAX_URLS: Final = 50_000  # SPEC-10 §4.4: at most 50k URLs are read
# sitemaps.org: a sitemap holds at most 50,000 URLs and is at most 50 MB (52,428,800 bytes) uncompressed.
MAX_SITEMAP_BYTES: Final = 52_428_800
_GZIP_MAGIC: Final = b"\x1f\x8b"  # RFC 1952 §2.3.1: ID1 and ID2 of a gzip member
# sitemaps.org: an urlset lists `url` entries and an index `sitemap` entries, each with a `loc`.
_ENTRIES: Final[dict[str, tuple[str, Literal["urlset", "index"]]]] = {
    "urlset": ("url", "urlset"),
    "sitemapindex": ("sitemap", "index"),
}

FetchBody = Callable[[str], Awaitable[bytes | None]]
_Queue = deque[tuple[str, int]]  # sitemap URLs to read, with their depth


@dataclass(frozen=True)
class Sitemap:
    """A sitemap as read: an urlset of page locations, or an index of sitemap locations, as written."""

    kind: Literal["urlset", "index"]
    locs: tuple[str, ...]


def roots(start_url: str, listed: Sequence[str]) -> tuple[str, ...]:
    """The sitemaps to read for `start_url`: those of robots.txt's `listed` that are on its host, else `/sitemap.xml`
    at its origin (sitemaps.org, "Informing search engine crawlers")."""
    on_host = _on_host(filter(None, map(canonicalize, listed)), _host(start_url))
    if on_host:
        return tuple(dict.fromkeys(on_host))
    fallback = canonicalize(urljoin(start_url, "/sitemap.xml"))
    return () if fallback is None else (fallback,)


def read(body: bytes) -> Sitemap | None:
    """The sitemap `body` holds, gzipped or not; `None` when it holds none or is past the protocol's size."""
    xml = _gunzipped(body) if body.startswith(_GZIP_MAGIC) else body
    if xml is None or len(xml) > MAX_SITEMAP_BYTES:
        return None
    # Page content is untrusted: no entity is expanded (so no exponential "billion laughs" growth), and no DTD or
    # other resource is fetched.
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(xml, parser)
    except etree.XMLSyntaxError:
        return None
    entry = _ENTRIES.get(_local_name(root))
    if entry is None:
        return None
    child, kind = entry
    locs = (
        loc.text.strip()
        for item in root
        if _local_name(item) == child
        for loc in item
        if _local_name(loc) == "loc" and loc.text
    )
    return Sitemap(kind, tuple(loc for loc in locs if loc))


class SitemapReader:
    """Reads sitemaps through `fetch`, which answers a sitemap URL with its body, or `None` when there is none to
    read. `cut` is set once a cap (depth, `max_urls`) kept a sitemap or a URL from being read."""

    def __init__(self, fetch: FetchBody, host: str, *, max_urls: int = MAX_URLS) -> None:
        self._fetch = fetch
        self._host = host
        self._max_urls = max_urls
        self.cut = False

    async def urls(self, start: Iterable[str]) -> AsyncGenerator[str]:
        """The page URLs of the sitemaps from `start` and the indexes under them, breadth first. Each sitemap is
        fetched once."""
        queue: _Queue = deque((url, 0) for url in start)
        seen: set[str] = set()
        count = 0
        while (urlset := await self._next_urlset(queue, seen)) is not None:
            for page in urlset.locs:
                if count == self._max_urls:
                    self.cut = True
                    return
                count += 1
                yield page

    async def _next_urlset(self, queue: _Queue, seen: set[str]) -> Sitemap | None:
        """The next urlset of `queue`, reading the indexes before it into `queue`; `None` once it is empty."""
        while queue:
            url, depth = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            sitemap = await self._sitemap(url)
            if sitemap is not None and sitemap.kind == "index":
                queue.extend((child, depth + 1) for child in self._children(sitemap, depth))
            elif sitemap is not None:
                return sitemap
        return None

    async def _sitemap(self, url: str) -> Sitemap | None:
        """The sitemap at `url`, its locations canonical; `None` when there is none to read."""
        body = await self._fetch(url)
        # Up to 50 MB of XML and 50k URLs are parsed: a thread keeps the event loop free.
        return None if body is None else await asyncio.to_thread(_read_canonical, body)

    def _children(self, index: Sitemap, depth: int) -> list[str]:
        """The sitemaps of `index` to read: those on the host, unless they would be past the depth cap."""
        children = _on_host(index.locs, self._host)
        if children and depth == MAX_DEPTH:
            self.cut = True
            return []
        return children


def _read_canonical(body: bytes) -> Sitemap | None:
    """`read`, with each location in canonical form; one that is not an http(s) URL is dropped."""
    sitemap = read(body)
    if sitemap is None:
        return None
    return Sitemap(sitemap.kind, tuple(filter(None, map(canonicalize, sitemap.locs))))


def _on_host(urls: Iterable[str], host: str | None) -> list[str]:
    return [url for url in urls if _host(url) == host]


def _gunzipped(body: bytes) -> bytes | None:
    """The gzip member's content, read to one byte past the protocol's size so that a larger one is seen as such."""
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)  # 16+: a gzip header and trailer (RFC 1952)
    try:
        return decompressor.decompress(body, MAX_SITEMAP_BYTES + 1)
    except zlib.error:
        return None


def _local_name(element: etree._Element) -> str:
    # Element names without their `{namespace}` (lxml's Clark notation), so that a sitemap without the protocol's
    # namespace reads too. Comments and processing instructions have no name.
    return element.tag.rpartition("}")[2] if isinstance(element.tag, str) else ""


def _host(url: str) -> str | None:
    return urlsplit(url).hostname
