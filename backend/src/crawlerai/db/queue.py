"""The task queue (SPEC-01 §4.3): `url_task` rows claimed with `FOR UPDATE SKIP LOCKED`, leased, retried with
backoff, and settled into their job's status.

A claim is fenced by `(claimed_by, attempts)`: every claim increments `attempts`, so once a lease is lost (the task
was requeued, and maybe claimed again, even by the same worker) the old `ClaimedTask` can no longer finish the task,
and `LeaseLost` makes the caller roll back whatever it wrote for it.

Finishing a task settles its job in the same transaction. The job row is locked first, so of two workers finishing
a job's last two tasks, the second one waits, then sees the first one's task as finished and ends the job.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import (
    InvalidTransition,
    blocking_statuses,
    settled_status,
    start_jobs,
    transition_job,
    transition_task,
)
from crawlerai.db.models import FinishedOutcome, Job, JobId, PageKind, TaskStatus, UrlTask, UrlTaskId

LEASE: Final = timedelta(minutes=10)
MAX_ATTEMPTS: Final = 3
BACKOFF_BASE: Final = timedelta(seconds=30)
LAST_ERROR_BYTES: Final = 2048


@dataclass(frozen=True)
class ClaimedTask:
    """A url_task as it was claimed. It is a snapshot: the row may move on (a lost lease) while a worker holds it."""

    id: UrlTaskId
    job_id: JobId
    url: str
    canonical_url: str
    page_kind: PageKind | None
    attempts: int
    priority: int
    depth: int
    parent_task_id: UrlTaskId | None
    claimed_by: str


class LeaseLost(Exception):
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"url_task {task_id}: lease lost")


async def claim_tasks(conn: AsyncConnection, worker: str, n: int) -> list[ClaimedTask]:
    """Lease up to `n` due tasks to `worker`, highest priority first, then oldest, and start their queued jobs."""
    due = (
        select(UrlTask.id)
        .where(UrlTask.status == "queued", UrlTask.next_attempt_at <= func.now())
        .order_by(UrlTask.priority.desc(), UrlTask.id)
        .limit(n)
        .with_for_update(skip_locked=True)
    )
    claim = (
        update(UrlTask)
        .where(UrlTask.id.in_(due))
        .values(status="claimed", claimed_by=worker, lease_until=func.now() + LEASE, attempts=UrlTask.attempts + 1)
        .returning(*(getattr(UrlTask, field) for field in ClaimedTask.__dataclass_fields__))
    )
    tasks = [ClaimedTask(**row._mapping) for row in await conn.execute(claim)]
    if tasks:
        await start_jobs(conn, {task.job_id for task in tasks})
    # UPDATE ... RETURNING does not keep the subquery's order.
    return sorted(tasks, key=lambda task: (-task.priority, task.id))


async def complete_task(conn: AsyncConnection, task: ClaimedTask, outcome: FinishedOutcome) -> None:
    await _finish(conn, task, "done", outcome=outcome)


async def fail_task(conn: AsyncConnection, task: ClaimedTask, error: str, *, transient: bool) -> None:
    """Record a failure. A transient one is retried after an exponential backoff until `MAX_ATTEMPTS` (D-0006);
    anything else fails the task."""
    last_error = error.encode()[:LAST_ERROR_BYTES].decode(errors="ignore")
    if transient and task.attempts < MAX_ATTEMPTS:
        backoff = BACKOFF_BASE * 2 ** (task.attempts - 1)
        await _move(conn, task, "queued", last_error=last_error, next_attempt_at=func.now() + backoff)
    else:
        await _finish(conn, task, "failed", outcome="failed", last_error=last_error)


async def cancel_task(conn: AsyncConnection, task: ClaimedTask) -> None:
    """End a claimed task of a job whose cancel was requested, without running it (§4.3)."""
    await _finish(conn, task, "cancelled")


async def release_task(conn: AsyncConnection, task: ClaimedTask) -> None:
    """Return a claimed task that was never started, giving back the attempt its claim counted."""
    await _move(conn, task, "queued", attempts=UrlTask.attempts - 1)


async def _finish(conn: AsyncConnection, task: ClaimedTask, target: TaskStatus, **values: Any) -> None:
    await _move(conn, task, target, **values)
    await _settle_job(conn, task.job_id)


async def _move(conn: AsyncConnection, task: ClaimedTask, target: TaskStatus, **values: Any) -> None:
    """Move a claimed task along the state machine, if the claim still holds the lease."""
    fence = (UrlTask.claimed_by == task.claimed_by, UrlTask.attempts == task.attempts)
    try:
        await transition_task(conn, task.id, target, fence=fence, **values)
    except InvalidTransition as lost:
        raise LeaseLost(task.id) from lost


async def _settle_job(conn: AsyncConnection, job_id: JobId) -> None:
    """End a running job once its tasks allow it (`settled_status`)."""
    job = (await conn.execute(select(Job.status, Job.cancel_requested).where(Job.id == job_id).with_for_update())).one()
    if job.status != "running":
        return
    # Most finished tasks leave others open. The partial index on open tasks answers that without counting every
    # task of the job, which is linear in the job's size and would run once per task.
    blocking = blocking_statuses(cancel_requested=job.cancel_requested)
    open_task = select(UrlTask.id).where(UrlTask.job_id == job_id, UrlTask.status.in_(blocking)).limit(1)
    if (await conn.execute(open_task)).first() is not None:
        return
    counts = await conn.execute(
        select(UrlTask.status, func.count()).where(UrlTask.job_id == job_id).group_by(UrlTask.status)
    )
    target = settled_status(dict(counts.all()), cancel_requested=job.cancel_requested)
    if target is not None:
        await transition_job(conn, job_id, target)
