"""The task queue (persistence-storage spec): `url_task` rows claimed with `FOR UPDATE SKIP LOCKED`, leased, retried
with backoff, and settled into their job's status.

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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import Executable, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import aliased

from crawlerai.core.retry import backoff_delay
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
    JobKind,
    JobStatus,
    PageKind,
    TaskOutcome,
    TaskStatus,
    UrlTask,
    UrlTaskId,
)
from crawlerai.db.task_events import record_task_events

LEASE: Final = timedelta(minutes=10)
# A task's wall-clock limit (`worker/loop`): a page that runs past it is recorded as failed and its job moves on. It
# ends well inside `LEASE`, so the result is recorded while the claim still holds and no other worker runs it meanwhile.
TASK_DEADLINE: Final = timedelta(minutes=3)
MAX_ATTEMPTS: Final = 3
LAST_ERROR_BYTES: Final = 2048
# How many stalled jobs one scheduler turn ends (`fail_stalled_jobs`); a full batch runs again at once.
STALLED_BATCH: Final = 100
# How many expired leases one scheduler turn releases (`release_expired_leases`), each turn one transaction; a full
# batch runs again at once.
LEASE_BATCH: Final = 100
# The kinds of job a process runs while its caller waits, with no task for a while or ever: a `map`, an `extract`
# drafting its prompt's schema.
_RUN_INLINE: Final[tuple[JobKind, ...]] = ("map", "extract")

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
    score: float | None
    parent_task_id: UrlTaskId | None
    claimed_by: str
    lease_until: datetime


_CLAIMED_COLUMNS: Final = tuple(getattr(UrlTask, field) for field in ClaimedTask.__dataclass_fields__)


class LeaseLost(Exception):
    def __init__(self, task_id: uuid.UUID) -> None:
        super().__init__(f"url_task {task_id}: lease lost")


async def claim_tasks(conn: AsyncConnection, worker: str, n: int) -> list[ClaimedTask]:
    """Lease up to `n` due tasks to `worker`: highest priority first, then round robin between jobs (each job's
    best task, then each job's second best, and so on; jobs with fewer leased tasks first), then job and id; within
    a job, best crawl score (`UrlTask.score`, a task with none after one with), then oldest (D-1593). Their queued
    jobs start. The tasks come back in that order."""
    # The rank is a window function, which FOR UPDATE refuses, so the rows are ranked in a subquery and locked after.
    # The ids are read first, in order, and leased by a second statement of the same transaction, which holds the
    # locks: the UPDATE ... RETURNING does not keep the order, and a plain `IN (subquery)` could be planned as a
    # semi-join rescanned per row, claiming every due task.
    leased = aliased(UrlTask)
    in_flight = (
        select(func.count())
        .where(leased.job_id == UrlTask.job_id, leased.status == "claimed")
        .correlate(UrlTask)
        .scalar_subquery()
    )
    rank = (
        func.row_number()
        .over(
            partition_by=(UrlTask.priority, UrlTask.job_id),
            order_by=(UrlTask.score.desc().nulls_last(), UrlTask.id),
        )
        .label("rank")
    )
    ranked = (
        select(UrlTask.id, UrlTask.priority, UrlTask.job_id, rank, in_flight.label("in_flight"))
        .where(UrlTask.status == "queued", UrlTask.next_attempt_at <= func.now())
        .subquery("ranked")
    )
    due = (
        select(UrlTask.id)
        .join(ranked, ranked.c.id == UrlTask.id)
        .where(UrlTask.status == "queued")
        .order_by(ranked.c.priority.desc(), ranked.c.rank, ranked.c.in_flight, ranked.c.job_id, UrlTask.id)
        .limit(n)
        .with_for_update(of=UrlTask, skip_locked=True)
    )
    ids = list((await conn.execute(due)).scalars())
    if not ids:
        return []
    claim = (
        update(UrlTask)
        .where(UrlTask.id.in_(ids))
        .values(
            status="claimed",
            claimed_by=worker,
            lease_until=func.clock_timestamp() + LEASE,
            attempts=UrlTask.attempts + 1,
        )
        .returning(*_CLAIMED_COLUMNS)
    )
    position = {task_id: i for i, task_id in enumerate(ids)}
    tasks = sorted(await _claimed(conn, claim), key=lambda task: position[task.id])
    await start_jobs(conn, {task.job_id for task in tasks})
    return tasks


async def insert_claimed(
    conn: AsyncConnection, job_id: JobId, url: str, canonical_url: str, page_kind: PageKind | None, worker: str
) -> ClaimedTask:
    """Add a task already claimed by `worker`, for a caller that runs it at once instead of queueing it (the
    synchronous `scrape`, rest-api spec). It is leased like any claim, so it finishes through `complete_task` and
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
    `blocked` task's `robots`, acquisition spec). `capture_id` is the page the task fetched, if it fetched one. `ending`
    runs if this ends the job (`settle_job`)."""
    values: dict[str, Any] = {} if capture_id is None else {"capture_id": capture_id}
    await _finish(conn, task, "done", ending, outcome=outcome, last_error=reason, **values)


def retried(task: ClaimedTask, *, transient: bool) -> bool:
    """Whether a failure of `task` on this attempt is retried: a transient one, until `MAX_ATTEMPTS` (D-0006)."""
    return transient and task.attempts < MAX_ATTEMPTS


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
    asked for a delay (a `Retry-After`, acquisition spec), else after `backoff_delay`. A permanent failure, or the last
    attempt, ends the task with `exhausted`: `failed` or `timeout` (a `failed` task), or the outcome the failure
    stands for (a 429 is `blocked`, a finished task).
    `capture_id` is the page the failed attempt fetched, if it fetched one. `ending` runs if this ends the job."""
    values: dict[str, Any] = {"last_error": _cut(error)}
    if capture_id is not None:
        values["capture_id"] = capture_id
    if retried(task, transient=transient):
        delay = backoff_delay(task.attempts) if after is None else after
        await _move(conn, task, "queued", next_attempt_at=func.now() + delay, **values)
    elif exhausted in ("failed", "timeout"):
        await _finish(conn, task, "failed", ending, outcome=exhausted, **values)
    else:
        await _finish(conn, task, "done", ending, outcome=exhausted, **values)


async def cancel_task(conn: AsyncConnection, task: ClaimedTask, *, ending: JobEnding | None = None) -> None:
    """End a claimed task without running it: one of a job whose cancel was requested (§4.3), or one its handler
    skipped. `ending` runs if this ends the job (`settle_job`)."""
    await _finish(conn, task, "cancelled", ending)


async def release_task(conn: AsyncConnection, task: ClaimedTask, *, after: timedelta = timedelta(0)) -> None:
    """Return a claimed task that was never started, due again `after` from now, giving back the attempt its claim
    counted."""
    await _move(conn, task, "queued", attempts=UrlTask.attempts - 1, next_attempt_at=func.now() + after)


async def release_expired_leases(conn: AsyncConnection, *, batch: int, ending: JobEnding | None = None) -> int:
    """Requeue, after the usual backoff, or fail on the last attempt, up to `batch` claimed tasks whose lease has run
    out (§4.3), and return how many. Tasks a worker is finishing right now are skipped; the next run sees them.
    `ending` runs for each job this ends.
    """
    expired = (
        select(*_CLAIMED_COLUMNS)
        .where(UrlTask.status == "claimed", UrlTask.lease_until < func.now())
        # Job by job, so that two schedulers lock job rows in the same order.
        .order_by(UrlTask.job_id, UrlTask.id)
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    tasks = await _claimed(conn, expired)
    for task in tasks:
        await fail_task(conn, task, "lease expired", transient=True, ending=ending)
    return len(tasks)


async def stuck_running_jobs(
    conn: AsyncConnection, *, kinds: Sequence[JobKind], older_than: timedelta, batch: int, taskless: bool = False
) -> list[JobId]:
    """Up to `batch` ids of jobs of `kinds` `running` since more than `older_than` ago (with `taskless`, only those with
    no task), oldest id first, locked for the caller's transaction: the one query the scheduler's reapers share. The
    partial index on running jobs answers it. FOR NO KEY UPDATE, as `settle_job` takes; a job another transaction holds
    is left to the next run."""
    stuck = select(Job.id).where(Job.status == "running", Job.kind.in_(kinds), Job.started_at < func.now() - older_than)
    if taskless:
        stuck = stuck.where(~select(UrlTask.id).where(UrlTask.job_id == Job.id).exists())
    locked = stuck.order_by(Job.id).limit(batch).with_for_update(key_share=True, skip_locked=True)
    return list((await conn.execute(locked)).scalars())


async def fail_stalled_jobs(conn: AsyncConnection, *, batch: int) -> int:
    """End `failed` up to `batch` jobs of `_RUN_INLINE` kinds `running` with no task for longer than `LEASE`, and
    return how many. A process runs such a job while its caller waits, within the request's time cap (a `map`'s, a
    draft's), far under a lease."""
    job_ids = await stuck_running_jobs(conn, kinds=_RUN_INLINE, older_than=LEASE, batch=batch, taskless=True)
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
