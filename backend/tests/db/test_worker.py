"""The queue and the worker loop across several connections, with committed data (SPEC-01 §6, §7)."""

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
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskHandler, TaskResult, run_worker

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
    async with asyncio.timeout(300):
        while not await done():
            await asyncio.sleep(0.1)
        stop.set()
        await asyncio.gather(*loops)


def _job_ended(engine: AsyncEngine, job_id: JobId) -> Callable[[], Awaitable[bool]]:
    async def ended() -> bool:
        return (await _job_state(engine, job_id))[0] in ("completed", "failed", "cancelled")

    return ended


async def test_8_claimers_take_1000_tasks_each_exactly_once_and_at_most_7_a_claim(engine: AsyncEngine) -> None:
    _, ids = await _job(engine, 1000)
    sizes: list[int] = []

    async def claimer(worker: str) -> list[UrlTaskId]:
        claimed: list[UrlTaskId] = []
        async with engine.connect() as conn:
            while True:
                async with conn.begin():
                    batch = await claim_tasks(conn, worker, 7)
                if not batch:
                    return claimed
                sizes.append(len(batch))
                claimed += [task.id for task in batch]

    batches = await asyncio.gather(*(claimer(f"w{i}") for i in range(8)))

    claims = Counter(task_id for batch in batches for task_id in batch)
    assert claims == Counter(ids)
    assert max(sizes) == 7
    assert sum(1 for batch in batches if batch) > 1


async def test_10k_tasks_drain_through_4_workers_with_no_double_claims(engine: AsyncEngine) -> None:
    job_id, ids = await _job(engine, 10_000)
    runs: Counter[UrlTaskId] = Counter()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        runs[task.id] += 1
        return Finished("extracted")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id), workers=4)

    assert runs == Counter(ids)
    assert Counter(row[:3] for row in await _tasks(engine)) == {("done", "extracted", 1): 10_000}
    assert await _job_state(engine, job_id) == ("completed", ["completed"])


async def test_tasks_of_a_cancelled_job_are_not_run(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 3, status="running", cancel_requested=True)
    runs: list[UrlTaskId] = []

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        runs.append(task.id)
        return Finished("extracted")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert runs == []
    assert await _job_state(engine, job_id) == ("cancelled", ["cancelled"])
    assert [row.status for row in await _tasks(engine)] == ["cancelled"] * 3


async def test_a_permanent_failure_result_fails_the_task_and_the_job(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        return Failed("budget_exhausted", transient=False)

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert await _tasks(engine) == [("failed", "failed", 1, "budget_exhausted")]
    assert await _job_state(engine, job_id) == ("failed", ["failed"])


async def test_a_finished_result_records_its_reason(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        return Finished("blocked", reason="robots")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert await _tasks(engine) == [("done", "blocked", 1, "robots")]


async def test_a_retry_result_requeues_the_task_until_its_attempts_run_out(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        return Failed("http 429", transient=True, after=timedelta(0), exhausted="blocked")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert await _tasks(engine) == [("done", "blocked", MAX_ATTEMPTS, "http 429")]


async def test_a_postponed_task_runs_later_without_spending_attempts(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)
    runs: list[int] = []

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        runs.append(task.attempts)
        return Postpone(timedelta(0)) if len(runs) < 5 else Finished("extracted")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert runs == [1, 1, 1, 1, 1]
    assert await _tasks(engine) == [("done", "extracted", 1, None)]


async def test_a_task_without_a_handler_for_its_job_kind_fails(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    await _run_until(engine, {}, _job_ended(engine, job_id))

    assert await _tasks(engine) == [("failed", "failed", 1, "no handler for job kind 'crawl'")]


@pytest.mark.parametrize(
    ("redact", "last_error"),
    [
        (False, "RuntimeError: fetching https://example.test/p/0?q=1 timed out"),
        (True, "RuntimeError: fetching <url> timed out"),
    ],
)
async def test_a_handler_exception_is_recorded_and_the_task_retried(
    engine: AsyncEngine, redact: bool, last_error: str
) -> None:
    await _job(engine, 1)
    stop_after_one = asyncio.Event()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        stop_after_one.set()
        raise RuntimeError(f"fetching {task.url}?q=1 timed out")

    async def ran() -> bool:
        return stop_after_one.is_set() and (await _tasks(engine))[0].status == "queued"

    await _run_until(engine, {"crawl": handler}, ran, log_redact_urls=redact)

    assert await _tasks(engine) == [("queued", None, 1, last_error)]


async def test_stopping_returns_claimed_tasks_that_did_not_start(engine: AsyncEngine) -> None:
    await _job(engine, 3)
    stop = asyncio.Event()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        stop.set()
        return Finished("extracted")

    await asyncio.wait_for(run_worker(_settings(engine), {"crawl": handler}, stop), 60)

    assert await _tasks(engine) == [("done", "extracted", 1, None)] + [("queued", None, 0, None)] * 2


async def test_work_of_a_task_whose_lease_was_lost_is_rolled_back(engine: AsyncEngine) -> None:
    job_id, [task_id] = await _job(engine, 1)
    ran = asyncio.Event()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        await conn.execute(insert(JobEvent).values(job_id=task.job_id, kind="handler_wrote"))
        async with engine.begin() as other:
            await other.execute(update(UrlTask).values(claimed_by="another-worker"))
        ran.set()
        return Finished("extracted")

    async def handled() -> bool:
        return ran.is_set()

    await _run_until(engine, {"crawl": handler}, handled)

    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.status, UrlTask.claimed_by).where(UrlTask.id == task_id))).one()
    assert task == ("claimed", "another-worker")
    assert await _job_state(engine, job_id) == ("running", [])
