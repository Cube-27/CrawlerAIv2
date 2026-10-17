"""The scheduler loop against a real Postgres, with committed data (SPEC-01 §4.3)."""

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.jobs import transition_job
from crawlerai.db.keys import create_key
from crawlerai.db.models import (
    ApiKey,
    Capture,
    Job,
    JobEvent,
    JobId,
    ProgressiveState,
    Project,
    SchemaDef,
    Site,
    SiteFetchMethod,
    UrlTask,
    WebhookDelivery,
    WebhookEvent,
)
from crawlerai.db.queue import claim_tasks
from crawlerai.llm.client import NO_LLM
from crawlerai.scheduler.loop import Periodic, periodic, run_scheduler
from crawlerai.services.fetching import Fetching
from crawlerai.services.schedules import Submitting
from crawlerai.storage.fs import FsStore
from tests.db.conftest import resolve

pytestmark = pytest.mark.anyio

QUICK = timedelta(milliseconds=50)


async def _no_post(url: str, body: bytes, headers: Mapping[str, str]) -> int:
    raise AssertionError("no webhook is due")


async def _no_fetch(url: str, policy: FetchPolicy) -> FetchResult:
    raise AssertionError("no site is due for a fetch-method re-check")


# No schedule is due in these tests but in the one that makes one, which refuses no target and fetches nothing.
_SUBMITTING = Submitting(
    Fetching(Rungs(http=_no_fetch, browser=_no_fetch), SafeConnector(resolve), FsStore(Path("unused")), HostLimiter()),
    None,
    NO_LLM,
)


async def _job(engine: AsyncEngine, count: int) -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "crawl", "request": {}, "engine_version": "0+cal.0"}
    async with engine.begin() as conn:
        job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
        urls = [f"https://example.test/p/{i}" for i in range(count)]
        if urls:
            rows = [{"job_id": job_id, "url": url, "canonical_url": url} for url in urls]
            await conn.execute(insert(UrlTask), rows)
        return job_id


def _settings(engine: AsyncEngine) -> Settings:
    url = engine.url.render_as_string(hide_password=False)
    return Settings(database_url=SecretStr(url), object_store="fs:///unused")


async def _scheduler_until(
    engine: AsyncEngine, entries: Sequence[Periodic], done: Callable[[], Awaitable[bool]], *, timeout: float = 60
) -> None:
    """Run the scheduler until `done()` holds, then stop it and wait for it to exit, all within `timeout` seconds."""
    stop = asyncio.Event()
    loop = asyncio.create_task(run_scheduler(_settings(engine), entries, stop))
    async with asyncio.timeout(timeout):
        while not await done():
            await asyncio.sleep(0.05)
        stop.set()
        await loop


async def test_the_scheduler_requeues_tasks_whose_lease_expired(engine: AsyncEngine, tmp_path: Path) -> None:
    await _job(engine, 2)
    async with engine.begin() as conn:
        expired, live = await claim_tasks(conn, "a-worker-that-died", 2)
        past = func.now() - timedelta(seconds=1)
        await conn.execute(update(UrlTask).where(UrlTask.id == expired.id).values(lease_until=past))

    async def statuses() -> dict[Any, tuple[str, str | None]]:
        async with engine.connect() as conn:
            rows = await conn.execute(select(UrlTask.id, UrlTask.status, UrlTask.last_error))
            return {row.id: (row.status, row.last_error) for row in rows}

    async def requeued() -> bool:
        return (await statuses())[expired.id][0] == "queued"

    await _scheduler_until(engine, periodic(FsStore(tmp_path), _no_fetch, _no_post, _SUBMITTING), requeued)

    assert await statuses() == {expired.id: ("queued", "lease expired"), live.id: ("claimed", None)}


async def test_the_scheduler_expires_production_captures_past_expires_at(engine: AsyncEngine, tmp_path: Path) -> None:
    store = FsStore(tmp_path)
    key = "captures/2026/09/expired.bundle.zst"
    store.put(key, b"blob")
    url = "https://example.test/p/1"
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    async with engine.begin() as conn:
        site_id = (
            await conn.execute(
                insert(Site).values(project_id=default_project, host="retention.example.test").returning(Site.id)
            )
        ).scalar_one()
        await conn.execute(
            insert(Capture).values(
                site_id=site_id,
                url=url,
                final_url=url,
                method="http",
                status_code=200,
                fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
                block_class="ok",
                object_key=key,
                html_sha256="0" * 64,
                size_bytes=4,
                duration_ms=5,
                expires_at=func.now() - timedelta(seconds=1),
            )
        )

    async def expired() -> bool:
        async with engine.connect() as conn:
            return (await conn.execute(select(func.count()).where(Capture.site_id == site_id))).scalar_one() == 0

    try:
        await _scheduler_until(engine, periodic(store, _no_fetch, _no_post, _SUBMITTING), expired)
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Capture).where(Capture.site_id == site_id))
            await conn.execute(delete(Site).where(Site.id == site_id))

    assert store.list("") == []


async def test_entries_repeat_at_their_interval_and_a_failing_one_neither_stops_the_others_nor_commits(
    engine: AsyncEngine,
) -> None:
    job_id = await _job(engine, 0)
    runs: Counter[str] = Counter()

    async def count(conn: AsyncConnection) -> None:
        runs["count"] += 1

    async def fail(conn: AsyncConnection) -> None:
        runs["fail"] += 1
        await conn.execute(insert(JobEvent).values(job_id=job_id, kind="written_then_failed"))
        raise RuntimeError("boom")

    async def hourly(conn: AsyncConnection) -> None:
        runs["hourly"] += 1

    async def repeated() -> bool:
        return runs["count"] >= 3 and runs["fail"] >= 3

    entries = [
        Periodic("fail", QUICK, fail),
        Periodic("count", QUICK, count),
        Periodic("hourly", timedelta(hours=1), hourly),
    ]
    await _scheduler_until(engine, entries, repeated)

    assert runs["hourly"] == 1
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(JobEvent))).scalar_one() == 0


async def test_a_batched_entry_that_fills_its_batch_runs_again_at_once_until_its_backlog_drains(
    engine: AsyncEngine,
) -> None:
    backlog = [2, 2, 1]
    runs: list[int] = []

    async def drain(conn: AsyncConnection) -> int:
        runs.append(backlog.pop(0) if backlog else 0)
        return runs[-1]

    async def drained() -> bool:
        return not backlog

    await _scheduler_until(engine, [Periodic("drain", timedelta(hours=1), drain, batch=2)], drained, timeout=10)

    assert runs == [2, 2, 1]


async def test_the_scheduler_logs_its_start_and_each_entry_that_did_work(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
) -> None:
    results = [3, 0]

    async def drain(conn: AsyncConnection) -> int:
        return results.pop(0) if results else 0

    async def drained() -> bool:
        return not results

    with caplog.at_level(logging.INFO, logger="crawlerai.scheduler.loop"):
        await _scheduler_until(engine, [Periodic("drain", QUICK, drain)], drained, timeout=10)

    # An entry that found nothing to do logs nothing at INFO: entries run every few seconds.
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO] == [
        "scheduler: started; entries drain",
        "scheduler: drain: 3",
    ]


async def test_the_scheduler_sets_a_browser_site_back_to_http_once_http_passes(
    engine: AsyncEngine, tmp_path: Path, fetch_result: Callable[..., FetchResult]
) -> None:
    url = "https://recheck.example.test/p/1"
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    async with engine.begin() as conn:
        site_id = (
            await conn.execute(
                insert(Site).values(project_id=default_project, host="recheck.example.test").returning(Site.id)
            )
        ).scalar_one()
        never_checked = func.now() - timedelta(days=30)
        memory = {"site_id": site_id, "page_kind": "detail", "method": "browser", "checked_at": never_checked}
        await conn.execute(insert(SiteFetchMethod).values(**memory))
        await conn.execute(
            insert(Capture).values(
                site_id=site_id,
                url=url,
                final_url=url,
                method="browser",
                status_code=200,
                fetched_at=func.now(),
                block_class="ok",
                object_key="captures/2026/10/recheck.bundle.zst",
                html_sha256="0" * 64,
                size_bytes=4,
                duration_ms=5,
            )
        )
    fetched: list[str] = []

    async def fetch(fetched_url: str, policy: FetchPolicy) -> FetchResult:
        fetched.append(fetched_url)
        return fetch_result(fetched_url, 200, b"" if fetched_url.endswith("/robots.txt") else b"<p>page</p>")

    async def on_http() -> bool:
        async with engine.connect() as conn:
            query = select(SiteFetchMethod.method).where(SiteFetchMethod.site_id == site_id)
            method = (await conn.execute(query)).scalar_one()
            return bool(method == "http")

    try:
        await _scheduler_until(engine, periodic(FsStore(tmp_path), fetch, _no_post, _SUBMITTING), on_http)
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(Capture).where(Capture.site_id == site_id))
            await conn.execute(delete(SiteFetchMethod).where(SiteFetchMethod.site_id == site_id))
            await conn.execute(delete(Site).where(Site.id == site_id))

    assert fetched == ["https://recheck.example.test/robots.txt", url]


async def test_the_scheduler_starts_learning_for_a_state_with_eight_extracted_pages(
    engine: AsyncEngine, tmp_path: Path, own_origin: str, schema_name: str
) -> None:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    schema = {"name": schema_name, "page_kind": "detail", "fields": {}, "origin": "user"}
    async with engine.begin() as conn:
        host = own_origin.removeprefix("https://")
        site_id = (
            await conn.execute(insert(Site).values(project_id=default_project, host=host).returning(Site.id))
        ).scalar_one()
        schema_id = (
            await conn.execute(insert(SchemaDef).values(**schema, status="active").returning(SchemaDef.id))
        ).scalar_one()
        key = {"site_id": site_id, "schema_id": schema_id, "page_kind": "detail"}
        await conn.execute(insert(ProgressiveState).values(**key, pages_extracted=8))

    async def learn_job() -> bool:
        async with engine.connect() as conn:
            jobs = select(Job.status).where(Job.kind == "learn", Job.schema_id == schema_id)
            return list((await conn.execute(jobs)).scalars()) == ["queued"]

    await _scheduler_until(engine, periodic(FsStore(tmp_path), _no_fetch, _no_post, _SUBMITTING), learn_job)

    async with engine.connect() as conn:
        mode = select(ProgressiveState.mode).where(ProgressiveState.schema_id == schema_id)
        assert (await conn.execute(mode)).scalar_one() == "learning"


async def test_the_scheduler_delivers_an_ended_jobs_webhook(engine: AsyncEngine, tmp_path: Path) -> None:
    async with engine.begin() as conn:
        key = await create_key(conn, "scheduler-webhook-test")
    job_id = await _job(engine, 0)
    hook = "https://hooks.example.test/done"
    async with engine.begin() as conn:
        await conn.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status="running", webhook_url=hook, webhook_events=["job_completed"], api_key_id=key.id)
        )
        await transition_job(conn, job_id, "completed")
    sent: list[str] = []

    async def post(url: str, body: bytes, headers: Mapping[str, str]) -> int:
        sent.append(url)
        return 200

    async def delivered() -> bool:
        async with engine.connect() as conn:
            status = select(WebhookDelivery.status).where(WebhookDelivery.job_id == job_id)
            return (await conn.execute(status)).scalar_one_or_none() == "delivered"

    try:
        await _scheduler_until(engine, periodic(FsStore(tmp_path), _no_fetch, post, _SUBMITTING), delivered)
    finally:
        async with engine.begin() as conn:
            for model in (WebhookEvent, WebhookDelivery, JobEvent, UrlTask):
                await conn.execute(delete(model).where(model.job_id == job_id))
            await conn.execute(delete(Job).where(Job.id == job_id))
            await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))

    assert sent == [hook]
