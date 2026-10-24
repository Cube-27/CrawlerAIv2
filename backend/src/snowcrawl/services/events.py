"""A job's run events as a stream: the stored `job_event` rows in id order, from
after the last one a client saw, with the job's task counts as `progress` after each batch, until the job's end event.
`GET /v1/jobs/{id}/events` sends these over SSE.

The stream polls: events are written by workers in other processes, and a poll a second is well inside the 15 s
heartbeat a client waits for anyway.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Final

import anyio
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from snowcrawl.db.jobs import JOB_TRANSITIONS
from snowcrawl.db.models import Job, JobEvent, JobEventId, JobId
from snowcrawl.services.jobs import JobNotFound, get_job

POLL_S: Final = 1.0
BATCH: Final = 100
PROGRESS: Final = "progress"
# A job's end event has the kind of the status it ended in (`transition_job`): the statuses with no way out.
ENDS: Final = frozenset(status for status, targets in JOB_TRANSITIONS.items() if not targets)


class StreamEvent(BaseModel):
    """One event of the stream. `id` is the stored event's, which a client resumes after; `progress` has none, as it
    is not stored."""

    model_config = ConfigDict(frozen=True)

    id: JobEventId | None
    kind: str
    data: dict[str, Any]


async def check_job(conn: AsyncConnection, job_id: JobId) -> None:
    if (await conn.execute(select(Job.id).where(Job.id == job_id))).first() is None:
        raise JobNotFound(f"no job {job_id}")


async def events_after(conn: AsyncConnection, job_id: JobId, after: JobEventId | None) -> list[StreamEvent]:
    """The job's stored events after `after` (all of them for None), in id order, at most `BATCH`."""
    query = select(JobEvent.id, JobEvent.kind, JobEvent.payload).where(JobEvent.job_id == job_id)
    if after is not None:
        query = query.where(JobEvent.id > after)
    rows = await conn.execute(query.order_by(JobEvent.id).limit(BATCH))
    return [StreamEvent(id=row.id, kind=row.kind, data=row.payload) for row in rows]


async def stream(
    engine: AsyncEngine, job_id: JobId, after: JobEventId | None, *, poll_s: float = POLL_S
) -> AsyncIterator[StreamEvent]:
    """The job's events after `after`, as they are stored, until its end event; a stream that resumes after the end
    event closes at once."""
    while True:
        # A client that drops the stream cancels it through the server's cancel scope, which cancels every await
        # until the scope exits, the pooled connection's reset and close too: a connection half closed that way went
        # back to the pool and failed the next request to draw it. Shielded, a poll finishes and returns its
        # connection, and the cancellation lands at the sleep after it.
        with anyio.CancelScope(shield=True):
            ended, batch = await _poll(engine, job_id, after)
        stored = [event.id for event in batch if event.id is not None]
        for event in batch:
            yield event
        if (batch and batch[-1].kind in ENDS) or (ended and not batch):
            return
        if stored:
            after = max(stored)
        if len(stored) < BATCH:
            await asyncio.sleep(poll_s)


async def _poll(engine: AsyncEngine, job_id: JobId, after: JobEventId | None) -> tuple[bool, list[StreamEvent]]:
    """Whether the job had ended, and what to send for its events after `after`: those events in id order, then
    `progress`, then the end event, if one was read; the end event is last, so the stream stops on it."""
    async with engine.connect() as conn:
        # The status is read before the events: an end committed between the two reads is in the events read.
        ended = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one() in ENDS
        batch = await events_after(conn, job_id, after)
        if not batch:
            return ended, []
        summary = await get_job(conn, job_id)
    progress = StreamEvent(id=None, kind=PROGRESS, data=summary.model_dump(mode="json", include={"counts", "outcomes"}))
    end = [event for event in batch if event.kind in ENDS][:1]
    return ended, [event for event in batch if event.kind not in ENDS] + [progress, *end]
