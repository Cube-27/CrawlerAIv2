"""The job and url_task state machines (SPEC-01 §4.2, §4.3), and job run events (ARCHITECTURE §17).

The transition tables are the authority: `transition_job` and `transition_task` only move a row along an edge of
its table, with a compare-and-set update, so two workers racing on one row cannot both win.
"""

import uuid
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobEvent, JobId, JobStatus, TaskStatus, UrlTask, UrlTaskId
from crawlerai.db.webhook_outbox import emit_job_event

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


def blocking_statuses(*, cancel_requested: bool) -> tuple[TaskStatus, ...]:
    """The task statuses that keep a running job from ending: a cancelled job waits only for its claimed tasks, and
    its queued tasks are not run (SPEC-10 §4.2); any other job also waits for its queued tasks (§4.3)."""
    return ("claimed",) if cancel_requested else ("claimed", "queued")


def settled_status(counts: Mapping[TaskStatus, int], *, cancel_requested: bool) -> JobStatus | None:
    """The status a running job ends in, given how many of its tasks are in each status; `None` while it continues.

    A job fails only when every task failed (§4.3, D-0006).
    """
    if any(counts.get(status, 0) for status in blocking_statuses(cancel_requested=cancel_requested)):
        return None
    if cancel_requested:
        return "cancelled"
    failed = counts.get("failed", 0)
    return "failed" if failed and failed == sum(counts.values()) else "completed"


async def record_event(
    conn: AsyncConnection,
    job_id: JobId,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    ts: datetime | None = None,
) -> None:
    """Append an event, stamped `ts`, or when it is recorded, and owe the webhook event it stands for, if any
    (`db.webhook_outbox`). A worker records a task's events at the end of the task's transaction, where `now()` would
    be the time the transaction began (PostgreSQL §9.9.5)."""
    values = {"job_id": job_id, "kind": kind, "payload": dict(payload or {}), "ts": ts or func.clock_timestamp()}
    await conn.execute(insert(JobEvent).values(values))
    await emit_job_event(conn, job_id, kind, payload or {})


async def _move[S: str](
    conn: AsyncConnection,
    model: type[Job] | type[UrlTask],
    row_id: uuid.UUID,
    transitions: Mapping[S, frozenset[S]],
    target: S,
    values: Mapping[str, Any],
    fence: Sequence[ColumnElement[bool]] = (),
) -> None:
    """Compare-and-set `row_id` to `target` from any status with an edge to it, or raise `InvalidTransition`.
    `fence` adds conditions the row must also meet."""
    sources = [status for status, targets in transitions.items() if target in targets]
    moved = await conn.execute(
        update(model).where(model.id == row_id, model.status.in_(sources), *fence).values(status=target, **values)
    )
    if moved.rowcount == 0:
        current = (await conn.execute(select(model.status).where(model.id == row_id))).scalar_one()
        raise InvalidTransition(model.__tablename__, row_id, current, target)


async def transition_job(conn: AsyncConnection, job_id: JobId, target: JobStatus) -> None:
    """Move a job to `target`. Starting stamps `started_at`; ending stamps `finished_at` and records an event of the
    same kind, which SSE reports and which owes the job's end webhook event, if it asked for one (SPEC-10 §4.2)."""
    values: dict[str, Any] = {}
    if target == "running":
        values["started_at"] = func.now()
    ended_at: datetime | None = None
    if not JOB_TRANSITIONS[target]:
        # The job ends when its last task settles, at the end of that task's transaction: `clock_timestamp()`, not
        # `now()`, which is when the transaction began (PostgreSQL §9.9.5).
        ended_at = (await conn.execute(select(func.clock_timestamp()))).scalar_one()
        values["finished_at"] = ended_at
    await _move(conn, Job, job_id, JOB_TRANSITIONS, target, values)
    if ended_at is not None:
        await record_event(conn, job_id, target, ts=ended_at)


async def start_jobs(conn: AsyncConnection, job_ids: Collection[JobId]) -> None:
    """Move those of `job_ids` that are still queued to `running`; a job that has started is left as it is."""
    await conn.execute(
        update(Job).where(Job.id.in_(job_ids), Job.status == "queued").values(status="running", started_at=func.now())
    )


async def transition_task(
    conn: AsyncConnection,
    task_id: UrlTaskId,
    target: TaskStatus,
    *,
    fence: Sequence[ColumnElement[bool]] = (),
    **values: Any,
) -> None:
    """Move a url_task to `target`, setting `values` too. A requeued task gives up its lease, so it looks like any
    other queued task."""
    if target == "queued":
        values |= {"claimed_by": None, "lease_until": None}
    await _move(conn, UrlTask, task_id, TASK_TRANSITIONS, target, values, fence)
