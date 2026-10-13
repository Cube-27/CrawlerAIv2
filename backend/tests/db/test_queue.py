import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.db.models import Job, JobEvent, JobId, JobStatus, Project, UrlTask, UrlTaskId
from crawlerai.db.queue import (
    LEASE,
    MAX_ATTEMPTS,
    ClaimedTask,
    LeaseLost,
    cancel_task,
    claim_tasks,
    complete_task,
    fail_task,
    release_expired_leases,
    release_task,
)

pytestmark = pytest.mark.anyio


async def _job(conn: AsyncConnection, status: JobStatus = "running", **columns: Any) -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "crawl", "request": {}, "engine_version": "0+cal.0"}
    job_id: JobId = (
        await conn.execute(insert(Job).values(**values, status=status, **columns).returning(Job.id))
    ).scalar_one()
    return job_id


async def _tasks(conn: AsyncConnection, job_id: JobId, count: int, **columns: Any) -> list[UrlTaskId]:
    urls = [f"https://example.test/p/{i}" for i in range(count)]
    rows = [{"job_id": job_id, "url": url, "canonical_url": url, **columns} for url in urls]
    ids = (await conn.execute(insert(UrlTask).returning(UrlTask.id, sort_by_parameter_order=True), rows)).scalars()
    return list(ids)


async def _claim_one(conn: AsyncConnection, worker: str = "w1") -> ClaimedTask:
    [task] = await claim_tasks(conn, worker, 1)
    return task


async def _row(conn: AsyncConnection, task_id: UrlTaskId) -> Any:
    return (await conn.execute(select(UrlTask).where(UrlTask.id == task_id))).one()


async def _job_state(conn: AsyncConnection, job_id: JobId) -> tuple[str, list[str]]:
    status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    events = (await conn.execute(select(JobEvent.kind).where(JobEvent.job_id == job_id))).scalars().all()
    return status, list(events)


async def _now(conn: AsyncConnection) -> Any:
    return (await conn.execute(select(func.now()))).scalar_one()


async def _clock(conn: AsyncConnection) -> Any:
    return (await conn.execute(select(func.clock_timestamp()))).scalar_one()


async def _expire(conn: AsyncConnection, task: ClaimedTask) -> ClaimedTask:
    """Let `task`'s lease run out, as it would after `LEASE` with no word from its worker."""
    expired = await _now(conn) - timedelta(seconds=1)
    await conn.execute(update(UrlTask).where(UrlTask.id == task.id).values(lease_until=expired))
    return replace(task, lease_until=expired)


async def test_claim_takes_due_queued_tasks_by_priority_then_age(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    old, new, urgent = await _tasks(conn, job_id, 3)
    await conn.execute(update(UrlTask).where(UrlTask.id == urgent).values(priority=5))
    [not_due] = await _tasks(
        conn, job_id, 1, url="u", canonical_url="u", next_attempt_at=await _now(conn) + timedelta(1)
    )
    [done] = await _tasks(conn, job_id, 1, url="d", canonical_url="d", status="done")

    claimed = await claim_tasks(conn, "w1", 10)

    assert [task.id for task in claimed] == [urgent, old, new]
    assert not_due not in {task.id for task in claimed}
    assert done not in {task.id for task in claimed}


async def test_claim_leases_the_task_to_the_worker_and_counts_the_attempt(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1, attempts=1)

    task = await _claim_one(conn, "worker-a")

    row = await _row(conn, task_id)
    assert (row.status, row.claimed_by, row.attempts, row.lease_until) == ("claimed", "worker-a", 2, task.lease_until)
    assert (task.id, task.job_id, task.url, task.attempts, task.claimed_by) == (
        task_id,
        job_id,
        "https://example.test/p/0",
        2,
        "worker-a",
    )
    assert await _now(conn) + LEASE <= task.lease_until <= await _clock(conn) + LEASE


async def test_claim_takes_at_most_n_and_never_the_same_task_twice(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    ids = await _tasks(conn, job_id, 5)

    first = await claim_tasks(conn, "w1", 2)
    second = await claim_tasks(conn, "w2", 2)
    third = await claim_tasks(conn, "w3", 2)
    fourth = await claim_tasks(conn, "w4", 2)

    assert [[task.id for task in batch] for batch in (first, second, third, fourth)] == [
        ids[0:2],
        ids[2:4],
        ids[4:5],
        [],
    ]


async def test_claim_takes_at_most_n_when_the_planner_thinks_the_queue_is_tiny(conn: AsyncConnection) -> None:
    """Statistics taken while the queue held one task, as on a fresh database, lead Postgres to run the claim's
    `LIMIT n ... SKIP LOCKED` subquery once per scanned row; each run skips the rows already claimed and offers `n`
    more, so a claim could take every due task."""
    job_id = await _job(conn)
    [first] = await _tasks(conn, job_id, 1, url="a", canonical_url="a")
    await conn.execute(text("ANALYZE url_task"))
    rest = await _tasks(conn, job_id, 5)

    claimed = await claim_tasks(conn, "w1", 2)

    assert [task.id for task in claimed] == [first, rest[0]]


async def test_claiming_a_task_starts_its_queued_job(conn: AsyncConnection) -> None:
    job_id = await _job(conn, "queued")
    await _tasks(conn, job_id, 1)

    await _claim_one(conn)

    status, started_at = (await conn.execute(select(Job.status, Job.started_at))).one()
    assert (status, started_at) == ("running", await _now(conn))


async def test_completing_the_last_task_completes_the_job_once(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    first_id, second_id = await _tasks(conn, job_id, 2)
    first, second = await claim_tasks(conn, "w1", 2)

    await complete_task(conn, first, "extracted")
    assert await _job_state(conn, job_id) == ("running", [])

    await complete_task(conn, second, "no_match")

    assert await _job_state(conn, job_id) == ("completed", ["completed"])
    rows = [await _row(conn, task_id) for task_id in (first_id, second_id)]
    assert [(row.status, row.outcome, row.claimed_by) for row in rows] == [
        ("done", "extracted", "w1"),
        ("done", "no_match", "w1"),
    ]


async def test_a_transient_failure_requeues_with_exponential_backoff(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    now = await _now(conn)
    delays = []

    for _ in range(2):
        task = await _claim_one(conn)
        await fail_task(conn, task, "timeout", transient=True)
        row = await _row(conn, task_id)
        assert (row.status, row.outcome, row.last_error, row.claimed_by, row.lease_until) == (
            "queued",
            None,
            "timeout",
            None,
            None,
        )
        delays.append(row.next_attempt_at - now)
        # Make the task due again without waiting for the backoff.
        await conn.execute(update(UrlTask).values(next_attempt_at=func.now()))

    assert delays == [timedelta(seconds=30), timedelta(seconds=60)]
    assert await _job_state(conn, job_id) == ("running", [])


async def test_a_transient_failure_on_the_third_attempt_fails_the_task(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1, attempts=2)
    task = await _claim_one(conn)

    await fail_task(conn, task, "timeout", transient=True)

    row = await _row(conn, task_id)
    assert (row.status, row.outcome, row.attempts, row.last_error) == ("failed", "failed", 3, "timeout")
    assert await _job_state(conn, job_id) == ("failed", ["failed"])


async def test_a_permanent_failure_fails_the_task_at_once(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    task = await _claim_one(conn)

    await fail_task(conn, task, "budget_exhausted", transient=False)

    row = await _row(conn, task_id)
    assert (row.status, row.outcome, row.attempts, row.last_error) == ("failed", "failed", 1, "budget_exhausted")


async def test_a_job_with_one_success_and_one_failure_completes(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _tasks(conn, job_id, 2)
    first, second = await claim_tasks(conn, "w1", 2)

    await fail_task(conn, first, "boom", transient=False)
    await complete_task(conn, second, "blocked")

    assert await _job_state(conn, job_id) == ("completed", ["completed"])


async def test_last_error_is_cut_to_2_kb_on_a_character_boundary(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    task = await _claim_one(conn)

    await fail_task(conn, task, "x" + "é" * 2000, transient=False)

    assert (await _row(conn, task_id)).last_error == "x" + "é" * 1023


async def test_a_task_whose_lease_was_lost_cannot_be_finished(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    stale = await _claim_one(conn, "w1")
    # The lease expired, the task went back to the queue, and another worker claimed it.
    await conn.execute(update(UrlTask).values(status="queued", claimed_by=None, lease_until=None))
    await _claim_one(conn, "w2")

    with pytest.raises(LeaseLost, match=str(task_id)):
        await complete_task(conn, stale, "extracted")
    with pytest.raises(LeaseLost):
        await fail_task(conn, stale, "boom", transient=True)

    row = await _row(conn, task_id)
    assert (row.status, row.claimed_by, row.attempts) == ("claimed", "w2", 2)


async def test_the_same_worker_cannot_finish_its_earlier_claim_after_reclaiming(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _tasks(conn, job_id, 1)
    stale = await _claim_one(conn, "w1")
    await conn.execute(update(UrlTask).values(status="queued", claimed_by=None, lease_until=None))
    await _claim_one(conn, "w1")

    with pytest.raises(LeaseLost):
        await complete_task(conn, stale, "extracted")


async def test_cancelling_the_last_claimed_task_cancels_the_job(conn: AsyncConnection) -> None:
    job_id = await _job(conn, cancel_requested=True)
    claimed_id, queued_id = await _tasks(conn, job_id, 2)
    task = await _claim_one(conn)

    await cancel_task(conn, task)

    assert (await _row(conn, claimed_id)).status == "cancelled"
    assert (await _row(conn, queued_id)).status == "queued"
    assert await _job_state(conn, job_id) == ("cancelled", ["cancelled"])


async def test_finishing_a_task_of_an_ended_job_leaves_the_job_alone(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _tasks(conn, job_id, 1)
    task = await _claim_one(conn)
    await conn.execute(update(Job).values(status="cancelled"))

    await complete_task(conn, task, "extracted")

    assert await _job_state(conn, job_id) == ("cancelled", [])


async def test_releasing_an_unstarted_task_returns_it_without_spending_an_attempt(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    task = await _claim_one(conn)

    await release_task(conn, task)

    row = await _row(conn, task_id)
    assert (row.status, row.attempts, row.claimed_by, row.lease_until) == ("queued", 0, None, None)
    assert (await _claim_one(conn)).id == task_id


async def test_after_a_release_and_a_reclaim_by_the_same_worker_the_old_claim_cannot_finish(
    conn: AsyncConnection,
) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1)
    stale = await _claim_one(conn, "w1")
    await release_task(conn, stale)
    current = await _claim_one(conn, "w1")
    # Same worker, same attempt count: only the lease tells the two claims apart.
    assert (current.claimed_by, current.attempts) == (stale.claimed_by, stale.attempts)

    with pytest.raises(LeaseLost):
        await complete_task(conn, stale, "extracted")

    await complete_task(conn, current, "extracted")
    assert (await _row(conn, task_id)).status == "done"


async def test_an_expired_lease_is_requeued_with_backoff_and_the_old_claim_is_fenced_out(
    conn: AsyncConnection,
) -> None:
    job_id = await _job(conn)
    expired_id, live_id = await _tasks(conn, job_id, 2)
    expiring, live = await claim_tasks(conn, "w1", 2)
    stale = await _expire(conn, expiring)

    released = await release_expired_leases(conn)

    assert released == 1
    row = await _row(conn, expired_id)
    assert (row.status, row.claimed_by, row.lease_until, row.attempts, row.last_error) == (
        "queued",
        None,
        None,
        1,
        "lease expired",
    )
    assert row.next_attempt_at == await _now(conn) + timedelta(seconds=30)
    assert (await _row(conn, live_id)).status == "claimed"
    with pytest.raises(LeaseLost):
        await complete_task(conn, stale, "extracted")
    await complete_task(conn, live, "extracted")
    assert await _job_state(conn, job_id) == ("running", [])


async def test_an_expired_lease_on_the_last_attempt_fails_the_task_and_settles_the_job(
    conn: AsyncConnection,
) -> None:
    job_id = await _job(conn)
    [task_id] = await _tasks(conn, job_id, 1, attempts=MAX_ATTEMPTS - 1)
    await _expire(conn, await _claim_one(conn))

    assert await release_expired_leases(conn) == 1

    row = await _row(conn, task_id)
    assert (row.status, row.outcome, row.attempts, row.last_error) == ("failed", "failed", 3, "lease expired")
    assert await _job_state(conn, job_id) == ("failed", ["failed"])


async def test_releasing_with_no_expired_lease_changes_nothing(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    [task_id, _] = await _tasks(conn, job_id, 2)
    await _claim_one(conn)

    assert await release_expired_leases(conn) == 0

    assert (await _row(conn, task_id)).status == "claimed"


async def test_concurrent_claims_each_take_at_most_n_and_share_no_task(engine: AsyncEngine) -> None:
    """Claimers racing over committed tasks: every claim takes at most `n`, and every task is claimed exactly once."""
    claimers, n, count = 8, 3, 240
    async with engine.begin() as conn:
        ids = set(await _tasks(conn, await _job(conn), count))

    async def claimer(worker: str) -> list[list[UrlTaskId]]:
        batches: list[list[UrlTaskId]] = []
        while True:
            async with engine.begin() as conn:
                batch = [task.id for task in await claim_tasks(conn, worker, n)]
            if not batch:
                return batches
            batches.append(batch)

    batches = [
        batch for worker in await asyncio.gather(*(claimer(f"w{i}") for i in range(claimers))) for batch in worker
    ]

    assert max(len(batch) for batch in batches) <= n
    claimed = [task_id for batch in batches for task_id in batch]
    assert sorted(claimed) == sorted(ids)
