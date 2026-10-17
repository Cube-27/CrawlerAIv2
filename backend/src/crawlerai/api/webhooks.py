"""Webhook deliveries (SPEC-10 §4.2): the events a job's webhook is owed (`crawlerai.db.webhook_outbox`), POSTed in
the deliveries the scheduler grouped them into, signed with the webhook secret of the API key that submitted the job,
in at most 5 attempts with backoff.

The target passes the SSRF guard at every attempt, so a name that resolves to a private address by then is refused,
and a redirect is not followed. A delivery that fails never changes the job (§4.8); its last error is kept on the row,
and never contains the URL. Deliveries of one job are independent: a failing one does not hold up the next, so a
receiver orders events by their ids (UUIDv7, RFC 9562 §5.7: creation order).

Body (JSON): `{"delivery_id", "job_id", "attempt", "events": [{"id", "type", "created_at", "data"}]}`; a job end
event's `data` carries the job's summary at delivery as `job`. Signature: `X-CrawlerAI-Signature: sha256=<hex>`, the
HMAC-SHA256 (RFC 2104, FIPS 180-4) of the request body, keyed with the UTF-8 bytes of the key's `webhook_secret`,
which `crawlerai apikey create` prints with the key; `X-CrawlerAI-Delivery` repeats the delivery id, the same on every
attempt, for a receiver to drop a delivery it already took.
"""

import hashlib
import hmac
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Final, cast

from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.http import RequestFailed, post
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected
from crawlerai.db.models import (
    ApiKey,
    Job,
    JobId,
    WebhookDelivery,
    WebhookDeliveryId,
    WebhookEvent,
    WebhookEventId,
    WebhookEventType,
)
from crawlerai.db.webhook_outbox import JOB_END_EVENTS
from crawlerai.services.jobs import get_job

SIGNATURE_HEADER: Final = "X-CrawlerAI-Signature"
DELIVERY_HEADER: Final = "X-CrawlerAI-Delivery"
MAX_ATTEMPTS: Final = 5
RETRY_BASE: Final = timedelta(seconds=30)  # then 2 min, 8 min and 32 min
TIMEOUT_S: Final = 10.0
# One delivery per scheduler run: the POST runs inside the run's transaction, so this bounds how long a row stays
# locked, and the scheduler runs a full batch again at once.
DELIVERY_BATCH: Final = 1
UNSIGNED: Final = "no API key submitted the job, so there is no secret to sign with"
_JOB_END: Final = frozenset(JOB_END_EVENTS)

# POST a body with headers to a URL; the response status. Raises `SsrfRejected` or `RequestFailed`.
Poster = Callable[[str, bytes, Mapping[str, str]], Awaitable[int]]


class EventOut(BaseModel):
    """One event of a delivery's body."""

    id: WebhookEventId
    type: WebhookEventType
    created_at: datetime
    data: dict[str, Any]


class DeliveryBody(BaseModel):
    """What a delivery POSTs (SPEC-10 §4.2)."""

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
    events = [EventOut(id=row.id, type=row.event, created_at=row.created_at, data=row.payload) for row in rows]
    if any(event.type in _JOB_END for event in events):
        summary = (await get_job(conn, job_id)).model_dump(mode="json")
        events = [
            event.model_copy(update={"data": {**event.data, "job": summary}}) if event.type in _JOB_END else event
            for event in events
        ]
    body = DeliveryBody(delivery_id=delivery_id, job_id=job_id, attempt=attempt, events=events)
    return body.model_dump_json().encode()


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
    error = await _attempt(post, row.url, body, headers)
    if error is None:
        await _set(conn, row.id, status="delivered", attempts=attempts, last_error=None)
    elif attempts >= MAX_ATTEMPTS:
        await _set(conn, row.id, status="failed", attempts=attempts, last_error=error)
    else:
        retry_at = func.now() + retry_delay(attempts)
        await _set(conn, row.id, attempts=attempts, last_error=error, next_attempt_at=retry_at)


async def _attempt(post: Poster, url: str, body: bytes, headers: Mapping[str, str]) -> str | None:
    """None when the target accepted the delivery (a 2xx, RFC 9110 §15.3); else why not."""
    try:
        status = await post(url, body, headers)
    except (SsrfRejected, RequestFailed) as e:
        return str(e)
    return None if 200 <= status < 300 else f"status {status}"


async def _set(conn: AsyncConnection, delivery_id: WebhookDeliveryId, **values: Any) -> None:
    await conn.execute(update(WebhookDelivery).where(WebhookDelivery.id == delivery_id).values(**values))
