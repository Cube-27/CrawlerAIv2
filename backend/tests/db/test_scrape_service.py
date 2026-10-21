"""The scrape service without HTTP (rest-api spec): one URL fetched at once, its content formats, and the job,
task, capture and usage rows it leaves."""

from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.challenges import SIGNATURES
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import Capture, Job, UrlTask
from crawlerai.services.fetching import Fetching, TargetRejected
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.fs import FsStore
from tests.db.support import Page, Web, fetching_from

pytestmark = pytest.mark.anyio

PUBLIC = ip_address("93.184.215.14")
PRIVATE = ip_address("10.0.0.7")
PAGE = b"""<!doctype html><html lang="en"><head><title>Blue  kettle</title>
<meta name="description" content="A kettle.">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Product"}</script>
<script>alert(1)</script></head>
<body><main><h1>Blue kettle</h1>
<p>A kettle that boils water quickly and quietly, with a handle that stays cool to the touch while it pours.</p>
<p>It holds one and a half litres and switches itself off once the water boils, so it never boils dry.</p>
<a href="/kettles/red">Red kettle</a> <a href="/kettles/red">Red again</a> <a href="mailto:a@example.test">Mail</a>
</main></body></html>"""


@dataclass
class Resolver:
    private_hosts: set[str] = field(default_factory=set)

    async def __call__(self, host: str) -> list[IPAddress]:
        return [PRIVATE if host in self.private_hosts else PUBLIC]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    site = Web(fetch_result)
    site.robots(own_origin, b"User-agent: *\nDisallow: /private/\n")
    return site


@pytest.fixture
def store(tmp_path: Path) -> ObjectStore:
    return FsStore(tmp_path)


@pytest.fixture
def resolver() -> Resolver:
    return Resolver()


@pytest.fixture
def fetching(web: Web, store: ObjectStore, resolver: Resolver) -> Fetching:
    return fetching_from(web, store, resolver=resolver)


def request(url: str, *formats: str, **fields: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": url, "formats": list(formats), **fields})


async def _row(engine: AsyncEngine, statement: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(statement)).one()


async def test_a_page_a_vendors_challenge_kept_out_is_blocked_naming_the_vendor_and_not_retried(
    engine: AsyncEngine, web: Web, store: ObjectStore, resolver: Resolver, own_origin: str
) -> None:
    # Master plan 2026-10-18 §3.1: an outcome, not an engine failure; the caller waits, so nothing is fetched again.
    url = f"{own_origin}/kettles/blue"
    web.serve(url, b"<html><body><script>check()</script></body></html>", 403, "blocked")
    vendor = SIGNATURES[0].vendor  # the adapter package's signature data (C3)

    def labelled(method: CaptureMethod) -> Callable[[str, FetchPolicy], Any]:
        fetch = web.rung(method)

        async def challenged(target: str, policy: FetchPolicy) -> FetchResult:
            result: FetchResult = await fetch(target, policy)
            attempts = tuple(a.model_copy(update={"challenge": vendor}) for a in result.attempts)
            return result.model_copy(update={"attempts": attempts})

        return challenged

    rungs = Rungs(http=labelled("http"), browser=labelled("browser"))
    fetching = fetching_from(rungs, store, resolver=resolver)

    result = await scrape(engine, fetching, request(url, "markdown"))

    assert (result.outcome, result.reason) == ("blocked", f"challenge: {vendor}")
    assert web.page_fetches() == [("http", url), ("browser", url)]
    task = await _row(engine, select(UrlTask.outcome, UrlTask.last_error).where(UrlTask.job_id == result.job_id))
    assert tuple(task) == ("blocked", f"challenge: {vendor}")


async def test_a_page_robots_txt_disallows_is_blocked_without_fetching_it(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/private/kettle"
    web.serve(url, PAGE)

    result = await scrape(engine, fetching, request(url, "markdown", fetch={"respect_robots": True}))

    assert web.page_fetches() == []
    assert (result.outcome, result.reason) == ("blocked", "robots")
    assert (result.capture_id, result.fetch, result.final_url, result.markdown) == (None, None, None, None)
    task = await _row(
        engine, select(UrlTask.status, UrlTask.outcome, UrlTask.last_error).where(UrlTask.job_id == result.job_id)
    )
    assert tuple(task) == ("done", "blocked", "robots")


async def test_by_default_robots_txt_is_not_requested_and_its_disallow_does_not_block(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    # Owner decision #75: robots.txt is obeyed only when the request switches it on.
    url = f"{own_origin}/private/kettle"
    web.serve(url, PAGE)

    result = await scrape(engine, fetching, request(url, "markdown"))

    assert web.fetched == [("http", url)]
    assert result.reason is None
    assert result.capture_id is not None
    assert result.markdown is not None


async def test_a_private_target_is_rejected_before_any_job_or_fetch(
    engine: AsyncEngine, fetching: Fetching, web: Web, resolver: Resolver, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    resolver.private_hosts.add(urlsplit(own_origin).netloc)
    async with engine.connect() as conn:
        jobs_before = (await conn.execute(select(func.count()).select_from(Job))).scalar_one()
    scrape_request = request(url, "markdown")

    with pytest.raises(TargetRejected) as rejected:
        await scrape(engine, fetching, scrape_request)

    assert rejected.value.reason == "ssrf_rejected: private_address"
    assert web.fetched == []
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Job))).scalar_one() == jobs_before


async def test_a_redirect_to_a_private_target_is_rejected_and_fails_the_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = Page(302, b"", "error", "ssrf_rejected: private_address")
    scrape_request = request(url, "markdown")

    with pytest.raises(TargetRejected) as rejected:
        await scrape(engine, fetching, scrape_request)

    assert rejected.value.reason == "ssrf_rejected: private_address"
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask).where(UrlTask.url == url))).one()
        job_status = (await conn.execute(select(Job.status).where(Job.id == task.job_id))).scalar_one()
        captures = (
            await conn.execute(select(func.count()).select_from(Capture).where(Capture.url == url))
        ).scalar_one()
    assert (task.status, task.capture_id, job_status, captures) == ("failed", None, "failed", 0)
