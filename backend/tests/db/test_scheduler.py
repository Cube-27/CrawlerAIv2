"""The scheduler loop against a real Postgres, with committed data (persistence-storage spec)."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.jobs import transition_job
from crawlerai.db.keys import create_key
from crawlerai.db.models import (
    ApiKey,
    Job,
    JobEvent,
    JobId,
    Project,
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
