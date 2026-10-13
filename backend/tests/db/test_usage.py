"""Usage events and per-job budgets (SPEC-01 §4.6)."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.db.models import Job, JobId, Project, UrlTask, UsageEvent, UsageResource
from crawlerai.db.usage import budget_remaining, record_usage

pytestmark = pytest.mark.anyio


async def _job_id(conn: AsyncConnection, **columns: Any) -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "crawl", "request": {}, "engine_version": "0+cal.0"}
    job_id: JobId = (await conn.execute(insert(Job).values(**{**values, **columns}).returning(Job.id))).scalar_one()
    return job_id


async def _usage(conn: AsyncConnection, job_id: JobId) -> dict[str, Any]:
    usage: dict[str, Any] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
    return usage


async def test_recording_usage_writes_an_event_and_adds_to_the_job_counter(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    await record_usage(
        conn, job_id, "llm_tokens_in", provider="p", model_or_pool="m", quantity=120, metadata={"prompt_kind": "c"}
    )

    event = (await conn.execute(select(UsageEvent))).one()
    assert (event.job_id, event.resource, event.provider, event.model_or_pool, event.quantity, event.metadata) == (
        job_id,
        "llm_tokens_in",
        "p",
        "m",
        120,
        {"prompt_kind": "c"},
    )
    assert event.id.version == 7
    assert await _usage(conn, job_id) == {"llm_tokens_in": 120}


async def test_counters_add_up_per_resource(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    recordings: list[tuple[UsageResource, int]] = [
        ("llm_calls", 1),
        ("http_requests", 1),
        ("llm_calls", 1),
        ("browser_seconds", 7),
    ]
    for resource, quantity in recordings:
        await record_usage(conn, job_id, resource, provider=None, model_or_pool=None, quantity=quantity)

    assert await _usage(conn, job_id) == {"llm_calls": 2, "http_requests": 1, "browser_seconds": 7}
    assert (await conn.execute(select(func.count()).select_from(UsageEvent))).scalar_one() == 4


async def test_an_event_without_metadata_stores_an_empty_object(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    await record_usage(conn, job_id, "proxy_bytes", provider=None, model_or_pool="pool-a", quantity=0)

    assert (await conn.execute(select(UsageEvent.metadata_))).scalar_one() == {}


@pytest.mark.parametrize(
    ("resource", "quantity", "constraint"),
    [("pages", 1, "ck_usage_event_resource"), ("llm_calls", -1, "ck_usage_event_quantity_non_negative")],
)
async def test_usage_rejects_values_outside_its_domain(
    conn: AsyncConnection, resource: Any, quantity: int, constraint: str
) -> None:
    job_id = await _job_id(conn)

    with pytest.raises(IntegrityError, match=constraint):
        await record_usage(conn, job_id, resource, provider=None, model_or_pool=None, quantity=quantity)


async def test_concurrent_recordings_lose_no_increment(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        job_id = await _job_id(conn)

    async def record(times: int) -> None:
        for _ in range(times):
            async with engine.begin() as conn:
                await record_usage(conn, job_id, "llm_calls", provider=None, model_or_pool=None, quantity=3)

    await asyncio.gather(*(record(25) for _ in range(8)))

    async with engine.connect() as conn:
        assert await _usage(conn, job_id) == {"llm_calls": 600}
        events = select(func.count(), func.sum(UsageEvent.quantity)).where(UsageEvent.job_id == job_id)
        assert tuple((await conn.execute(events)).one()) == (200, 600)


async def test_a_rolled_back_recording_leaves_no_event_and_no_increment(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        job_id = await _job_id(conn)

    async with engine.connect() as conn:
        async with conn.begin() as transaction:
            await record_usage(conn, job_id, "llm_calls", provider=None, model_or_pool=None, quantity=1)
            await transaction.rollback()
        assert await _usage(conn, job_id) == {}
        assert (await conn.execute(select(func.count()).select_from(UsageEvent))).scalar_one() == 0


async def test_a_job_without_a_budget_has_no_limit(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn, request={"urls": []})

    assert await budget_remaining(conn, job_id, "llm_calls") is None


async def test_a_budget_on_another_resource_does_not_limit_this_one(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn, request={"budget": {"pages": 5}})

    assert await budget_remaining(conn, job_id, "llm_calls") is None


@pytest.mark.parametrize(("used", "remaining"), [(0, 10), (4, 6), (10, 0), (13, 0)])
async def test_the_remaining_budget_is_what_the_job_has_not_used(
    conn: AsyncConnection, used: int, remaining: int
) -> None:
    job_id = await _job_id(conn, request={"budget": {"llm_calls": 10, "browser_seconds": 2}})
    if used:
        await record_usage(conn, job_id, "llm_calls", provider=None, model_or_pool=None, quantity=used)

    assert await budget_remaining(conn, job_id, "llm_calls") == remaining
    assert await budget_remaining(conn, job_id, "browser_seconds") == 2


async def test_the_page_budget_counts_tasks_that_ended(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn, request={"budget": {"pages": 5}})
    statuses = ["queued", "claimed", "done", "done", "failed", "cancelled"]
    rows = [
        {"job_id": job_id, "url": f"https://example.test/p/{i}", "canonical_url": f"https://example.test/p/{i}"}
        | {"status": status}
        for i, status in enumerate(statuses)
    ]
    await conn.execute(insert(UrlTask), rows)

    assert await budget_remaining(conn, job_id, "pages") == 2
