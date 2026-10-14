"""Sitemaps (SPEC-10 §4.4, §6; sitemaps.org protocol): where they are found, how an urlset, an index and a gzipped
sitemap read, and how far indexes are followed. Synthetic sitemaps on RFC 2606 hosts; the fetch is a stub."""

import gzip

import pytest

from crawlerai.crawl.sitemaps import MAX_SITEMAP_BYTES, Sitemap, SitemapReader, read, roots

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
ORIGIN = "https://shop.example.test"


def urlset(*locs: str, ns: str = NS) -> bytes:
    entries = "".join(f"<url><loc> {loc} </loc><lastmod>2026-01-01</lastmod></url>" for loc in locs)
    xmlns = f' xmlns="{ns}"' if ns else ""
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset{xmlns}>{entries}</urlset>'.encode()


def index(*locs: str) -> bytes:
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="{NS}">{entries}</sitemapindex>'.encode()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Web:
    """Answers each URL from `bodies`; anything else is not there (`None`). Records what was fetched."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.fetched: list[str] = []

    async def __call__(self, url: str) -> bytes | None:
        self.fetched.append(url)
        return self.bodies.get(url)


async def collect(reader: SitemapReader, start: tuple[str, ...]) -> list[str]:
    return [url async for url in reader.urls(start)]


def test_an_urlset_reads_its_locations_in_order() -> None:
    assert read(urlset(f"{ORIGIN}/b", f"{ORIGIN}/a&amp;b")) == Sitemap("urlset", (f"{ORIGIN}/b", f"{ORIGIN}/a&b"))


def test_an_index_reads_its_sitemaps() -> None:
    assert read(index(f"{ORIGIN}/s1.xml", f"{ORIGIN}/s2.xml.gz")) == Sitemap(
        "index", (f"{ORIGIN}/s1.xml", f"{ORIGIN}/s2.xml.gz")
    )


def test_a_sitemap_without_the_namespace_reads_by_element_names() -> None:
    assert read(urlset(f"{ORIGIN}/a", ns="")) == Sitemap("urlset", (f"{ORIGIN}/a",))


def test_a_gzipped_sitemap_reads_as_the_sitemap_it_holds() -> None:
    assert read(gzip.compress(urlset(f"{ORIGIN}/a"))) == Sitemap("urlset", (f"{ORIGIN}/a",))


def test_a_sitemap_past_the_protocol_size_declines() -> None:
    # sitemaps.org: at most 50 MB uncompressed, however small it is compressed.
    padding = b" " * MAX_SITEMAP_BYTES
    assert read(gzip.compress(urlset(f"{ORIGIN}/a") + padding)) is None
    assert read(urlset(f"{ORIGIN}/a") + padding) is None


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body><a href='/a'>a</a></body></html>",
        b"<urlset><url><loc>https://shop.example.test/a</loc>",
        b"\x1f\x8bnot gzip",
        b"",
        f"<rss><channel><link>{ORIGIN}/a</link></channel></rss>".encode(),
    ],
)
def test_what_is_not_a_sitemap_declines(body: bytes) -> None:
    assert read(body) is None


def test_entities_are_not_expanded() -> None:
    # An internal entity is left unexpanded (no "billion laughs"): the location holds only its literal text.
    body = (
        b'<?xml version="1.0"?><!DOCTYPE urlset [<!ENTITY e "https://shop.example.test/injected">]>'
        b"<urlset><url><loc>&e;</loc></url><url><loc>https://shop.example.test/a</loc></url></urlset>"
    )
    assert read(body) == Sitemap("urlset", (f"{ORIGIN}/a",))


def test_roots_are_the_robots_sitemaps_on_the_host() -> None:
    listed = [f"{ORIGIN}/s.xml", "https://cdn.example.test/s.xml", f"{ORIGIN}/s.xml#x", "/relative.xml"]
    assert roots(f"{ORIGIN}/start", listed) == (f"{ORIGIN}/s.xml",)


@pytest.mark.parametrize("listed", [[], ["https://cdn.example.test/s.xml"]])
def test_without_a_robots_sitemap_on_the_host_the_root_is_sitemap_xml(listed: list[str]) -> None:
    assert roots("https://shop.example.test:8443/a/b?q=1", listed) == ("https://shop.example.test:8443/sitemap.xml",)


async def test_an_index_is_followed_to_its_sitemaps_gzipped_or_not() -> None:
    web = Web(
        {
            f"{ORIGIN}/index.xml": index(f"{ORIGIN}/one.xml", f"{ORIGIN}/two.xml.gz"),
            f"{ORIGIN}/one.xml": urlset(f"{ORIGIN}/p/1", f"{ORIGIN}/p/2#top"),
            f"{ORIGIN}/two.xml.gz": gzip.compress(urlset(f"{ORIGIN}/p/3?b=1&amp;a=2")),
        }
    )
    reader = SitemapReader(web, "shop.example.test")

    urls = await collect(reader, (f"{ORIGIN}/index.xml",))

    assert urls == [f"{ORIGIN}/p/1", f"{ORIGIN}/p/2", f"{ORIGIN}/p/3?a=2&b=1"]
    assert reader.cut is False


async def test_page_urls_on_other_hosts_are_read_and_sitemaps_on_them_are_not_fetched() -> None:
    web = Web(
        {
            f"{ORIGIN}/index.xml": index("https://other.example.test/s.xml", f"{ORIGIN}/s.xml"),
            f"{ORIGIN}/s.xml": urlset("https://sub.shop.example.test/p/1", "ftp://shop.example.test/x", f"{ORIGIN}/a"),
        }
    )

    urls = await collect(SitemapReader(web, "shop.example.test"), (f"{ORIGIN}/index.xml",))

    # The caller's scope decides which page URLs it keeps; a location that is not an http(s) URL is none.
    assert urls == ["https://sub.shop.example.test/p/1", f"{ORIGIN}/a"]
    assert web.fetched == [f"{ORIGIN}/index.xml", f"{ORIGIN}/s.xml"]


async def test_indexes_are_followed_to_depth_three_and_no_deeper() -> None:
    # The root is depth 0; each index adds one, so a urlset under three indexes is read and a fifth index is not.
    chain = {
        f"{ORIGIN}/i0.xml": index(f"{ORIGIN}/i1.xml"),
        f"{ORIGIN}/i1.xml": index(f"{ORIGIN}/i2.xml"),
        f"{ORIGIN}/i2.xml": index(f"{ORIGIN}/leaf.xml"),
        f"{ORIGIN}/leaf.xml": urlset(f"{ORIGIN}/p"),
    }
    deep = {f"{ORIGIN}/i{n}.xml": index(f"{ORIGIN}/i{n + 1}.xml") for n in range(5)}

    reached = SitemapReader(Web(chain), "shop.example.test")
    cut = SitemapReader(Web(deep), "shop.example.test")

    assert await collect(reached, (f"{ORIGIN}/i0.xml",)) == [f"{ORIGIN}/p"]
    assert reached.cut is False
    assert await collect(cut, (f"{ORIGIN}/i0.xml",)) == []
    assert cut.cut is True


async def test_a_sitemap_is_fetched_once_however_often_it_is_listed() -> None:
    web = Web(
        {
            f"{ORIGIN}/a.xml": index(f"{ORIGIN}/b.xml", f"{ORIGIN}/a.xml"),
            f"{ORIGIN}/b.xml": index(f"{ORIGIN}/a.xml#again", f"{ORIGIN}/c.xml"),
            f"{ORIGIN}/c.xml": urlset(f"{ORIGIN}/p"),
        }
    )

    assert await collect(SitemapReader(web, "shop.example.test"), (f"{ORIGIN}/a.xml", f"{ORIGIN}/b.xml")) == [
        f"{ORIGIN}/p"
    ]
    assert web.fetched == [f"{ORIGIN}/a.xml", f"{ORIGIN}/b.xml", f"{ORIGIN}/c.xml"]


async def test_reading_stops_at_the_url_cap() -> None:
    web = Web(
        {
            f"{ORIGIN}/a.xml": urlset(f"{ORIGIN}/1", f"{ORIGIN}/2"),
            f"{ORIGIN}/b.xml": urlset(f"{ORIGIN}/3", f"{ORIGIN}/4"),
        }
    )
    reader = SitemapReader(web, "shop.example.test", max_urls=3)

    assert await collect(reader, (f"{ORIGIN}/a.xml", f"{ORIGIN}/b.xml")) == [
        f"{ORIGIN}/1",
        f"{ORIGIN}/2",
        f"{ORIGIN}/3",
    ]
    assert reader.cut is True


async def test_exactly_the_url_cap_is_not_cut() -> None:
    reader = SitemapReader(
        Web({f"{ORIGIN}/a.xml": urlset(f"{ORIGIN}/1", f"{ORIGIN}/2")}), "shop.example.test", max_urls=2
    )

    assert await collect(reader, (f"{ORIGIN}/a.xml",)) == [f"{ORIGIN}/1", f"{ORIGIN}/2"]
    assert reader.cut is False


async def test_a_missing_or_unreadable_sitemap_is_skipped() -> None:
    web = Web({f"{ORIGIN}/bad.xml": b"<html></html>", f"{ORIGIN}/good.xml": urlset(f"{ORIGIN}/p")})

    urls = await collect(
        SitemapReader(web, "shop.example.test"), (f"{ORIGIN}/gone.xml", f"{ORIGIN}/bad.xml", f"{ORIGIN}/good.xml")
    )

    assert urls == [f"{ORIGIN}/p"]
