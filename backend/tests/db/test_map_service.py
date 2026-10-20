"""The map service without HTTP (jobs spec): URLs found through sitemaps and the start page's links, in scope and
canonical, with the `job(kind='map')` row that records the usage."""

import asyncio
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
from crawlerai.db.models import Job
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


async def test_the_redirect_target_s_robots_txt_decides_what_is_fetched_there(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, www_origin: str
) -> None:
    web.redirects[f"{own_origin}/"] = f"{www_origin}/"
    web.pages |= {
        f"{own_origin}/robots.txt": robots(),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{www_origin}/p/1"), "ok", None),
        f"{www_origin}/robots.txt": robots("Disallow: /sitemap.xml"),
        f"{www_origin}/sitemap.xml": (200, urlset(f"{www_origin}/p/2"), "ok", None),
        f"{www_origin}/": (200, page("/c/1"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/", respect_robots=True))

    assert result.urls == [f"{www_origin}/c/1"]
    assert f"{www_origin}/sitemap.xml" not in web.urls()
    assert f"{own_origin}/sitemap.xml" not in web.urls()


async def test_robots_txt_decides_what_is_fetched(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots("Disallow: /sitemap.xml", "Disallow: /start"),
        f"{own_origin}/sitemap.xml": (200, urlset(f"{own_origin}/s"), "ok", None),
        f"{own_origin}/start": (200, page("/l"), "ok", None),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/start", respect_robots=True))

    assert result.urls == []
    assert web.urls() == [f"{own_origin}/robots.txt"]


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
