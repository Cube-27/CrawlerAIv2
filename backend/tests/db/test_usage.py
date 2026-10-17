"""Usage events and per-job budgets (SPEC-01 §4.6)."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.types import AttemptRecord
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import Job, JobId, Project, UrlTask, UsageEvent, UsageResource
from crawlerai.db.usage import budget_remaining, record_usage
from crawlerai.services.scrape_steps import record_fetch_usage

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


async def test_a_budget_on_another_resource_does_not_limit_this_one(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn, request={"budget": {"pages": 5}})

    assert await budget_remaining(conn, job_id, "llm_calls") is None


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


@pytest.mark.parametrize("request_", [{}, {"budget": None}, {"budget": {"pages": 5}}])
async def test_a_job_without_its_own_llm_call_budget_takes_its_projects_cap(
    conn: AsyncConnection, request_: dict[str, Any]
) -> None:
    job_id = await _job_id(conn, request=request_)
    await record_usage(conn, job_id, "llm_calls", provider=None, model_or_pool=None, quantity=3)

    assert await budget_remaining(conn, job_id, "llm_calls") is None  # no cap: no limit
    await _cap_llm_calls(conn, 5)
    assert await budget_remaining(conn, job_id, "llm_calls") == 2
    assert await budget_remaining(conn, job_id, "browser_seconds") is None


async def test_a_jobs_own_llm_call_budget_wins_over_its_projects_cap(conn: AsyncConnection) -> None:
    await _cap_llm_calls(conn, 5)
    job_id = await _job_id(conn, request={"budget": {"llm_calls": 20}})

    assert await budget_remaining(conn, job_id, "llm_calls") == 20


async def test_the_page_budget_counts_tasks_that_ended(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn, request={"budget": {"pages": 5}})
    statuses = ["queued", "claimed", "done", "done", "failed", "cancelled"]
    urls = [f"https://example.test/p/{i}" for i in range(len(statuses))]
    rows = [
        {"job_id": job_id, "url": url, "canonical_url": url, "status": status}
        for url, status in zip(urls, statuses, strict=True)
    ]
    await conn.execute(insert(UrlTask), rows)

    assert await budget_remaining(conn, job_id, "pages") == 2


def _attempt(method: CaptureMethod, transferred: int, duration_ms: int = 1) -> AttemptRecord:
    return AttemptRecord(method=method, status=200, block_class="ok", duration_ms=duration_ms, transferred=transferred)


async def test_a_fetch_through_a_proxy_pool_counts_the_bytes_of_every_attempt(conn: AsyncConnection) -> None:
    # D-1381: every rung's attempt through the pool, HTTP, browser and API alike.
    job_id = await _job_id(conn)
    attempts = [_attempt("http", 900), _attempt("browser", 52_000, duration_ms=2500), _attempt("api", 300)]

    await record_fetch_usage(conn, job_id, attempts, "dc")

    assert await _usage(conn, job_id) == {"http_requests": 2, "browser_seconds": 3, "proxy_bytes": 53_200}
    pools = set((await conn.execute(select(UsageEvent.model_or_pool).where(UsageEvent.job_id == job_id))).scalars())
    assert pools == {"dc"}


async def test_a_fetch_without_a_proxy_pool_counts_no_proxy_bytes(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    await record_fetch_usage(conn, job_id, [_attempt("http", 900)], None)

    assert await _usage(conn, job_id) == {"http_requests": 1}
