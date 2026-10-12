"""The job and url_task state machines (SPEC-01 §4.2, §4.3), and job run events (ARCHITECTURE §17).

The transition tables are the authority: `transition_job` and `transition_task` only move a row along an edge of
its table, with a compare-and-set update, so two workers racing on one row cannot both win.
"""

from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobEvent, JobEventId, JobId, JobStatus, TaskStatus, UrlTask, UrlTaskId

JOB_TRANSITIONS: Final[Mapping[JobStatus, frozenset[JobStatus]]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

TASK_TRANSITIONS: Final[Mapping[TaskStatus, frozenset[TaskStatus]]] = {
    "queued": frozenset({"claimed", "cancelled"}),
    # `queued` again: a retry after a transient failure, or a lease that expired (§4.3).
    "claimed": frozenset({"queued", "done", "failed", "cancelled"}),
    "done": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, table: str, row_id: object, current: str, target: str) -> None:
        super().__init__(f"{table} {row_id}: {current} -> {target}")


def _sources[S: str](transitions: Mapping[S, frozenset[S]], target: S) -> list[S]:
    return [status for status, targets in transitions.items() if target in targets]


def settled_status(counts: Mapping[TaskStatus, int], *, cancel_requested: bool) -> JobStatus | None:
    """The status a running job ends in, given how many of its tasks are in each status; `None` while it continues.

    A cancelled job ends once no task is claimed, and its queued tasks are not run (SPEC-10 §4.2). Otherwise a job
    ends when no task is queued or claimed, and fails only when every task failed (§4.3, D-0006).
    """
    if counts.get("claimed", 0):
        return None
    if cancel_requested:
        return "cancelled"
    if counts.get("queued", 0):
        return None
    failed = counts.get("failed", 0)
    return "failed" if failed and failed == sum(counts.values()) else "completed"


async def record_event(
    conn: AsyncConnection, job_id: JobId, kind: str, payload: Mapping[str, Any] | None = None
) -> JobEventId:
    event_id: JobEventId = (
        await conn.execute(
            insert(JobEvent).values(job_id=job_id, kind=kind, payload=dict(payload or {})).returning(JobEvent.id)
        )
    ).scalar_one()
    return event_id


async def transition_job(conn: AsyncConnection, job_id: JobId, target: JobStatus) -> None:
    """Move a job to `target`. Starting stamps `started_at`; ending stamps `finished_at` and records an event of
    the same kind, which SSE and webhooks report (SPEC-10 §4.2)."""
    values: dict[str, Any] = {"status": target}
    if target == "running":
        values["started_at"] = func.now()
    if not JOB_TRANSITIONS[target]:
        values["finished_at"] = func.now()
    moved = await conn.execute(
        update(Job)
        .where(Job.id == job_id, Job.status.in_(_sources(JOB_TRANSITIONS, target)))
        .values(values)
        .returning(Job.id)
    )
    if moved.first() is None:
        current = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
        raise InvalidTransition("job", job_id, current, target)
    if not JOB_TRANSITIONS[target]:
        await record_event(conn, job_id, target)


async def transition_task(conn: AsyncConnection, task_id: UrlTaskId, target: TaskStatus) -> None:
    """Move a url_task to `target`. A requeued task gives up its lease, so it looks like any other queued task."""
    values: dict[str, Any] = {"status": target}
    if target == "queued":
        values.update(claimed_by=None, lease_until=None)
    moved = await conn.execute(
        update(UrlTask)
        .where(UrlTask.id == task_id, UrlTask.status.in_(_sources(TASK_TRANSITIONS, target)))
        .values(values)
        .returning(UrlTask.id)
    )
    if moved.first() is None:
        current = (await conn.execute(select(UrlTask.status).where(UrlTask.id == task_id))).scalar_one()
        raise InvalidTransition("url_task", task_id, current, target)
