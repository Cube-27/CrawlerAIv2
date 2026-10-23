"""The webhook outbox: the events a job's webhook is owed, and their grouping into deliveries.

An event is written in the transaction that makes it happen (a task's end, a record stored, a URL found gone, the
job's end), and only for a job whose request asked for it (`job.webhook_events`), so it is owed exactly when the
change it reports is committed. `form_deliveries`, a scheduler entry, then groups each job's unassigned events into
`webhook_delivery` rows, oldest first, as the job's `webhook_batch` says: at most `max_events` a delivery, sent once
that many wait or the oldest has waited `max_seconds`; without `webhook_batch`, one event a delivery. Once the job has
ended nothing more is coming, so what waits is sent at once. `crawlerai.api.webhooks` posts the deliveries.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, get_args

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.ids import uuid7
from crawlerai.db.models import Job, JobId, JobStatus, WebhookDelivery, WebhookEvent, WebhookEventType

# The events a request without `webhook_events` is sent: the job's end, as a webhook was before events existed.
JOB_END_EVENTS: Final[tuple[WebhookEventType, ...]] = ("job_completed", "job_failed", "job_cancelled")
ALL_EVENTS: Final[tuple[WebhookEventType, ...]] = get_args(WebhookEventType)
MAX_BATCH_EVENTS: Final = 1000
MAX_BATCH_SECONDS: Final = 3600
# Jobs whose waiting events one scheduler run groups; a full batch runs again at once (`scheduler.loop`).
FORM_BATCH: Final = 20
_ENDED: Final[tuple[JobStatus, ...]] = ("completed", "failed", "cancelled")
# The job event (`db.jobs.record_event`) that is also a webhook event, by its kind.
_JOB_EVENT_KINDS: Final[Mapping[str, WebhookEventType]] = {
    "completed": "job_completed",
    "failed": "job_failed",
    "cancelled": "job_cancelled",
    "url_gone": "url_gone",
}


class WebhookBatch(BaseModel):
    """How a job's webhook events are grouped: up to `max_events` a delivery, sent when that many wait or the oldest
    has waited `max_seconds`, whichever comes first."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_events: int = Field(ge=1, le=MAX_BATCH_EVENTS)
    max_seconds: float = Field(gt=0, le=MAX_BATCH_SECONDS)


async def emit(conn: AsyncConnection, job_id: JobId, event: WebhookEventType, payload: Mapping[str, Any]) -> None:
    """Owe `job_id`'s webhook `event` with `payload`, if the job has a webhook that asked for it."""
    await emit_many(conn, job_id, event, [payload])


async def emit_many(
    conn: AsyncConnection, job_id: JobId, event: WebhookEventType, payloads: Sequence[Mapping[str, Any]]
) -> None:
    """`emit` for each of `payloads`, in their order: one statement, which writes nothing for a job not asking."""
    if not payloads:
        return
    asking = select(Job.id).where(Job.id == job_id, Job.webhook_url.is_not(None), Job.webhook_events.contains([event]))
    if (await conn.execute(asking)).first() is None:
        return
    # Ids are UUIDv7 (RFC 9562 §5.7), drawn in order here, so id order is the order the events happened in.
    rows = [{"id": uuid7(), "job_id": job_id, "event": event, "payload": dict(payload)} for payload in payloads]
    await conn.execute(insert(WebhookEvent), rows)


async def emit_job_event(conn: AsyncConnection, job_id: JobId, kind: str, payload: Mapping[str, Any]) -> None:
    """Owe the webhook event a stored job event of `kind` stands for, if it is one (the job's end, `url_gone`)."""
    event = _JOB_EVENT_KINDS.get(kind)
    if event is not None:
        await emit(conn, job_id, event, {"job_id": str(job_id), **payload})


async def form_deliveries(conn: AsyncConnection, *, batch: int) -> int:
    """Group the waiting events of up to `batch` jobs whose delivery is due (the job ended, its oldest event waited
    `max_seconds`, or `max_events` wait; any event without a batch) into deliveries, and return how many jobs got one.
    Only due jobs are read, so a job whose batch is still filling never holds up the others, and a full batch means
    more are due. A job's events are locked as they are read (`SKIP LOCKED`), so two schedulers never put one event in
    two deliveries."""
    overdue = func.min(WebhookEvent.created_at) < func.now() - _max_wait()
    ended = Job.status.in_(_ENDED)
    full = func.count() >= func.coalesce(Job.webhook_batch["max_events"].as_integer(), 1)
    due = (
        select(WebhookEvent.job_id, or_(ended, overdue).label("flush"))
        .join(Job, Job.id == WebhookEvent.job_id)
        .where(WebhookEvent.delivery_id.is_(None))
        .group_by(WebhookEvent.job_id, Job.status, Job.webhook_batch)
        .having(or_(ended, overdue, full))
        .order_by(func.min(WebhookEvent.created_at))
        .limit(batch)
    )
    formed = 0
    for row in (await conn.execute(due)).all():
        formed += await _form(conn, row.job_id, flush=row.flush) > 0
    return formed


def _max_wait() -> Any:
    """The SQL interval the oldest event of a job may wait: its batch's `max_seconds`, none without a batch."""
    seconds = func.coalesce(Job.webhook_batch["max_seconds"].as_float(), 0)
    return func.make_interval(0, 0, 0, 0, 0, 0, seconds)


async def _form(conn: AsyncConnection, job_id: JobId, *, flush: bool) -> int:
    """Assign the job's waiting events to deliveries of its batch size, oldest first, a last, smaller group only when
    `flush`; return how many deliveries were formed (none while another scheduler holds the events)."""
    raw: dict[str, Any] | None = (await conn.execute(select(Job.webhook_batch).where(Job.id == job_id))).scalar_one()
    size = 1 if raw is None else WebhookBatch.model_validate(raw).max_events
    events = (
        select(WebhookEvent.id)
        .where(WebhookEvent.job_id == job_id, WebhookEvent.delivery_id.is_(None))
        .order_by(WebhookEvent.id)
        .with_for_update(skip_locked=True)
    )
    ids = list((await conn.execute(events)).scalars())
    formed = 0
    for start in range(0, len(ids), size):
        group = ids[start : start + size]
        if len(group) < size and not flush:
            break
        formed += 1
        delivery = insert(WebhookDelivery).values(id=uuid7(), job_id=job_id).returning(WebhookDelivery.id)
        delivery_id = (await conn.execute(delivery)).scalar_one()
        await conn.execute(update(WebhookEvent).where(WebhookEvent.id.in_(group)).values(delivery_id=delivery_id))
    return formed
