"""The queue and the worker loop across several connections, with committed data (persistence-storage spec)."""

import asyncio
import threading
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
from crawlerai.worker.loop import DEADLINE, TASK_SLOTS, Failed, Finished, TaskHandler, TaskResult, run_worker

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
    # Every claimer has made its first claim before any claims again: 8 first claims take 56 of the 1000 tasks, so each
    # takes some, whatever the order the event loop runs them in.
    first_claims_made = asyncio.Barrier(8)

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

    batches = await asyncio.gather(*(claimer(f"w{i}") for i in range(8)))

    claims = Counter(task_id for batch in batches for task_id in batch)
    assert claims == Counter(ids)
    assert max(sizes) == 7
    assert all(batches)


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


async def test_a_retry_result_requeues_the_task_until_its_attempts_run_out(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 1)

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
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


async def test_a_worker_runs_up_to_its_slots_of_tasks_at_once(engine: AsyncEngine) -> None:
    job_id, _ = await _job(engine, 2 * TASK_SLOTS)
    running = 0
    most = 0

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.2)
        running -= 1
        return Finished("extracted")

    await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))

    assert most == TASK_SLOTS
    assert await _job_state(engine, job_id) == ("completed", ["completed"])


async def test_a_task_past_its_deadline_fails_and_its_job_moves_on(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(loop, "TASK_DEADLINE", timedelta(seconds=1))
    monkeypatch.setattr(loop, "CANCEL_GRACE", timedelta(seconds=1))
    job_id, [stuck_on_loop, left_behind, *rest] = await _job(engine, TASK_SLOTS + 2)
    released = threading.Event()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        if task.id == stuck_on_loop:
            await asyncio.Event().wait()  # a wait that never ends
        if task.id == left_behind:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.to_thread(released.wait)  # ignores its cancellation: the worker leaves it behind
        return Finished("extracted")

    try:
        await _run_until(engine, {"crawl": handler}, _job_ended(engine, job_id))
        assert loop._LEFT_BEHIND
    finally:
        released.set()
        await asyncio.gather(*loop._LEFT_BEHIND)  # its late result finds the lease gone and changes nothing

    async with engine.connect() as conn:
        found = await conn.execute(select(UrlTask.id, UrlTask.status, UrlTask.outcome))
        rows = {task_id: (status, outcome) for task_id, status, outcome in found}
        errors = (await conn.execute(select(UrlTask.last_error).where(UrlTask.status == "failed"))).scalars().all()
    assert {rows[stuck_on_loop], rows[left_behind]} == {("failed", "failed")}
    assert {rows[task_id] for task_id in rest} == {("done", "extracted")}
    assert errors == [DEADLINE, DEADLINE]
    assert (await _job_state(engine, job_id))[0] == "completed"
