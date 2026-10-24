"""Webhook deliveries: the events a job's webhook is owed (`snowcrawl.db.webhook_outbox`), POSTed in
the deliveries the scheduler grouped them into, signed with the webhook secret of the API key that submitted the job,
in at most 5 attempts with backoff.

The target passes the SSRF guard at every attempt, so a name that resolves to a private address by then is refused,
and a redirect is not followed. A delivery that fails never changes the job; its last error is kept on the row,
and never contains the URL. Deliveries of one job are independent: a failing one does not hold up the next, so a
receiver orders events by their ids (UUIDv7, RFC 9562 §5.7: creation order).

Body (JSON): `{"delivery_id", "job_id", "attempt", "events": [{"id", "type", "created_at", "data"}]}`; a job end
event's `data` carries the job's summary at delivery as `job`, and a `record` or `record_changed` event's record
values are served as the API serves them. Signature: `X-Snowcrawl-Signature:
sha256=<hex>`, the HMAC-SHA256 (RFC 2104, FIPS 180-4) of the request body, keyed with the UTF-8 bytes of the key's
`webhook_secret`, which `snowcrawl apikey create` prints with the key; `X-Snowcrawl-Delivery` repeats the delivery id,
the same on every attempt, for a receiver to drop a delivery it already took.
"""

import hashlib
import hmac
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Final, cast

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.acquire.http import RequestFailed, post
from snowcrawl.acquire.ssrf import SafeConnector, SsrfRejected
from snowcrawl.db.models import (
    ApiKey,
    Job,
    JobId,
    SchemaId,
    WebhookDelivery,
    WebhookDeliveryId,
    WebhookEvent,
    WebhookEventId,
    WebhookEventType,
)
from snowcrawl.db.webhook_outbox import JOB_END_EVENTS
from snowcrawl.normalize.dispatch import served
from snowcrawl.schemas import registry
from snowcrawl.schemas.types import SchemaDef
from snowcrawl.services.jobs import get_job

SIGNATURE_HEADER: Final = "X-Snowcrawl-Signature"
DELIVERY_HEADER: Final = "X-Snowcrawl-Delivery"
MAX_ATTEMPTS: Final = 5
RETRY_BASE: Final = timedelta(seconds=30)  # then 2 min, 8 min and 32 min
TIMEOUT_S: Final = 10.0
# One delivery per scheduler run: the POST runs inside the run's transaction, so this bounds how long a row stays
# locked, and the scheduler runs a full batch again at once.
DELIVERY_BATCH: Final = 1
UNSIGNED: Final = "no API key submitted the job, so there is no secret to sign with"
_JOB_END: Final = frozenset(JOB_END_EVENTS)
# The events whose `data` holds a stored record's published values (`db.task_events`).
_RECORD_EVENTS: Final = frozenset({"record", "record_changed"})

# POST a body with headers to a URL; the response status. Raises `SsrfRejected` or `RequestFailed`.
Poster = Callable[[str, bytes, Mapping[str, str]], Awaitable[int]]


class EventOut(BaseModel):
    """One event of a delivery's body."""

    id: WebhookEventId
    type: WebhookEventType
    created_at: datetime
    data: dict[str, Any]


class DeliveryBody(BaseModel):
    """What a delivery POSTs."""

    delivery_id: WebhookDeliveryId
    job_id: JobId
    attempt: int
    events: list[EventOut]


@dataclass(frozen=True)
class _Due:
    id: WebhookDeliveryId
    job_id: JobId
    attempts: int
    url: str
    secret: str | None  # None when no API key submitted the job


def poster(connector: SafeConnector) -> Poster:
    return partial(post, connector=connector, timeout_s=TIMEOUT_S)


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def retry_delay(attempts: int) -> timedelta:
    """The wait after failed attempt number `attempts` (1 for the first)."""
    delay: timedelta = RETRY_BASE * 4 ** (attempts - 1)
    return delay


async def deliver_webhooks(conn: AsyncConnection, post: Poster, *, batch: int) -> int:
    """Attempt up to `batch` due deliveries, the longest due first, and return how many."""
    due = (
        select(
            WebhookDelivery.id, WebhookDelivery.job_id, WebhookDelivery.attempts, Job.webhook_url, ApiKey.webhook_secret
        )
        .join(Job, Job.id == WebhookDelivery.job_id)
        .outerjoin(ApiKey, ApiKey.id == Job.api_key_id)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= func.now())
        .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.id)
        .limit(batch)
        .with_for_update(of=WebhookDelivery, skip_locked=True)
    )
    # An event is owed only to a job with a URL (`webhook_outbox.emit`), so `webhook_url` is set on every row read.
    rows = [
        _Due(row.id, row.job_id, row.attempts, cast(str, row.webhook_url), row.webhook_secret)
        for row in await conn.execute(due)
    ]
    for row in rows:
        await _deliver(conn, row, post)
    return len(rows)


async def delivery_body(conn: AsyncConnection, delivery_id: WebhookDeliveryId, job_id: JobId, attempt: int) -> bytes:
    """The JSON body of attempt number `attempt` of the delivery: its events in order, a job end event with the job's
    summary as it is now."""
    rows = await conn.execute(
        select(WebhookEvent.id, WebhookEvent.event, WebhookEvent.created_at, WebhookEvent.payload)
        .where(WebhookEvent.delivery_id == delivery_id)
        .order_by(WebhookEvent.id)
    )
    events = await _served(
        [EventOut(id=row.id, type=row.event, created_at=row.created_at, data=row.payload) for row in rows], conn
    )
    if any(event.type in _JOB_END for event in events):
        summary = (await get_job(conn, job_id)).model_dump(mode="json")
        events = [
            event.model_copy(update={"data": {**event.data, "job": summary}}) if event.type in _JOB_END else event
            for event in events
        ]
    body = DeliveryBody(delivery_id=delivery_id, job_id=job_id, attempt=attempt, events=events)
    return body.model_dump_json().encode()


async def _served(events: list[EventOut], conn: AsyncConnection) -> list[EventOut]:
    """`events` with each record event's values served in the schema the record follows."""
    schemas: dict[str, SchemaDef] = {}
    out: list[EventOut] = []
    for event in events:
        if event.type in _RECORD_EVENTS:
            schema_id = event.data["schema_id"]
            if schema_id not in schemas:
                schemas[schema_id] = await registry.get_by_id(conn, SchemaId(uuid.UUID(schema_id)))
            data = served(event.data["data"], schemas[schema_id].fields)
            event = event.model_copy(update={"data": {**event.data, "data": data}})
        out.append(event)
    return out


async def _deliver(conn: AsyncConnection, row: _Due, post: Poster) -> None:
    if row.secret is None:
        await _set(conn, row.id, status="failed", last_error=UNSIGNED)
        return
    attempts = row.attempts + 1
    body = await delivery_body(conn, row.id, row.job_id, attempts)
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: signature(row.secret, body),
        DELIVERY_HEADER: str(row.id),
    }
    code, error = await _attempt(post, row.url, body, headers)
    # The attempt's answer is kept as it came: `response_code` is None when the target gave none.
    seen = {"attempts": attempts, "last_error": error, "response_code": code}
    if error is None:
        await _set(conn, row.id, status="delivered", **seen)
    elif attempts >= MAX_ATTEMPTS:
        await _set(conn, row.id, status="failed", **seen)
    else:
        await _set(conn, row.id, next_attempt_at=func.now() + retry_delay(attempts), **seen)


async def _attempt(post: Poster, url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int | None, str | None]:
    """The target's status (None when it gave none) and why the attempt failed (None when the target accepted the
    delivery with a 2xx, RFC 9110 §15.3)."""
    try:
        status = await post(url, body, headers)
    except (SsrfRejected, RequestFailed) as e:
        return None, str(e)
    return status, None if 200 <= status < 300 else f"status {status}"


async def _set(conn: AsyncConnection, delivery_id: WebhookDeliveryId, **values: Any) -> None:
    await conn.execute(update(WebhookDelivery).where(WebhookDelivery.id == delivery_id).values(**values))
