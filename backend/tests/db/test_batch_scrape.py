"""`batch_scrape` jobs: submitted through the batch service, run by worker loops through the real queue,
and read back through the jobs service; with the settings pinned at submit and each task isolated from the
others."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.core.capture import CaptureMethod
from snowcrawl.core.settings import Settings
from snowcrawl.db.models import (
    Job,
    JobId,
    UrlTask,
)
from snowcrawl.db.queue import MAX_ATTEMPTS, ClaimedTask
from snowcrawl.llm.client import NO_LLM, LLMClient
from snowcrawl.resolve.pipeline import EngineData
from snowcrawl.services import jobs
from snowcrawl.services.batch import BatchScrapeRequest, submit_batch
from snowcrawl.services.fetching import Fetching, TargetsRejected
from snowcrawl.services.jobs import PageOutputPage, ResultsQuery
from snowcrawl.services.page_run import Page
from snowcrawl.services.page_task import NotReached
from snowcrawl.worker.handlers import scrape as scrape_handler
from snowcrawl.worker.handlers import steps
from snowcrawl.worker.handlers.table import task_handlers
from snowcrawl.worker.loop import run_worker
from tests.db.support import PRIVATE_HOST
from tests.db.support import Web as SharedWeb

pytestmark = pytest.mark.anyio


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
class Web(SharedWeb):
    """`SharedWeb`, where the HTTP rung raises for a URL in `raising`."""

    raising: set[str] = field(default_factory=set)

    async def fetch(self, method: CaptureMethod, url: str, policy: FetchPolicy) -> FetchResult:
        if method == "http" and url in self.raising:
            raise Crash("the rung raised")
        return await super().fetch(method, url, policy)


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web.site(fetch_result, own_origin)


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
    [("urls", "https://10.0.0.7/x"), ("webhook_url", f"https://{PRIVATE_HOST}/hook")],
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
    web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[1], _page("Red kettle"))
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


# Settings pinned at submit.


# One task's failure never fails another.


async def _last_attempt(engine: AsyncEngine, url: str) -> None:
    """Make the next claim of `url`'s task its last attempt, so a transient failure ends it."""
    async with engine.begin() as conn:
        await conn.execute(update(UrlTask).where(UrlTask.url == url).values(attempts=MAX_ATTEMPTS - 1))


@pytest.mark.usefixtures("site")
async def test_a_task_that_raises_fails_alone(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "broken", "red")]
    web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[2], _page("Red kettle"))
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


@pytest.mark.usefixtures("site")
async def test_tasks_of_one_site_hold_none_of_its_rows_across_their_transactions(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each task waits in its transaction, after its fetch, until the other is in its own: a row of the site's memory
    # that a task's transaction held (the contract its fetch taught) would keep the other out until it timed out.
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red")]
    for url in urls:
        web.serve(url, _page("Kettle"))
    both, timed_out = asyncio.Barrier(2), []
    count_fetch = steps.count_fetch

    async def count_side_by_side(conn: AsyncConnection, task: ClaimedTask, page: Page | NotReached) -> None:
        if isinstance(page, Page):  # a task postponed for its host's turn fetched nothing yet
            try:
                async with asyncio.timeout(10):
                    await both.wait()
            except TimeoutError:
                timed_out.append(task.url)
                raise
        await count_fetch(conn, task, page)

    monkeypatch.setattr(scrape_handler, "count_fetch", count_side_by_side)
    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)

    await _run(engine, fetching, None, submitted.job_id)

    summary = await _summary(engine, submitted.job_id)
    assert (timed_out, summary.status, summary.outcomes.extracted) == ([], "completed", 2)


# The request context and cache modes per page.
