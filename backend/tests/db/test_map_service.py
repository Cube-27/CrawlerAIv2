"""The map service without HTTP: URLs found through sitemaps and the start page's links, in scope and
canonical, with the `job(kind='map')` row that records the usage."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.types import FetchResult
from snowcrawl.db.models import Job
from snowcrawl.services.fetching import Fetching, TargetRejected
from snowcrawl.services.map import MapRequest, map_urls
from tests.db.support import PRIVATE_HOST, Page, Web, fetching_from, unpaced

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def urlset(*locs: str) -> bytes:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0"?><urlset xmlns="{NS}">{entries}</urlset>'.encode()


def page(*hrefs: str) -> bytes:
    anchors = "".join(f'<a href="{href}">link</a>' for href in hrefs)
    return f"<!doctype html><html><head><title>Start</title></head><body><main>{anchors}</main></body></html>".encode()


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult]) -> Web:
    """A site without robots.txt."""
    return Web(fetch_result)


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    return fetching_from(web, tmp_path, limiter=unpaced())


def robots(*lines: str) -> Page:
    return Page(200, "\n".join(["User-agent: *", *lines]).encode())


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
        f"{own_origin}/sitemap.xml": Page(200, urlset(f"{www_origin}/p/1")),
        f"{www_origin}/robots.txt": robots("Disallow: /sitemap.xml"),
        f"{www_origin}/sitemap.xml": Page(200, urlset(f"{www_origin}/p/2")),
        f"{www_origin}/": Page(200, page("/c/1")),
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
        f"{own_origin}/sitemap.xml": Page(200, urlset(f"{own_origin}/s")),
        f"{own_origin}/start": Page(200, page("/l")),
    }

    result = await map_urls(engine, fetching, request(f"{own_origin}/start", respect_robots=True))

    assert result.urls == []
    assert web.urls() == [f"{own_origin}/robots.txt"]


async def test_a_private_target_is_refused_before_any_job(engine: AsyncEngine, fetching: Fetching, web: Web) -> None:
    refused = request(f"https://{PRIVATE_HOST}/")

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
        f"{own_origin}/sitemap.xml": Page(0, b"", "error", "ssrf_rejected: private_address"),
    }
    refused = request(f"{own_origin}/", use_links=False)

    with pytest.raises(TargetRejected, match="private_address"):
        await map_urls(engine, fetching, refused)

    assert (await _job(engine)).status == "failed"
