"""The scrape service without HTTP (SPEC-07 §4.4, §4.7): one URL fetched at once, its content formats, and the job,
task, capture and usage rows it leaves.

The web is a stub that answers synthetic pages on RFC 2606 hosts, and the resolver a stub: no network.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import Capture, Job, Site, UrlTask, UsageEvent
from crawlerai.services.scrape import Fetching, ScrapeRejected, ScrapeRequest, ScrapeTimedOut, scrape
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import capture_key, decode
from crawlerai.storage.fs import FsStore

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
class Web:
    """Answers each URL from `pages` as (status, body, block class, error); anything else is a 404. `delay_s` holds
    every answer back."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes, BlockClass, str | None]] = field(default_factory=dict)
    fetched: list[tuple[CaptureMethod, str]] = field(default_factory=list)
    delay_s: float = 0.0

    def rung(self, method: CaptureMethod) -> Callable[[str, FetchPolicy], Any]:
        async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
            self.fetched.append((method, url))
            await asyncio.sleep(self.delay_s)
            status, body, block_class, error = self.pages.get(url, (404, b"gone", "not_found", None))
            return self.fetch_result(url, status, body, block_class=block_class, error=error, method=method)

        return fetch

    def page_fetches(self) -> list[tuple[CaptureMethod, str]]:
        return [(method, url) for method, url in self.fetched if not url.endswith("/robots.txt")]


@dataclass
class Resolver:
    private_hosts: set[str] = field(default_factory=set)

    async def __call__(self, host: str) -> list[IPAddress]:
        return [PRIVATE if host in self.private_hosts else PUBLIC]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": (200, b"User-agent: *\nDisallow: /private/\n", "ok", None)})


@pytest.fixture
def store(tmp_path: Path) -> ObjectStore:
    return FsStore(tmp_path)


@pytest.fixture
def resolver() -> Resolver:
    return Resolver()


@pytest.fixture
def fetching(web: Web, store: ObjectStore, resolver: Resolver) -> Fetching:
    return Fetching(
        rungs=Rungs(http=web.rung("http"), browser=web.rung("browser")),
        connector=SafeConnector(resolver),
        store=store,
        limiter=HostLimiter(),
    )


def request(url: str, *formats: str, **fields: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": url, "formats": list(formats), **fields})


async def _row(engine: AsyncEngine, statement: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(statement)).one()


async def test_returns_the_requested_formats_of_the_fetched_page(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)

    result = await scrape(engine, fetching, request(url, "markdown", "html", "raw_html", "links", "metadata"))

    assert result.outcome == "extracted"
    assert (result.url, result.final_url) == (url, url)
    assert result.raw_html == PAGE.decode()
    assert result.html is not None and "<script" not in result.html and "<h1>Blue kettle</h1>" in result.html
    assert result.markdown is not None and "boils water quickly" in result.markdown
    assert result.links == [f"{own_origin}/kettles/red"]
    assert result.metadata is not None
    assert (result.metadata.title, result.metadata.description, result.metadata.language) == (
        "Blue kettle",
        "A kettle.",
        "en",
    )
    assert result.metadata.structured_data_types == ("Product",)


async def test_leaves_out_the_formats_not_requested(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)

    result = await scrape(engine, fetching, request(url, "links"))

    assert result.links == [f"{own_origin}/kettles/red"]
    assert (result.markdown, result.html, result.raw_html, result.metadata) == (None, None, None, None)
    assert set(result.model_dump(by_alias=True)) == {
        "job_id",
        "capture_id",
        "url",
        "final_url",
        "fetched_at",
        "outcome",
        "fetch",
        "links",
        "usage",
    }


async def test_records_a_completed_scrape_job_its_task_and_capture(
    engine: AsyncEngine, fetching: Fetching, store: ObjectStore, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)

    result = await scrape(engine, fetching, request(url, "markdown", fetch={"method_hint": "http"}))

    job = await _row(engine, select(Job.kind, Job.status, Job.request).where(Job.id == result.job_id))
    assert (job.kind, job.status) == ("scrape", "completed")
    assert job.request["url"] == url and job.request["fetch"]["method_hint"] == "http"
    task = await _row(engine, select(UrlTask).where(UrlTask.job_id == result.job_id))
    assert (task.status, task.outcome, task.capture_id, task.canonical_url) == (
        "done",
        "extracted",
        result.capture_id,
        url,
    )
    capture = await _row(engine, select(Capture.url, Capture.fetched_at).where(Capture.id == result.capture_id))
    assert capture.url == url
    assert result.capture_id is not None
    assert decode(store.get(capture_key(result.capture_id, capture.fetched_at))).body == PAGE


async def test_counts_each_request_it_made_as_usage(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)

    result = await scrape(engine, fetching, request(url, "markdown"))

    # robots.txt, then the page.
    assert result.usage.http_requests == 2
    assert (result.usage.llm_calls, result.usage.browser_seconds) == (0, 0)
    used = await _row(engine, select(func.sum(UsageEvent.quantity)).where(UsageEvent.job_id == result.job_id))
    assert used[0] == 2


@pytest.mark.parametrize(
    ("status", "block_class", "outcome"),
    [(403, "blocked", "blocked"), (404, "not_found", "not_found"), (200, "shell", "shell")],
)
async def test_a_page_that_is_not_ok_is_an_outcome_without_formats(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    status: int,
    block_class: BlockClass,
    outcome: str,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (status, b"<html><body>no</body></html>", block_class, None)

    result = await scrape(engine, fetching, request(url, "markdown", "raw_html", fetch={"method_hint": "http"}))

    assert result.outcome == outcome
    assert result.fetch is not None and result.fetch.status_code == status
    assert (result.markdown, result.raw_html) == (None, None)
    task = await _row(engine, select(UrlTask.status, UrlTask.outcome).where(UrlTask.job_id == result.job_id))
    assert tuple(task) == ("done", outcome)


async def test_a_failed_fetch_fails_the_task_and_the_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (0, b"", "error", "network_error: ConnectError")

    result = await scrape(engine, fetching, request(url, "markdown"))

    assert result.outcome == "failed"
    assert result.fetch is not None
    assert [a.error for a in result.fetch.attempts] == ["network_error: ConnectError"]
    assert result.fetch.status_code is None
    task = await _row(engine, select(UrlTask.status, UrlTask.last_error).where(UrlTask.job_id == result.job_id))
    assert tuple(task) == ("failed", "network_error: ConnectError")
    job = await _row(engine, select(Job.status).where(Job.id == result.job_id))
    assert job.status == "failed"


async def test_a_shell_over_http_is_fetched_again_in_the_browser(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, fetch_result: Callable[..., FetchResult]
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, b"<html><body></body></html>", "shell", None)

    async def browser(target: str, policy: FetchPolicy) -> FetchResult:
        return fetch_result(target, 200, PAGE, method="browser")

    fetching = Fetching(
        Rungs(http=web.rung("http"), browser=browser), fetching.connector, fetching.store, HostLimiter()
    )

    result = await scrape(engine, fetching, request(url, "raw_html"))

    assert result.outcome == "extracted"
    assert result.fetch is not None and result.fetch.method == "browser"
    assert [a.method for a in result.fetch.attempts] == ["http", "browser"]
    assert result.raw_html == PAGE.decode()
    site = await _row(engine, select(Site.fetch_method).where(Site.host == urlsplit(url).hostname))
    assert site.fetch_method == "browser"


async def test_a_page_robots_txt_disallows_is_blocked_without_fetching_it(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/private/kettle"
    web.pages[url] = (200, PAGE, "ok", None)

    result = await scrape(engine, fetching, request(url, "markdown"))

    assert web.page_fetches() == []
    assert result.outcome == "blocked"
    assert (result.capture_id, result.fetch, result.final_url, result.markdown) == (None, None, None, None)
    task = await _row(
        engine, select(UrlTask.status, UrlTask.outcome, UrlTask.last_error).where(UrlTask.job_id == result.job_id)
    )
    assert tuple(task) == ("done", "blocked", "robots")


async def test_an_unreachable_robots_txt_allows_nothing(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)
    web.pages[f"{own_origin}/robots.txt"] = (503, b"", "blocked", None)

    result = await scrape(engine, fetching, request(url, "markdown"))

    assert web.page_fetches() == []
    assert result.outcome == "blocked"
    task = await _row(engine, select(UrlTask.last_error).where(UrlTask.job_id == result.job_id))
    assert task.last_error == "robots_unreachable"


async def test_the_operator_override_skips_robots_txt(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/private/kettle"
    web.pages[url] = (200, PAGE, "ok", None)
    override = {"respect_robots": False, "robots_override_reason": "the site's operator asked for it"}

    result = await scrape(engine, fetching, request(url, "raw_html", fetch=override))

    assert web.fetched == [("http", url)]
    assert result.outcome == "extracted"


async def test_a_private_target_is_rejected_before_any_job_or_fetch(
    engine: AsyncEngine, fetching: Fetching, web: Web, resolver: Resolver, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    resolver.private_hosts.add(urlsplit(own_origin).netloc)
    async with engine.connect() as conn:
        jobs_before = (await conn.execute(select(func.count()).select_from(Job))).scalar_one()
    scrape_request = request(url, "markdown")

    with pytest.raises(ScrapeRejected) as rejected:
        await scrape(engine, fetching, scrape_request)

    assert rejected.value.reason == "ssrf_rejected: private_address"
    assert web.fetched == []
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Job))).scalar_one() == jobs_before


async def test_a_redirect_to_a_private_target_is_rejected_and_fails_the_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (302, b"", "error", "ssrf_rejected: private_address")
    scrape_request = request(url, "markdown")

    with pytest.raises(ScrapeRejected) as rejected:
        await scrape(engine, fetching, scrape_request)

    assert rejected.value.reason == "ssrf_rejected: private_address"
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask).where(UrlTask.url == url))).one()
        job_status = (await conn.execute(select(Job.status).where(Job.id == task.job_id))).scalar_one()
        captures = (
            await conn.execute(select(func.count()).select_from(Capture).where(Capture.url == url))
        ).scalar_one()
    assert (task.status, task.capture_id, job_status, captures) == ("failed", None, "failed", 0)


async def test_a_scrape_past_its_timeout_fails_the_job_and_returns_nothing(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok", None)
    web.delay_s = 5
    scrape_request = request(url, "markdown", timeout_s=0.2)

    with pytest.raises(ScrapeTimedOut):
        await scrape(engine, fetching, scrape_request)

    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask).where(UrlTask.url == url))).one()
        job_status = (await conn.execute(select(Job.status).where(Job.id == task.job_id))).scalar_one()
    assert (task.status, task.outcome, task.last_error, job_status) == ("failed", "failed", "timeout", "failed")
