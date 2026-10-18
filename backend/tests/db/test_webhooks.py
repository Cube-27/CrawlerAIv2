"""Webhook deliveries (jobs spec): the events a job owes are grouped into deliveries (`form_deliveries`) as its
`webhook_batch` says, and `deliver_webhooks` POSTs each, signed with the submitting key's secret, in at most 5
attempts with backoff, through the SSRF guard. Hosts are RFC 2606 names; the poster is a stand-in except where the
guard itself is under test.
"""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from ipaddress import ip_address
from typing import Any

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.api.webhooks import MAX_ATTEMPTS, Poster, deliver_webhooks, poster
from crawlerai.db.jobs import transition_job
from crawlerai.db.keys import CreatedKey, create_key
from crawlerai.db.models import (
    ApiKey,
    ApiKeyId,
    Job,
    JobEvent,
    JobId,
    JobStatus,
    Project,
    UrlTask,
    WebhookDelivery,
    WebhookEvent,
    WebhookEventType,
)
from crawlerai.db.webhook_outbox import FORM_BATCH, JOB_END_EVENTS, form_deliveries

pytestmark = pytest.mark.anyio

HOOK = "https://hooks.example.test/done"


@dataclass
class Receiver:
    """Answers each POST with the next of `replies`: a status, or an exception to raise."""

    replies: list[int | Exception]
    sent: list[tuple[str, bytes, dict[str, str]]] = field(default_factory=list)

    async def __call__(self, url: str, body: bytes, headers: Mapping[str, str]) -> int:
        self.sent.append((url, body, dict(headers)))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(body) for _, body, _ in self.sent]


@pytest.fixture
async def key(engine: AsyncEngine) -> AsyncIterator[CreatedKey]:
    async with engine.begin() as conn:
        created = await create_key(conn, "webhook-test")
    yield created
    async with engine.begin() as conn:
        # The key's jobs go first, as they reference it; the `engine` fixture deletes the rest.
        jobs = select(Job.id).where(Job.api_key_id == created.id).scalar_subquery()
        for model in (WebhookEvent, WebhookDelivery, JobEvent, UrlTask):
            await conn.execute(delete(model).where(model.job_id.in_(jobs)))
        await conn.execute(delete(Job).where(Job.api_key_id == created.id))
        await conn.execute(delete(ApiKey).where(ApiKey.id == created.id))


async def _running(
    engine: AsyncEngine,
    api_key_id: ApiKeyId | None,
    events: tuple[WebhookEventType, ...] = JOB_END_EVENTS,
    batch: dict[str, Any] | None = None,
) -> JobId:
    """A running job of `api_key_id` whose webhook asks for `events`, grouped by `batch`, with one done task."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"kind": "batch_scrape", "request": {}, "engine_version": "e", "status": "running"}
        hook = {"webhook_url": HOOK, "webhook_events": list(events), "webhook_batch": batch}
        job = insert(Job).values(project_id=project, api_key_id=api_key_id, **hook, **values)
        job_id: JobId = (await conn.execute(job.returning(Job.id))).scalar_one()
        url = "https://shop.example.test/p/1"
        task = {"job_id": job_id, "url": url, "canonical_url": url, "status": "done", "outcome": "extracted"}
        await conn.execute(insert(UrlTask).values(**task))
    return job_id


async def _end(engine: AsyncEngine, job_id: JobId, end: JobStatus = "completed") -> None:
    async with engine.begin() as conn:
        await transition_job(conn, job_id, end)


async def _ended(engine: AsyncEngine, api_key_id: ApiKeyId | None, end: JobStatus = "completed") -> JobId:
    job_id = await _running(engine, api_key_id)
    await _end(engine, job_id, end)
    return job_id


async def _form(engine: AsyncEngine) -> int:
    async with engine.begin() as conn:
        return await form_deliveries(conn, batch=FORM_BATCH)


async def _deliver(engine: AsyncEngine, post: Poster) -> int:
    await _form(engine)
    async with engine.begin() as conn:
        return await deliver_webhooks(conn, post, batch=1)


async def _delivery(engine: AsyncEngine, job_id: JobId) -> tuple[str, int, str | None, timedelta]:
    """The job's one delivery: its status, attempts, last error, and how long until its next attempt."""
    async with engine.connect() as conn:
        columns = (WebhookDelivery.status, WebhookDelivery.attempts, WebhookDelivery.last_error)
        query = select(*columns, WebhookDelivery.next_attempt_at, func.now()).where(WebhookDelivery.job_id == job_id)
        status, attempts, error, due_at, now = (await conn.execute(query)).one()
        return status, attempts, error, due_at - now


async def _make_due(engine: AsyncEngine, job_id: JobId) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            update(WebhookDelivery).where(WebhookDelivery.job_id == job_id).values(next_attempt_at=func.now())
        )


async def test_a_job_end_delivery_carries_the_jobs_summary_signed_with_the_keys_secret(
    engine: AsyncEngine, key: CreatedKey
) -> None:
    job_id = await _ended(engine, key.id)
    post = Receiver([204])

    assert await _deliver(engine, post) == 1

    [(url, body, headers)] = post.sent
    expected = "sha256=" + hmac.new(key.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    assert (url, headers["X-CrawlerAI-Signature"], headers["Content-Type"]) == (HOOK, expected, "application/json")
    delivery = json.loads(body)
    assert (delivery["job_id"], delivery["attempt"]) == (str(job_id), 1)
    assert headers["X-CrawlerAI-Delivery"] == delivery["delivery_id"]
    [event] = delivery["events"]
    assert (event["type"], event["data"]["job_id"]) == ("job_completed", str(job_id))
    summary = event["data"]["job"]
    assert (summary["id"], summary["status"], summary["counts"]["done"]) == (str(job_id), "completed", 1)
    assert (await _delivery(engine, job_id))[:3] == ("delivered", 1, None)


async def test_a_refused_delivery_is_retried_with_backoff_then_given_up(engine: AsyncEngine, key: CreatedKey) -> None:
    job_id = await _ended(engine, key.id)
    post = Receiver([500, 302, 404, 500, 503])

    await _deliver(engine, post)
    status, attempts, error, wait = await _delivery(engine, job_id)
    assert (status, attempts, error) == ("pending", 1, "status 500")
    assert timedelta(seconds=25) < wait <= timedelta(seconds=30)
    assert await _deliver(engine, post) == 0  # not due yet

    await _make_due(engine, job_id)
    await _deliver(engine, post)
    status, attempts, error, wait = await _delivery(engine, job_id)
    assert (status, attempts, error) == ("pending", 2, "status 302")
    assert timedelta(seconds=115) < wait <= timedelta(minutes=2)

    for _ in range(MAX_ATTEMPTS - 2):
        await _make_due(engine, job_id)
        await _deliver(engine, post)
    assert (await _delivery(engine, job_id))[:3] == ("failed", MAX_ATTEMPTS, "status 503")
    assert [body["attempt"] for body in post.bodies()] == [1, 2, 3, 4, 5]
    assert len({headers["X-CrawlerAI-Delivery"] for _, _, headers in post.sent}) == 1
    assert await _deliver(engine, Receiver([])) == 0


async def test_a_webhook_url_that_resolves_to_a_private_address_is_never_posted(
    engine: AsyncEngine, key: CreatedKey
) -> None:
    job_id = await _ended(engine, key.id)

    async def private(_host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.1")]

    await _deliver(engine, poster(SafeConnector(private)))

    assert (await _delivery(engine, job_id))[:3] == ("pending", 1, "ssrf_rejected: private_address")
