"""The map service without HTTP (SPEC-10 §4.4): URLs found through sitemaps and the start page's links, in scope and
canonical, with the `job(kind='map')` row that records the usage.

The web is a stub that answers synthetic pages and sitemaps on RFC 2606 hosts, and the resolver a stub: no network.
The limiter's clock jumps ahead on every reading, so the site's rate never makes a test wait.
"""

import asyncio
import gzip
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import Job, UsageEvent
from crawlerai.services.fetching import Fetching, TargetRejected
from crawlerai.services.map import MapRequest, map_urls
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PUBLIC = ip_address("93.184.215.14")
PRIVATE = ip_address("10.0.0.7")
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

Page = tuple[int, bytes, BlockClass, str | None]


def urlset(*locs: str) -> bytes:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0"?><urlset xmlns="{NS}">{entries}</urlset>'.encode()


def index(*locs: str) -> bytes:
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0"?><sitemapindex xmlns="{NS}">{entries}</sitemapindex>'.encode()


def page(*hrefs: str) -> bytes:
    anchors = "".join(f'<a href="{href}">link</a>' for href in hrefs)
    return f"<!doctype html><html><head><title>Start</title></head><body><main>{anchors}</main></body></html>".encode()


@dataclass
class Web:
    """Answers each URL from `pages`; anything else is a 404. A URL of `redirects` answers as its target, reached
    through the site's redirect. `slow` URLs are held back by `delay_s`."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, Page] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    fetched: list[tuple[CaptureMethod, str]] = field(default_factory=list)
    policies: dict[str, FetchPolicy] = field(default_factory=dict)
    slow: set[str] = field(default_factory=set)
    delay_s: float = 5.0

    def rung(self, method: CaptureMethod) -> Callable[[str, FetchPolicy], Any]:
        async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
            self.fetched.append((method, url))
            self.policies[url] = policy
            if url in self.slow:
                await asyncio.sleep(self.delay_s)
            final_url = self.redirects.get(url, url)
            status, body, block_class, error = self.pages.get(final_url, (404, b"gone", "not_found", None))
            return self.fetch_result(
                url, status, body, block_class=block_class, error=error, method=method, final_url=final_url
            )

        return fetch

    def urls(self) -> list[str]:
        return [url for _, url in self.fetched]


@dataclass
class Resolver:
    private_hosts: set[str] = field(default_factory=set)

    async def __call__(self, host: str) -> list[IPAddress]:
        return [PRIVATE if host in self.private_hosts else PUBLIC]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult]) -> Web:
    return Web(fetch_result)


@pytest.fixture
def resolver() -> Resolver:
    return Resolver()


@pytest.fixture
def fetching(web: Web, resolver: Resolver, tmp_path: Path) -> Fetching:
    clock = itertools.count(step=3600)
    return Fetching(
        rungs=Rungs(http=web.rung("http"), browser=web.rung("browser")),
        connector=SafeConnector(resolver),
        store=FsStore(tmp_path),
        limiter=HostLimiter(clock=lambda: float(next(clock))),
    )


def robots(*lines: str) -> Page:
    return (200, "\n".join(["User-agent: *", *lines]).encode(), "ok", None)


def request(url: str, **fields: Any) -> MapRequest:
    return MapRequest.model_validate({"url": url, **fields})


async def _job(engine: AsyncEngine) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(select(Job.id, Job.kind, Job.status, Job.finished_at).where(Job.kind == "map"))
        ).one()


async def test_returns_sitemap_urls_then_link_urls_in_scope_and_canonical(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/index.xml"),
        f"{own_origin}/index.xml": (200, index(f"{own_origin}/a.xml", f"{own_origin}/b.xml.gz"), "ok", None),
        f"{own_origin}/a.xml": (200, urlset(f"{own_origin}/p/1", f"{own_origin}/p/2#top"), "ok", None),
        f"{own_origin}/b.xml.gz": (200, gzip.compress(urlset(f"{own_origin}/p/3?b=1&amp;a=2")), "ok", None),
        f"{own_origin}/start": (
            200,
            page("/p/1", "/c/9", "https://other.example.test/x", "mailto:a@b.test"),
            "ok",
            None,
        ),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/start"))

    assert result.urls == [
        f"{own_origin}/p/1",
        f"{own_origin}/p/2",
        f"{own_origin}/p/3?a=2&b=1",
        f"{own_origin}/c/9",
    ]
    assert (result.sources.sitemap, result.sources.links) == (3, 1)
    assert result.truncated is False


async def test_without_a_robots_sitemap_reads_sitemap_xml(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots("Allow: /"),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/p/1"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/deep/start?x=1", use_links=False))

    assert result.urls == [f"{own_origin}/p/1"]
    # The start page is fetched for where it is (its redirect), even when its links are not taken.
    assert web.urls() == [f"{own_origin}/robots.txt", f"{own_origin}/deep/start?x=1", f"{own_origin}/sitemap.xml"]


async def test_include_and_exclude_choose_the_urls_and_include_may_name_another_host(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    sub = own_origin.replace("https://", "https://sub.")
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (
            200,
            urlset(f"{own_origin}/p/1", f"{own_origin}/p/private", f"{own_origin}/c/1", f"{sub}/p/2"),
            "ok",
            None,
        ),
    }
    body = {"include": [f"{own_origin}/p/*", f"{sub}/*"], "exclude": ["*/private"], "use_links": False}

    result = await map_urls(engine, fetching, request(f"{own_origin}/", **body))

    assert result.urls == [f"{own_origin}/p/1", f"{sub}/p/2"]


async def test_the_limit_cuts_the_urls_and_says_so(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/a.xml", f"Sitemap: {own_origin}/b.xml"),
        f"{own_origin}/a.xml": (200, urlset(f"{own_origin}/1", f"{own_origin}/2", f"{own_origin}/3"), "ok", None),
        f"{own_origin}/b.xml": (200, urlset(f"{own_origin}/4"), "ok", None),
    }

    cut = await map_urls(engine, fetching, request(f"{own_origin}/", limit=2, use_links=False))
    exact = await map_urls(engine, fetching, request(f"{own_origin}/", limit=4, use_links=False))

    assert (cut.urls, cut.truncated) == ([f"{own_origin}/1", f"{own_origin}/2"], True)
    assert (cut.sources.sitemap, cut.sources.links) == (2, 0)
    # Once more URLs than the limit are found, no further sitemap is read.
    assert web.urls().count(f"{own_origin}/b.xml") == 1
    assert (len(exact.urls), exact.truncated) == (4, False)


async def test_sources_can_be_turned_off(engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/": (200, page("/l"), "ok", None),
    }

    links_only = await map_urls(engine, fetching, request(f"{own_origin}/", use_sitemaps=False))
    sitemaps_only = await map_urls(engine, fetching, request(f"{own_origin}/", use_links=False))

    assert (links_only.urls, sitemaps_only.urls) == ([f"{own_origin}/l"], [f"{own_origin}/s"])
    assert web.urls().count(f"{own_origin}/sitemap.xml") == 1
    assert web.urls().count(f"{own_origin}/") == 2


async def test_the_scope_follows_the_start_page_s_redirect_to_another_host(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, other_origin: str
) -> None:
    # The start URL's host redirects every URL to `own_origin` (RFC 9110 §15.4: the redirect names where the resource
    # is): the site's links and sitemaps are on that host, read under its own robots.txt.
    web.redirects |= {f"{other_origin}/": f"{own_origin}/", f"{other_origin}/robots.txt": f"{own_origin}/robots.txt"}
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/products.xml"),
        f"{own_origin}/products.xml": (200, urlset(f"{own_origin}/p/1", f"{other_origin}/p/9"), "ok", None),
        f"{own_origin}/": (200, page("/c/1", f"{own_origin}/c/2", f"{other_origin}/c/3"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{other_origin}/"))

    assert result.urls == [f"{own_origin}/p/1", f"{own_origin}/c/1", f"{own_origin}/c/2"]
    assert web.urls() == [
        f"{other_origin}/robots.txt",
        f"{other_origin}/",
        f"{own_origin}/robots.txt",
        f"{own_origin}/products.xml",
    ]


async def test_the_redirect_target_s_robots_txt_decides_what_is_fetched_there(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, other_origin: str
) -> None:
    web.redirects[f"{other_origin}/"] = f"{own_origin}/"
    web.pages |= {
        f"{other_origin}/robots.txt": robots(),
        f"{other_origin}/sitemap.xml": (200, urlset(f"{own_origin}/p/1"), "ok", None),
        f"{own_origin}/robots.txt": robots("Disallow: /sitemap.xml"),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/p/2"), "ok", None),
        f"{own_origin}/": (200, page("/c/1"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{other_origin}/"))

    assert result.urls == [f"{own_origin}/c/1"]
    assert f"{own_origin}/sitemap.xml" not in web.urls()
    assert f"{other_origin}/sitemap.xml" not in web.urls()


async def test_fetches_over_http_only_and_takes_no_links_from_a_page_not_reached(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/": (200, page("/l"), "shell", None),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/", use_sitemaps=False))

    assert result.urls == []
    assert {method for method, _ in web.fetched} == {"http"}


async def test_robots_txt_decides_what_is_fetched(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots("Disallow: /sitemap.xml", "Disallow: /start"),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/start": (200, page("/l"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/start"))

    assert result.urls == []
    assert web.urls() == [f"{own_origin}/robots.txt"]


async def test_an_unreachable_robots_txt_allows_nothing(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages[f"{own_origin}/robots.txt"] = (503, b"", "error", None)

    result = await map_urls(engine, fetching, request(f"{own_origin}/"))

    assert (result.urls, result.truncated) == ([], False)
    assert web.urls() == [f"{own_origin}/robots.txt"]


async def test_records_a_completed_map_job_with_its_requests_as_usage(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/": (200, page("/l"), "ok", None),
    }

    await map_urls(engine, fetching, request(f"{own_origin}/"))

    job = await _job(engine)
    assert (job.kind, job.status) == ("map", "completed")
    assert job.finished_at is not None
    async with engine.connect() as conn:
        used = (await conn.execute(select(func.sum(UsageEvent.quantity)).where(UsageEvent.job_id == job.id))).one()
    assert used[0] == 3  # robots.txt, the start page and the sitemap


async def test_a_sitemap_may_be_larger_than_a_page(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/": (200, page("/l"), "ok", None),
    }

    await map_urls(engine, fetching, request(f"{own_origin}/"))

    # sitemaps.org: a sitemap is at most 50 MB uncompressed, past the page cap of the default policy.
    sitemap_policy = web.policies[f"{own_origin}/sitemap.xml"]
    assert (sitemap_policy.max_body_bytes, sitemap_policy.max_decompressed_bytes) == (52_428_800, 52_428_800)
    assert web.policies[f"{own_origin}/"].max_body_bytes == FetchPolicy().max_body_bytes


async def test_past_its_timeout_returns_what_was_found_as_truncated(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/": (200, page("/l"), "ok", None),
    }
    web.slow.add(f"{own_origin}/sitemap.xml")

    result = await map_urls(engine, fetching, request(f"{own_origin}/"), timeout_s=0.5)

    assert (result.urls, result.truncated) == ([f"{own_origin}/l"], True)
    assert (await _job(engine)).status == "completed"


async def test_a_private_target_is_refused_before_any_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, resolver: Resolver
) -> None:
    resolver.private_hosts.add("intranet.example.test")
    refused = request("https://intranet.example.test/")

    with pytest.raises(TargetRejected, match="private_address"):
        await map_urls(engine, fetching, refused)

    assert web.fetched == []
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).where(Job.kind == "map"))).scalar_one() == 0


async def test_a_fetch_the_guard_refuses_fails_the_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    # A redirect to a private address: the rung reports the guard's refusal as the attempt's error.
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (0, b"", "error", "ssrf_rejected: private_address"),
    }
    refused = request(f"{own_origin}/", use_links=False)

    with pytest.raises(TargetRejected, match="private_address"):
        await map_urls(engine, fetching, refused)

    assert (await _job(engine)).status == "failed"


@pytest.mark.parametrize(
    ("body", "member"),
    [
        ({"url": "/relative"}, "url"),
        ({"url": "https://example.test/", "limit": 0}, "limit"),
        ({"url": "https://example.test/", "depth": 2}, "depth"),
    ],
)
def test_an_invalid_request_is_refused(body: dict[str, Any], member: str) -> None:
    with pytest.raises(ValueError, match=member):
        MapRequest.model_validate(body)
