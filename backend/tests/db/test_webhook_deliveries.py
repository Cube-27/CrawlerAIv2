"""A job's webhook deliveries as a caller debugging a receiver reads them (SPEC-10 §4.2): status, attempts, last error
and the receiver's HTTP status, newest first, a page at a time; and their expiry under retention. Hosts are RFC 2606
names."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import Job, JobId, Project, WebhookDelivery, WebhookEvent
from crawlerai.db.webhook_outbox import FORM_BATCH, emit, form_deliveries
from crawlerai.scheduler.retention import RETENTION_BATCH, WEBHOOK_TTL, expire_webhooks
from crawlerai.services.jobs import JobNotFound
from crawlerai.services.webhook_deliveries import DeliveryListQuery, list_deliveries

pytestmark = pytest.mark.anyio

HOOK = "https://hooks.example.test/done"
PAST_TTL = WEBHOOK_TTL + timedelta(hours=1)


async def _job(engine: AsyncEngine) -> JobId:
    """A completed job whose webhook asks for `page` events."""
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"kind": "batch_scrape", "request": {}, "engine_version": "e", "status": "completed"}
    hook = {"webhook_url": HOOK, "webhook_events": ["page"]}
    async with engine.begin() as conn:
        statement = insert(Job).values(project_id=project, **hook, **values).returning(Job.id)
        job_id: JobId = (await conn.execute(statement)).scalar_one()
    return job_id


async def _owe(engine: AsyncEngine, job_id: JobId, deliveries: int, *, events_each: int = 1) -> None:
    """`deliveries` deliveries of the job, each holding `events_each` page events."""
    async with engine.begin() as conn:
        await conn.execute(
            update(Job).where(Job.id == job_id).values(webhook_batch={"max_events": events_each, "max_seconds": 60})
        )
        for index in range(deliveries * events_each):
            await emit(conn, job_id, "page", {"url": f"https://shop.example.test/p/{index}"})
        await form_deliveries(conn, batch=FORM_BATCH)


async def _set(engine: AsyncEngine, job_id: JobId, **values: Any) -> None:
    async with engine.begin() as conn:
        await conn.execute(update(WebhookDelivery).where(WebhookDelivery.job_id == job_id).values(**values))


async def _remaining(engine: AsyncEngine, job_id: JobId) -> tuple[int, int]:
    """How many deliveries and events of the job are stored."""
    async with engine.connect() as conn:
        deliveries = select(func.count()).where(WebhookDelivery.job_id == job_id)
        events = select(func.count()).where(WebhookEvent.job_id == job_id)
        return (await conn.execute(deliveries)).scalar_one(), (await conn.execute(events)).scalar_one()


async def test_deliveries_list_newest_first_with_their_state_and_event_count(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    await _owe(engine, job_id, 2, events_each=3)
    async with engine.begin() as conn:
        oldest = (
            select(WebhookDelivery.id).where(WebhookDelivery.job_id == job_id).order_by(WebhookDelivery.id).limit(1)
        )
        first = (await conn.execute(oldest)).scalar_one()
        await conn.execute(
            update(WebhookDelivery)
            .where(WebhookDelivery.id == first)
            .values(status="failed", attempts=5, last_error="status 410", response_code=410)
        )

    async with engine.connect() as conn:
        page = await list_deliveries(conn, job_id, DeliveryListQuery())

    newest, oldest_out = page.items
    assert (newest.status, newest.attempts, newest.event_count) == ("pending", 0, 3)
    assert newest.next_attempt_at is not None
    assert (newest.last_error, newest.response_code) == (None, None)
    assert (oldest_out.id, oldest_out.status, oldest_out.attempts) == (first, "failed", 5)
    assert (oldest_out.last_error, oldest_out.response_code, oldest_out.event_count) == ("status 410", 410, 3)
    assert oldest_out.next_attempt_at is None
    assert page.next_cursor is None


async def test_deliveries_page_by_cursor_and_belong_to_their_job(engine: AsyncEngine) -> None:
    job_id, other = await _job(engine), await _job(engine)
    await _owe(engine, job_id, 3)
    await _owe(engine, other, 1)

    async with engine.connect() as conn:
        first = await list_deliveries(conn, job_id, DeliveryListQuery(limit=2))
        second = await list_deliveries(conn, job_id, DeliveryListQuery(limit=2, cursor=first.next_cursor))

    assert (len(first.items), first.next_cursor == first.items[-1].id) == (2, True)
    assert (len(second.items), second.next_cursor) == (1, None)
    assert [item.id for item in first.items] == sorted((item.id for item in first.items), reverse=True)
    assert {item.id for item in first.items}.isdisjoint(item.id for item in second.items)


async def test_listing_the_deliveries_of_an_unknown_job_raises(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        unknown, query = JobId(uuid.uuid4()), DeliveryListQuery()
        with pytest.raises(JobNotFound):
            await list_deliveries(conn, unknown, query)


async def test_ended_deliveries_past_the_ttl_go_with_their_events_and_pending_and_young_ones_stay(
    engine: AsyncEngine,
) -> None:
    delivered, failed, pending, young = [await _job(engine) for _ in range(4)]
    for job_id in (delivered, failed, pending, young):
        await _owe(engine, job_id, 1, events_each=2)
    await _set(engine, delivered, status="delivered", created_at=func.now() - PAST_TTL)
    await _set(engine, failed, status="failed", created_at=func.now() - PAST_TTL)
    await _set(engine, pending, created_at=func.now() - PAST_TTL)
    await _set(engine, young, status="delivered", created_at=func.now() - WEBHOOK_TTL + timedelta(hours=1))

    async with engine.begin() as conn:
        expired = await expire_webhooks(conn, batch=RETENTION_BATCH)

    assert expired == 2
    assert await _remaining(engine, delivered) == (0, 0)
    assert await _remaining(engine, failed) == (0, 0)
    assert await _remaining(engine, pending) == (1, 2)
    assert await _remaining(engine, young) == (1, 2)


async def test_expiring_webhooks_takes_the_oldest_first_up_to_the_batch(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    await _owe(engine, job_id, 3)
    async with engine.begin() as conn:
        ids = list((await conn.execute(select(WebhookDelivery.id).order_by(WebhookDelivery.id))).scalars())
        for age_days, delivery_id in zip((50, 40, 60), ids, strict=True):
            await conn.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id == delivery_id)
                .values(status="delivered", created_at=func.now() - timedelta(days=age_days))
            )

    async with engine.begin() as conn:
        assert await expire_webhooks(conn, batch=2) == 2
    async with engine.connect() as conn:
        left = list((await conn.execute(select(WebhookDelivery.id))).scalars())

    assert left == [ids[1]]
