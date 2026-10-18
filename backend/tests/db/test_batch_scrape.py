"""`batch_scrape` jobs (jobs spec): submitted through the batch service, run by worker loops through the real queue,
and read back through the jobs service; with the settings pinned at submit (INV-28) and each task isolated from the
others (INV-31)."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    Job,
    JobId,
    UrlTask,
)
from crawlerai.db.queue import MAX_ATTEMPTS
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.jobs import PageOutputPage, ResultsQuery
from crawlerai.storage.fs import FsStore
from crawlerai.worker.browser import SharedBrowser
from crawlerai.worker.handlers.table import task_handlers
from crawlerai.worker.loop import run_worker

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}


def _page(name: str, *, offers: bool = True) -> bytes:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return (
        f'<!doctype html><html lang="en"><head><title>{name}</title>'
        f'<script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><main><h1>{name}</h1><p>A kettle that boils water quickly and quietly.</p>"
        f'<a href="/kettles/other">Another kettle</a></main></body></html>'
    ).encode()


class Crash(Exception):
    pass


@dataclass
class Session:
    number: int
    connected: bool = True


@dataclass
class Web:
    """Answers each URL from `pages` as (status, body) over HTTP; anything else is a 404. A URL in `raising` makes
    the HTTP rung raise. The browser answers the same pages, or a URL's page in `renders`; a fetch of a URL in
    `crashing` kills its session."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    raising: set[str] = field(default_factory=set)
    crashing: set[str] = field(default_factory=set)
    renders: dict[str, bytes] = field(default_factory=dict)
    browser_fetches: list[tuple[int, str]] = field(default_factory=list)
    http_fetches: list[tuple[str, FetchPolicy]] = field(default_factory=list)
    policies: list[FetchPolicy] = field(default_factory=list)  # of the browser's fetches
    sessions: int = 0

    def answer(self, url: str, method: str = "http") -> FetchResult:
        status, body = self.pages.get(url, (404, b"gone"))
        return self.fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found", method=method)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url in self.raising:
            raise Crash("the rung raised")
        self.http_fetches.append((url, policy))
        return self.answer(url)

    @asynccontextmanager
    async def launch(self) -> AsyncIterator[Session]:
        self.sessions += 1
        yield Session(self.sessions)

    async def in_browser(
        self, session: Session, url: str, policy: FetchPolicy, export: CookieExport | None = None
    ) -> FetchResult:
        self.browser_fetches.append((session.number, url))
        self.policies.append(policy)
        if url in self.crashing:
            session.connected = False
            return self.fetch_result(url, 0, b"", block_class="error", error="browser crashed", method="browser")
        if url in self.renders:
            return self.fetch_result(url, 200, self.renders[url], method="browser")
        result = self.answer(url, "browser")
        files = {**({"screenshot.png": b"png " + url.encode()} if policy.screenshot else {})}
        return result.model_copy(update={"artifacts": files})


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    browser = SharedBrowser(web.launch, web.in_browser, lambda session: session.connected)
    rungs = Rungs(http=web.http, browser=browser.fetch)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def _batch(urls: list[str], *formats: str, **members: Any) -> BatchScrapeRequest:
    return BatchScrapeRequest.model_validate({"urls": urls, "formats": list(formats), **members})


async def _run(
    engine: AsyncEngine, fetching: Fetching, data: EngineData | None, *job_ids: JobId, llm: LLMClient = NO_LLM
) -> None:
    """Run a worker loop with the worker's handlers until every one of the jobs has ended; role C runs on `llm`."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, task_handlers(fetching, data, None, llm=llm), stop))
    async with asyncio.timeout(60):
        while not await _ended(engine, job_ids):
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def _ended(engine: AsyncEngine, job_ids: tuple[JobId, ...]) -> bool:
    async with engine.connect() as conn:
        statuses = (await conn.execute(select(Job.status).where(Job.id.in_(job_ids)))).scalars().all()
    return all(status in ("completed", "failed", "cancelled") for status in statuses)


async def _results(engine: AsyncEngine, fetching: Fetching, job_id: JobId, **query: Any) -> Any:
    async with engine.connect() as conn:
        return await jobs.job_results(conn, job_id, ResultsQuery(**query), store=fetching.store)


async def _summary(engine: AsyncEngine, job_id: JobId) -> jobs.JobSummary:
    async with engine.connect() as conn:
        return await jobs.get_job(conn, job_id)


# Submitting.


async def test_a_submitted_batch_is_a_queued_job_with_one_task_per_canonical_url(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    urls = [f"{own_origin}/a", f"{own_origin}/b", f"{own_origin}/a#reviews", f"{own_origin}/c"]

    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)

    summary = await _summary(engine, submitted.job_id)
    async with engine.connect() as conn:
        tasks = (await conn.execute(select(UrlTask.url).where(UrlTask.job_id == submitted.job_id))).scalars().all()
        job = (await conn.execute(select(Job).where(Job.id == submitted.job_id))).one()
    assert (summary.kind, summary.status, summary.counts.queued) == ("batch_scrape", "queued", 3)
    assert sorted(tasks) == [f"{own_origin}/a", f"{own_origin}/b", f"{own_origin}/c"]
    assert (job.schema_id, job.pinned, job.request["formats"]) == (None, None, ["markdown"])


@pytest.mark.parametrize(
    ("member", "url"),
    [("urls", f"https://{PRIVATE_HOST}/x"), ("webhook_url", f"https://{PRIVATE_HOST}/hook")],
)
async def test_a_refused_target_queues_nothing(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, member: str, url: str
) -> None:
    urls = [f"{own_origin}/a", url] if member == "urls" else [f"{own_origin}/a"]
    batch = _batch(urls, "markdown", **({"webhook_url": url} if member == "webhook_url" else {}))

    with pytest.raises(TargetsRejected) as rejected:
        await submit_batch(engine, fetching.connector, batch, data=None)

    assert rejected.value.member == ("urls[1]" if member == "urls" else "webhook_url")
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "batch_scrape"))).all() == []


# Running.


@pytest.mark.usefixtures("site")
async def test_page_outputs_are_made_from_each_tasks_capture_and_paginate(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red", "gone")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[1]] = (200, _page("Red kettle"))
    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown", "links"), data=None)

    await _run(engine, fetching, None, submitted.job_id)

    summary = await _summary(engine, submitted.job_id)
    first = await _results(engine, fetching, submitted.job_id, limit=2)
    second = await _results(engine, fetching, submitted.job_id, limit=2, cursor=first.next_cursor)
    assert (summary.status, summary.counts.done, summary.outcomes.extracted, summary.outcomes.not_found) == (
        "completed",
        3,
        2,
        1,
    )
    assert isinstance(first, PageOutputPage)
    assert isinstance(second, PageOutputPage)
    assert second.next_cursor is None
    blue, red, gone = first.items + second.items
    assert [item.url for item in (blue, red, gone)] == urls
    assert [item.outcome for item in (blue, red, gone)] == ["extracted", "extracted", "not_found"]
    assert blue.markdown is not None
    assert "boils water quickly" in blue.markdown
    assert blue.links == red.links == [f"{own_origin}/kettles/other"]
    assert (gone.capture_id is not None, gone.markdown, gone.links) == (True, None, None)
    assert (blue.html, blue.raw_html, blue.metadata) == (None, None, None)


# INV-28: settings pinned at submit.


# INV-31: one task's failure never fails another.


async def _last_attempt(engine: AsyncEngine, url: str) -> None:
    """Make the next claim of `url`'s task its last attempt, so a transient failure ends it."""
    async with engine.begin() as conn:
        await conn.execute(update(UrlTask).where(UrlTask.url == url).values(attempts=MAX_ATTEMPTS - 1))


@pytest.mark.usefixtures("site")
async def test_a_task_that_raises_fails_alone(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "broken", "red")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[2]] = (200, _page("Red kettle"))
    web.raising.add(urls[1])
    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)
    await _last_attempt(engine, urls[1])

    await _run(engine, fetching, None, submitted.job_id)

    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.url, UrlTask.status, UrlTask.last_error).where(UrlTask.job_id == submitted.job_id)
        )
        tasks = {row.url: (row.status, row.last_error) for row in rows}
    assert tasks == {
        urls[0]: ("done", None),
        urls[1]: ("failed", "Crash: the rung raised"),
        urls[2]: ("done", None),
    }
    assert (await _summary(engine, submitted.job_id)).status == "completed"


# The request context and cache modes per page (D-1432, D-1435, D-1439).
