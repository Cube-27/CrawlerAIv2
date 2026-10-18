"""A job's webhook deliveries (SPEC-10 §4.2): what a caller debugging a receiver reads, newest first, a page at a time.

A delivery is `pending` until the target accepts it (a 2xx) or its attempts run out (`failed`); it keeps how many
attempts were made, when the next is due, the last attempt's error and the status the target answered with. Rows
expire 30 days after their creation once ended (`scheduler.retention`).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobId, WebhookDelivery, WebhookDeliveryId, WebhookEvent, WebhookStatus
from crawlerai.db.paging import keyset_page
from crawlerai.services.jobs import JobNotFound
from crawlerai.services.records import MAX_PAGE


class DeliveryOut(BaseModel):
    """One delivery: its status, attempts, when the next one is due (while pending), the last attempt's error and the
    status the target answered it with (null before an attempt, or when the target gave none), and how many events it
    carries."""

    model_config = ConfigDict(frozen=True)

    id: WebhookDeliveryId
    status: WebhookStatus
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    response_code: int | None
    event_count: int
    created_at: datetime


class DeliveryPage(BaseModel):
    """One page of a job's deliveries, newest first; `next_cursor` is the `cursor` of the page after it, None on the
    last."""

    model_config = ConfigDict(frozen=True)

    items: list[DeliveryOut]
    next_cursor: WebhookDeliveryId | None


class DeliveryListQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: WebhookDeliveryId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


async def list_deliveries(conn: AsyncConnection, job_id: JobId, query: DeliveryListQuery) -> DeliveryPage:
    """The job's deliveries after `query.cursor`. Raises `JobNotFound`. Ids are UUIDv7 (RFC 9562 §5.7), so id order is
    creation order."""
    if (await conn.execute(select(Job.id).where(Job.id == job_id))).first() is None:
        raise JobNotFound(f"no job {job_id}")
    carried = (
        select(func.count())
        .where(WebhookEvent.delivery_id == WebhookDelivery.id)
        .correlate(WebhookDelivery)
        .scalar_subquery()
        .label("event_count")
    )
    statement = select(
        WebhookDelivery.id,
        WebhookDelivery.status,
        WebhookDelivery.attempts,
        # The time a pending delivery is next tried; an ended one has none.
        case((WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at)).label("next_attempt_at"),
        WebhookDelivery.last_error,
        WebhookDelivery.response_code,
        WebhookDelivery.created_at,
        carried,
    ).where(WebhookDelivery.job_id == job_id)
    rows, next_cursor = await keyset_page(
        conn, statement, WebhookDelivery.id, after=query.cursor, limit=query.limit, descending=True
    )
    return DeliveryPage(items=[DeliveryOut.model_validate(row._mapping) for row in rows], next_cursor=next_cursor)
