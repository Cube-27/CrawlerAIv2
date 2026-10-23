"""Sitemaps (sitemaps.org protocol): where they are found, how an urlset, an index and a gzipped
sitemap read, and how far indexes are followed. Synthetic sitemaps on RFC 2606 hosts; the fetch is a stub."""

import gzip

import pytest

from crawlerai.crawl.sitemaps import Sitemap, SitemapReader, read

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


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body><a href='/a'>a</a></body></html>",
        b"<urlset><url><loc>https://shop.example.test/a</loc>",
        b"\x1f\x8bnot gzip",
        b"",
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
