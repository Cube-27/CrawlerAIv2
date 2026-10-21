"""The queue and the worker loop across several connections, with committed data (persistence-storage spec)."""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.core.settings import Settings
from crawlerai.db.models import Job, JobEvent, JobId, JobKind, JobStatus, Project, UrlTask, UrlTaskId
from crawlerai.db.queue import MAX_ATTEMPTS, ClaimedTask, claim_tasks
from crawlerai.worker import loop
from crawlerai.worker.loop import Failed, Finished, Settle, TaskHandler, TaskResult, run_worker

pytestmark = pytest.mark.anyio


async def _job(engine: AsyncEngine, count: int, **columns: Any) -> tuple[JobId, list[UrlTaskId]]:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "crawl", "request": {}, "engine_version": "0+cal.0"}
    async with engine.begin() as conn:
        job_id: JobId = (await conn.execute(insert(Job).values(**values, **columns).returning(Job.id))).scalar_one()
        urls = [f"https://example.test/p/{i}" for i in range(count)]
        rows = [{"job_id": job_id, "url": url, "canonical_url": url} for url in urls]
        ids = await conn.execute(insert(UrlTask).returning(UrlTask.id, sort_by_parameter_order=True), rows)
        return job_id, list(ids.scalars())


def _settings(engine: AsyncEngine, **values: Any) -> Settings:
    url = engine.url.render_as_string(hide_password=False)
    return Settings(database_url=SecretStr(url), object_store="fs:///unused", **values)


async def _tasks(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.status, UrlTask.outcome, UrlTask.attempts, UrlTask.last_error).order_by(UrlTask.id)
        )
        return list(rows)


async def _job_state(engine: AsyncEngine, job_id: JobId) -> tuple[JobStatus, list[str]]:
    async with engine.connect() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
        events = (await conn.execute(select(JobEvent.kind).where(JobEvent.job_id == job_id))).scalars().all()
        return status, list(events)


# `_run_until` gives up after this long; the tests that use it carry a pytest timeout a little above it.
_RUN_BOUND_S = 300
_TEST_TIMEOUT_S = _RUN_BOUND_S + 30


async def _run_until(
    engine: AsyncEngine,
    handlers: Mapping[JobKind, TaskHandler],
    done: Callable[[], Awaitable[bool]],
    *,
    workers: int = 1,
    **settings: Any,
) -> None:
    """Run `workers` worker loops until `done()` holds, then stop them and wait for them to exit."""
    stop = asyncio.Event()
    loops = [asyncio.create_task(run_worker(_settings(engine, **settings), handlers, stop)) for _ in range(workers)]
    async with asyncio.timeout(_RUN_BOUND_S):
        while not await done():
            await asyncio.sleep(0.1)
        stop.set()
        await asyncio.gather(*loops)


def _job_ended(engine: AsyncEngine, job_id: JobId) -> Callable[[], Awaitable[bool]]:
    async def ended() -> bool:
        return (await _job_state(engine, job_id))[0] in ("completed", "failed", "cancelled")

    return ended


async def test_2_claimers_take_20_tasks_each_exactly_once_and_at_most_7_a_claim(engine: AsyncEngine) -> None:
    # The model (tools/verify/worker_queue) takes claim_tasks as one atomic step; this grounds that assumption in
    # PostgreSQL itself: concurrent FOR UPDATE SKIP LOCKED claims never lease one task twice nor more than `n`.
    _, ids = await _job(engine, 20)
    sizes: list[int] = []
    # Every claimer has made its first claim before any claims again: 2 first claims take 14 of the 20 tasks, so each
    # takes some, whatever the order the event loop runs them in.
    first_claims_made = asyncio.Barrier(2)

    async def claimer(worker: str) -> list[UrlTaskId]:
        claimed: list[UrlTaskId] = []
        first = True
        async with engine.connect() as conn:
            while True:
                async with conn.begin():
                    batch = await claim_tasks(conn, worker, 7)
                if first:
                    first = False
                    await first_claims_made.wait()
                if not batch:
                    return claimed
                sizes.append(len(batch))
                claimed += [task.id for task in batch]

    batches = await asyncio.gather(*(claimer(f"w{i}") for i in range(2)))

    claims = Counter(task_id for batch in batches for task_id in batch)
    assert claims == Counter(ids)
    assert max(sizes) == 7
    assert all(batches)


@pytest.mark.timeout(_TEST_TIMEOUT_S)
async def test_tasks_of_a_cancelled_job_are_not_run(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 3, status="running", cancel_requested=True)
    runs: list[UrlTaskId] = []

    async def handler(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        runs.append(task.id)
        return Finished("extracted")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert runs == []
    assert await _job_state(engine, job_id) == ("cancelled", ["cancelled"])
    assert [row.status for row in await _tasks(engine)] == ["cancelled"] * 3


@pytest.mark.timeout(_TEST_TIMEOUT_S)
async def test_a_retry_result_requeues_the_task_until_its_attempts_run_out(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    async def handler(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        return Failed("http 429", transient=True, after=timedelta(0), exhausted="blocked")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert await _tasks(engine) == [("done", "blocked", MAX_ATTEMPTS, "http 429")]


@pytest.mark.parametrize(
    ("redact", "last_error"),
    [
        (False, "RuntimeError: fetching https://example.test/p/0?q=1 timed out"),
        (True, "RuntimeError: fetching <url> timed out"),
    ],
)
@pytest.mark.timeout(_TEST_TIMEOUT_S)
async def test_a_handler_exception_is_recorded_and_the_task_retried(
    engine: AsyncEngine, redact: bool, last_error: str
) -> None:
    await _job(engine, 1)
    stop_after_one = asyncio.Event()

    async def handler(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        stop_after_one.set()
        raise RuntimeError(f"fetching {task.url}?q=1 timed out")

    async def ran() -> bool:
        return stop_after_one.is_set() and (await _tasks(engine))[0].status == "queued"

    await _run_until(engine, {"crawl": handler}, ran, log_redact_urls=redact)

    assert await _tasks(engine) == [("queued", None, 1, last_error)]


@pytest.mark.timeout(_TEST_TIMEOUT_S)
async def test_work_of_a_task_whose_lease_was_lost_is_rolled_back(engine: AsyncEngine) -> None:
    job_id, [task_id] = await _job(engine, 1)
    ran = asyncio.Event()

    async def handler(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        async def settle(conn: AsyncConnection) -> TaskResult:
            await conn.execute(insert(JobEvent).values(job_id=task.job_id, kind="handler_wrote"))
            async with engine.begin() as other:
                await other.execute(update(UrlTask).values(claimed_by="another-worker"))
            ran.set()
            return Finished("extracted")

        return settle

    async def handled() -> bool:
        return ran.is_set()

    await _run_until(engine, {"crawl": handler}, handled)

    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.status, UrlTask.claimed_by).where(UrlTask.id == task_id))).one()
    assert task == ("claimed", "another-worker")
    assert await _job_state(engine, job_id) == ("running", [])


async def test_work_left_behind_holding_its_row_has_its_session_ended_and_its_task_fails(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "TASK_DEADLINE", timedelta(seconds=1))
    monkeypatch.setattr(loop, "CANCEL_GRACE", timedelta(seconds=0.5))
    monkeypatch.setattr(loop, "_LOCK_WAIT", timedelta(seconds=5))
    job_id, _ = await _job(engine, 1)
    release = asyncio.Event()

    async def handler(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        async def settle(conn: AsyncConnection) -> TaskResult:
            # Its row locked in its open transaction, the work ignores its cancellation until released.
            await conn.execute(update(UrlTask).where(UrlTask.id == task.id).values(priority=UrlTask.priority))
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await release.wait()
            return Finished("extracted")

        return settle

    async with asyncio.timeout(30):
        await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))
    release.set()
    left = set(loop._LEFT_BEHIND)
    await asyncio.wait(left, timeout=10)
    assert all(work.done() for work in left)

    [(status, _, attempts, last_error)] = await _tasks(engine)
    assert (status, attempts, last_error) == ("failed", 1, loop.DEADLINE)
    assert (await _job_state(engine, job_id))[0] == "failed"
