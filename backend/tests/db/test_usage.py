"""Usage events and per-job budgets."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from snowcrawl.db.models import Job, JobId, Project, UsageEvent
from snowcrawl.db.usage import budget_remaining, record_usage

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
    assert await _usage(conn, job_id) == {"llm_tokens_in": 120}


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
            assert await _usage(conn, job_id) == {"llm_calls": 1}
            await transaction.rollback()
        assert await _usage(conn, job_id) == {}
        assert (await conn.execute(select(func.count()).select_from(UsageEvent))).scalar_one() == 0


@pytest.mark.parametrize(("used", "remaining"), [(0, 10), (4, 6), (13, 0)])
async def test_the_remaining_budget_is_what_the_job_has_not_used(
    conn: AsyncConnection, used: int, remaining: int
) -> None:
    job_id = await _job_id(conn, request={"budget": {"llm_calls": 10, "browser_seconds": 2}})
    if used:
        await record_usage(conn, job_id, "llm_calls", provider=None, model_or_pool=None, quantity=used)

    assert await budget_remaining(conn, job_id, "llm_calls") == remaining
    assert await budget_remaining(conn, job_id, "browser_seconds") == 2


async def _cap_llm_calls(conn: AsyncConnection, cap: int | None) -> None:
    await conn.execute(update(Project).where(Project.name == "default").values(llm_call_cap=cap))


async def test_a_jobs_own_llm_call_budget_wins_over_its_projects_cap(conn: AsyncConnection) -> None:
    await _cap_llm_calls(conn, 5)
    job_id = await _job_id(conn, request={"budget": {"llm_calls": 20}})

    assert await budget_remaining(conn, job_id, "llm_calls") == 20
