"""The scheduler loop against a real Postgres, with committed data (SPEC-01 §4.3)."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.core.settings import Settings
from crawlerai.db.models import Job, JobEvent, JobId, Project, UrlTask
from crawlerai.db.queue import claim_tasks
from crawlerai.scheduler.loop import PERIODIC, Periodic, run_scheduler

pytestmark = pytest.mark.anyio

QUICK = timedelta(milliseconds=50)


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
    engine: AsyncEngine, entries: Sequence[Periodic], done: Callable[[], Awaitable[bool]]
) -> None:
    """Run the scheduler until `done()` holds, then stop it and wait for it to exit."""
    stop = asyncio.Event()
    loop = asyncio.create_task(run_scheduler(_settings(engine), entries, stop))
    async with asyncio.timeout(60):
        while not await done():
            await asyncio.sleep(0.05)
        stop.set()
        await loop


async def test_the_scheduler_requeues_tasks_whose_lease_expired(engine: AsyncEngine) -> None:
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

    await _scheduler_until(engine, PERIODIC, requeued)

    assert await statuses() == {expired.id: ("queued", "lease expired"), live.id: ("claimed", None)}


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


async def test_stopping_ends_the_scheduler_while_it_waits(engine: AsyncEngine) -> None:
    ran = asyncio.Event()

    async def hourly(conn: AsyncConnection) -> None:
        ran.set()

    async def started() -> bool:
        return ran.is_set()

    async with asyncio.timeout(10):
        await _scheduler_until(engine, [Periodic("hourly", timedelta(hours=1), hourly)], started)
