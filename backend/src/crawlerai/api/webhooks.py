"""Completion webhooks (SPEC-10 §4.2): when a job with a `webhook_url` ends, its summary is POSTed there, signed with
the webhook secret of the API key that submitted the job, in at most 3 attempts with backoff.

The job's end writes a `webhook_delivery` row in the same transaction (`transition_job`); the scheduler delivers the
due rows (`deliver_webhooks`). The target passes the SSRF guard at every attempt, so a name that resolves to a
private address by then is refused. A delivery that fails never changes the job (§4.8); its last error is kept on
the row, and never contains the URL.

Signature: `X-CrawlerAI-Signature: sha256=<hex>`, the HMAC-SHA256 (RFC 2104, FIPS 180-4) of the request body, keyed
with the UTF-8 bytes of the key's `webhook_secret`, which `crawlerai apikey create` prints with the key.
"""

import hashlib
import hmac
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Any, Final, cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.http import RequestFailed, post
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected
from crawlerai.db.models import ApiKey, Job, JobId, WebhookDelivery
from crawlerai.services.jobs import get_job

SIGNATURE_HEADER: Final = "X-CrawlerAI-Signature"
MAX_ATTEMPTS: Final = 3
RETRY_BASE: Final = timedelta(seconds=30)  # 30 s after the first attempt, 2 min after the second
TIMEOUT_S: Final = 10.0
# One delivery per scheduler run: the POST runs inside the run's transaction, so this bounds how long a row stays
# locked, and the scheduler runs a full batch again at once.
DELIVERY_BATCH: Final = 1
UNSIGNED: Final = "no API key submitted the job, so there is no secret to sign with"

# POST a body with headers to a URL; the response status. Raises `SsrfRejected` or `RequestFailed`.
Poster = Callable[[str, bytes, Mapping[str, str]], Awaitable[int]]


@dataclass(frozen=True)
class _Due:
    job_id: JobId
    attempts: int
    url: str
    secret: str | None  # None when no API key submitted the job


def poster(connector: SafeConnector) -> Poster:
    return partial(_post, connector=connector)


async def _post(url: str, body: bytes, headers: Mapping[str, str], *, connector: SafeConnector) -> int:
    return await post(url, body, headers, connector=connector, timeout_s=TIMEOUT_S)


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def retry_delay(attempts: int) -> timedelta:
    """The wait after failed attempt number `attempts` (1 for the first)."""
    delay: timedelta = RETRY_BASE * 4 ** (attempts - 1)
    return delay


async def deliver_webhooks(conn: AsyncConnection, post: Poster, *, batch: int) -> int:
    """Attempt up to `batch` due webhooks, the longest due first, and return how many."""
    due = (
        select(WebhookDelivery.job_id, WebhookDelivery.attempts, Job.webhook_url, ApiKey.webhook_secret)
        .join(Job, Job.id == WebhookDelivery.job_id)
        .outerjoin(ApiKey, ApiKey.id == Job.api_key_id)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= func.now())
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(batch)
        .with_for_update(of=WebhookDelivery, skip_locked=True)
    )
    # `transition_job` owes a webhook only to a job with a URL, so `webhook_url` is set on every row read.
    rows = [
        _Due(row.job_id, row.attempts, cast(str, row.webhook_url), row.webhook_secret)
        for row in await conn.execute(due)
    ]
    for row in rows:
        await _deliver(conn, row, post)
    return len(rows)


async def _deliver(conn: AsyncConnection, row: _Due, post: Poster) -> None:
    if row.secret is None:
        await _set(conn, row, status="failed", last_error=UNSIGNED)
        return
    body = (await get_job(conn, row.job_id)).model_dump_json().encode()
    headers = {"Content-Type": "application/json", SIGNATURE_HEADER: signature(row.secret, body)}
    error = await _attempt(post, row.url, body, headers)
    attempts = row.attempts + 1
    if error is None:
        await _set(conn, row, status="delivered", attempts=attempts, last_error=None)
    elif attempts >= MAX_ATTEMPTS:
        await _set(conn, row, status="failed", attempts=attempts, last_error=error)
    else:
        retry_at = func.now() + retry_delay(attempts)
        await _set(conn, row, attempts=attempts, last_error=error, next_attempt_at=retry_at)


async def _attempt(post: Poster, url: str, body: bytes, headers: Mapping[str, str]) -> str | None:
    """None when the target accepted the webhook (a 2xx, RFC 9110 §15.3); else why not."""
    try:
        status = await post(url, body, headers)
    except (SsrfRejected, RequestFailed) as e:
        return str(e)
    return None if 200 <= status < 300 else f"status {status}"


async def _set(conn: AsyncConnection, row: _Due, **values: Any) -> None:
    await conn.execute(update(WebhookDelivery).where(WebhookDelivery.job_id == row.job_id).values(**values))
