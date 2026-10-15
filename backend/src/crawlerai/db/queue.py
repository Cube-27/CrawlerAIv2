"""The task queue (SPEC-01 §4.3): `url_task` rows claimed with `FOR UPDATE SKIP LOCKED`, leased, retried with
backoff, and settled into their job's status.

A claim is fenced by its `(claimed_by, lease_until)`. Each claim sets `lease_until` from `clock_timestamp()`, which,
unlike `now()`, advances within a transaction, so no two claims of a task share it; `attempts` would not do, as
`release_task` gives one back. Once a lease is lost (the task was requeued, and maybe claimed again, even by the same
worker) the old `ClaimedTask` can no longer finish the task, and `LeaseLost` makes the caller roll back whatever it
wrote for it. `lease_until` is thus the claim's identity too: anything that extends a lease must hand its holder the
new value, or the holder fences itself out.

A lease runs out when its worker died or hung; `release_expired_leases` (the scheduler, every minute) counts that as
a transient failure of the attempt. A job that a process runs while its caller waits, with no task (a `map`, a prompt's
draft), has no lease: one still `running` with no task a lease after it started lost its process, and
`fail_stalled_jobs` ends it `failed`.

Finishing a task records its run events (`crawlerai.db.task_events`) and settles its job in the same transaction.
The job row is locked first, so of two workers finishing a job's last two tasks, the second one waits, then sees the
first one's task as finished and ends the job. A caller may pass an `ending` hook, which runs in that transaction just
before the job ends: what it writes commits with the end, and the events it records come before the end event.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import Executable, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import (
    InvalidTransition,
    blocking_statuses,
    settled_status,
    start_jobs,
    transition_job,
    transition_task,
)
from crawlerai.db.models import (
    CaptureId,
    FinishedOutcome,
    Job,
    JobId,
    JobStatus,
    PageKind,
    TaskOutcome,
    TaskStatus,
    UrlTask,
    UrlTaskId,
)
from crawlerai.db.task_events import record_task_events

LEASE: Final = timedelta(minutes=10)
MAX_ATTEMPTS: Final = 3
BACKOFF_BASE: Final = timedelta(seconds=30)
LAST_ERROR_BYTES: Final = 2048
# How many stalled jobs one scheduler turn ends (`fail_stalled_jobs`); a full batch runs again at once.
STALLED_BATCH: Final = 100

# Runs as a job ends (`settle_job`): the job, and the status it is about to end in.
JobEnding = Callable[[AsyncConnection, JobId, JobStatus], Awaitable[None]]


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
    lease_until: datetime


_CLAIMED_COLUMNS: Final = tuple(getattr(UrlTask, field) for field in ClaimedTask.__dataclass_fields__)


class LeaseLost(Exception):
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"url_task {task_id}: lease lost")


async def claim_tasks(conn: AsyncConnection, worker: str, n: int) -> list[ClaimedTask]:
    """Lease up to `n` due tasks to `worker`, highest priority first, then oldest, and start their queued jobs."""
    # The CTE runs exactly once (MATERIALIZED, PostgreSQL docs, "WITH Queries"). As a plain `IN (subquery)`, the
    # planner may rescan the subquery once per row of a semi-join; each rescan skips the rows already claimed and
    # yields `n` more, so a single claim could take every due task.
    due = (
        select(UrlTask.id)
        .where(UrlTask.status == "queued", UrlTask.next_attempt_at <= func.now())
        .order_by(UrlTask.priority.desc(), UrlTask.id)
        .limit(n)
        .with_for_update(skip_locked=True)
        .cte("due")
        .prefix_with("MATERIALIZED")
    )
    claim = (
        update(UrlTask)
        .where(UrlTask.id.in_(select(due.c.id)))
        .values(
            status="claimed",
            claimed_by=worker,
            lease_until=func.clock_timestamp() + LEASE,
            attempts=UrlTask.attempts + 1,
        )
        .returning(*_CLAIMED_COLUMNS)
    )
    tasks = await _claimed(conn, claim)
    if tasks:
        await start_jobs(conn, {task.job_id for task in tasks})
    # UPDATE ... RETURNING does not keep the subquery's order.
    return sorted(tasks, key=lambda task: (-task.priority, task.id))


async def insert_claimed(
    conn: AsyncConnection, job_id: JobId, url: str, canonical_url: str, page_kind: PageKind | None, worker: str
) -> ClaimedTask:
    """Add a task already claimed by `worker`, for a caller that runs it at once instead of queueing it (the
    synchronous `scrape`, SPEC-07 §4.4). It is leased like any claim, so it finishes through `complete_task` and
    `fail_task`, and no worker takes it while it runs."""
    claim = (
        insert(UrlTask)
        .values(
            job_id=job_id,
            url=url,
            canonical_url=canonical_url,
            page_kind=page_kind,
            status="claimed",
            claimed_by=worker,
            lease_until=func.clock_timestamp() + LEASE,
            attempts=1,
        )
        .returning(*_CLAIMED_COLUMNS)
    )
    (task,) = await _claimed(conn, claim)
    return task


async def complete_task(
    conn: AsyncConnection,
    task: ClaimedTask,
    outcome: FinishedOutcome,
    *,
    reason: str | None = None,
    capture_id: CaptureId | None = None,
    ending: JobEnding | None = None,
) -> None:
    """Finish a task with `outcome`; `reason`, kept in `last_error`, says why when the outcome alone does not (a
    `blocked` task's `robots`, SPEC-02 §4.6). `capture_id` is the page the task fetched, if it fetched one. `ending`
    runs if this ends the job (`settle_job`)."""
    values: dict[str, Any] = {} if capture_id is None else {"capture_id": capture_id}
    await _finish(conn, task, "done", ending, outcome=outcome, last_error=reason, **values)


def retried(task: ClaimedTask, *, transient: bool) -> bool:
    """Whether a failure of `task` on this attempt is retried: a transient one, until `MAX_ATTEMPTS` (D-0006)."""
    return transient and task.attempts < MAX_ATTEMPTS


def retry_delay(attempts: int) -> timedelta:
    """The backoff before retrying a task that failed transiently on attempt `attempts` (1 for the first)."""
    delay: timedelta = BACKOFF_BASE * 2 ** (attempts - 1)
    return delay


async def fail_task(
    conn: AsyncConnection,
    task: ClaimedTask,
    error: str,
    *,
    transient: bool,
    after: timedelta | None = None,
    exhausted: TaskOutcome = "failed",
    capture_id: CaptureId | None = None,
    ending: JobEnding | None = None,
) -> None:
    """Record a failure. A transient one is retried until `MAX_ATTEMPTS` (D-0006): after `after` when the target
    asked for a delay (a `Retry-After`, SPEC-02 §4.6), else after `retry_delay`. A permanent failure, or the last
    attempt, ends the task with `exhausted`: `failed`, or the outcome the failure stands for (a 429 is `blocked`).
    `capture_id` is the page the failed attempt fetched, if it fetched one. `ending` runs if this ends the job."""
    values: dict[str, Any] = {"last_error": _cut(error)}
    if capture_id is not None:
        values["capture_id"] = capture_id
    if retried(task, transient=transient):
        delay = retry_delay(task.attempts) if after is None else after
        await _move(conn, task, "queued", next_attempt_at=func.now() + delay, **values)
    elif exhausted == "failed":
        await _finish(conn, task, "failed", ending, outcome="failed", **values)
    else:
        await _finish(conn, task, "done", ending, outcome=exhausted, **values)


async def cancel_task(conn: AsyncConnection, task: ClaimedTask) -> None:
    """End a claimed task of a job whose cancel was requested, without running it (§4.3)."""
    await _finish(conn, task, "cancelled", None)


async def release_task(conn: AsyncConnection, task: ClaimedTask, *, after: timedelta = timedelta(0)) -> None:
    """Return a claimed task that was never started, due again `after` from now, giving back the attempt its claim
    counted."""
    await _move(conn, task, "queued", attempts=UrlTask.attempts - 1, next_attempt_at=func.now() + after)


async def release_expired_leases(conn: AsyncConnection, *, ending: JobEnding | None = None) -> int:
    """Requeue, after the usual backoff, or fail on the last attempt, every claimed task whose lease has run out
    (§4.3), and return how many there were. Tasks a worker is finishing right now are skipped; the next run sees them.
    `ending` runs for each job this ends.
    """
    expired = (
        select(*_CLAIMED_COLUMNS)
        .where(UrlTask.status == "claimed", UrlTask.lease_until < func.now())
        # Job by job, so that two schedulers lock job rows in the same order.
        .order_by(UrlTask.job_id, UrlTask.id)
        .with_for_update(skip_locked=True)
    )
    tasks = await _claimed(conn, expired)
    for task in tasks:
        await fail_task(conn, task, "lease expired", transient=True, ending=ending)
    return len(tasks)


async def fail_stalled_jobs(conn: AsyncConnection, *, batch: int) -> int:
    """End `failed` up to `batch` jobs `running` with no task for longer than `LEASE`, and return how many. A process
    runs such a job while its caller waits, within the request's time cap (a `map`'s, a draft's), far under a lease;
    `learn` jobs run without tasks too, and end by their own expiry (`expire_learn_runs`)."""
    stalled = (
        select(Job.id)
        .where(
            Job.status == "running",
            Job.kind != "learn",
            Job.started_at < func.now() - LEASE,
            ~select(UrlTask.id).where(UrlTask.job_id == Job.id).exists(),
        )
        .order_by(Job.id)
        .limit(batch)
        # FOR NO KEY UPDATE, as `settle_job` takes; a job another transaction holds is left to the next run.
        .with_for_update(key_share=True, skip_locked=True)
    )
    job_ids = (await conn.execute(stalled)).scalars().all()
    for job_id in job_ids:
        await transition_job(conn, job_id, "failed")
    return len(job_ids)


def _cut(error: str) -> str:
    return error.encode()[:LAST_ERROR_BYTES].decode(errors="ignore")


async def _claimed(conn: AsyncConnection, statement: Executable) -> list[ClaimedTask]:
    return [ClaimedTask(**row._mapping) for row in await conn.execute(statement)]


async def _finish(
    conn: AsyncConnection, task: ClaimedTask, target: TaskStatus, ending: JobEnding | None, **values: Any
) -> None:
    await _move(conn, task, target, **values)
    if target != "cancelled":  # a cancelled task did not run
        await record_task_events(conn, task.id)
    await settle_job(conn, task.job_id, ending)


async def _move(conn: AsyncConnection, task: ClaimedTask, target: TaskStatus, **values: Any) -> None:
    """Move a claimed task along the state machine, if the claim still holds the lease."""
    fence = (UrlTask.claimed_by == task.claimed_by, UrlTask.lease_until == task.lease_until)
    try:
        await transition_task(conn, task.id, target, fence=fence, **values)
    except InvalidTransition as lost:
        raise LeaseLost(task.id) from lost


async def settle_job(conn: AsyncConnection, job_id: JobId, ending: JobEnding | None = None) -> None:
    """End a running job once its tasks allow it (`settled_status`), running `ending` first."""
    # FOR NO KEY UPDATE: it serializes with every other write to the job's row, but not with a running task's inserts
    # that refer to the job (FOR KEY SHARE, PostgreSQL row-level locks), which hold until that task commits.
    locked = select(Job.status, Job.cancel_requested).where(Job.id == job_id).with_for_update(key_share=True)
    job = (await conn.execute(locked)).one()
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
    if target is None:
        return
    if ending is not None:
        await ending(conn, job_id, target)
    await transition_job(conn, job_id, target)
