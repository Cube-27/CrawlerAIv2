"""Recurring schedules (§22 "Recurring schedule storage", admitted 2026-10-17): `/v1/schedules` over HTTP, and the
scheduler entry that submits due runs exactly once (`run_due_schedules` of `crawlerai.services.schedules`)."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Job, JobId, Schedule, ScheduleId
from crawlerai.llm.client import NO_LLM
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import schedules
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.schedules import NewBatchSchedule, Submitting
from crawlerai.storage.fs import FsStore
from tests.db.conftest import PRIVATE_HOST, resolve

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/kettles/blue"
BATCH = {"urls": [URL], "formats": ["markdown"]}


async def _never(url: str, policy: FetchPolicy) -> FetchResult:
    raise AssertionError("submitting a job fetches nothing")


@pytest.fixture
def submitting(tmp_path: Path, engine_data: EngineData) -> Submitting:
    fetching = Fetching(Rungs(http=_never, browser=_never), SafeConnector(resolve), FsStore(tmp_path), HostLimiter())
    return Submitting(fetching, engine_data, NO_LLM)


@pytest.fixture
async def created(engine: AsyncEngine, submitting: Submitting) -> ScheduleId:
    """A schedule of a markdown batch, every 5 minutes."""
    new = NewBatchSchedule.model_validate(
        {"name": "kettles", "kind": "batch_scrape", "request": BATCH, "interval_s": 300}
    )
    schedule = await schedules.create_schedule(engine, submitting, new, api_key_id=None)
    return schedule.id


async def _create(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/v1/schedules", json={"name": "kettles", **body})


async def _jobs(engine: AsyncEngine, schedule_id: ScheduleId) -> list[JobId]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(Job.id).where(Job.schedule_id == schedule_id).order_by(Job.id))
        return list(rows.scalars())


async def _due(engine: AsyncEngine, schedule_id: ScheduleId, ago: timedelta) -> datetime:
    """Make the schedule due since `ago`; that due time."""
    async with engine.begin() as conn:
        due = update(Schedule).where(Schedule.id == schedule_id).values(next_run_at=func.now() - ago)
        await conn.execute(due)
        return (await conn.execute(select(Schedule.next_run_at).where(Schedule.id == schedule_id))).scalar_one()


async def _run_due(engine: AsyncEngine, submitting: Submitting) -> int:
    async with engine.begin() as conn:
        return await schedules.run_due_schedules(conn, submitting, batch=10)


async def _row(engine: AsyncEngine, schedule_id: ScheduleId) -> Any:
    async with engine.connect() as conn:
        columns = (Schedule.next_run_at, Schedule.last_run_at, Schedule.last_error, func.now().label("now"))
        return (await conn.execute(select(*columns).where(Schedule.id == schedule_id))).one()


# Over HTTP.


async def test_a_schedule_is_created_listed_and_read(submit_client: httpx.AsyncClient) -> None:
    response = await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=600)

    assert response.status_code == 201, response.text
    schedule = response.json()
    assert (schedule["kind"], schedule["request"]["urls"], schedule["interval_s"]) == ("batch_scrape", [URL], 600)
    assert (schedule["paused"], schedule["last_job_id"], schedule["timezone"]) == (False, None, "UTC")
    wait = datetime.fromisoformat(schedule["next_run_at"]) - datetime.fromisoformat(schedule["created_at"])
    assert timedelta(seconds=599) < wait <= timedelta(seconds=601)
    listed = (await submit_client.get("/v1/schedules")).json()["items"]
    assert schedule["id"] in [item["id"] for item in listed]
    assert (await submit_client.get(f"/v1/schedules/{schedule['id']}")).json() == schedule


async def test_schedule_problems(submit_client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    actions = {"url": URL, "formats": ["records"], "page_kind": "listing", "schema": {"fields": ["title"]}}
    actions["browser_actions"] = {}
    responses = {
        "private target": await _create(
            submit_client, kind="batch_scrape", request={**BATCH, "urls": [f"https://{PRIVATE_HOST}/"]}, interval_s=60
        ),
        "no cadence": await _create(submit_client, kind="batch_scrape", request=BATCH),
        "two cadences": await _create(
            submit_client, kind="batch_scrape", request=BATCH, cron="* * * * *", interval_s=60
        ),
        "short interval": await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=30),
        "huge interval": await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=2**31),
        "six fields": await _create(submit_client, kind="batch_scrape", request=BATCH, cron="0 0 * * * *"),
        "unknown zone": await _create(
            submit_client, kind="batch_scrape", request=BATCH, cron="0 0 * * *", timezone="X"
        ),
        "browser actions": await _create(submit_client, kind="scrape", request=actions, interval_s=60),
        "secret values": await _create(
            submit_client, kind="batch_scrape", request={**BATCH, "fetch": {"cookies": {"sid": "abc"}}}, interval_s=60
        ),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == {
        "private target": (422, "ssrf_rejected"),
        "no cadence": (422, "validation"),
        "two cadences": (422, "validation"),
        "short interval": (422, "validation"),
        "huge interval": (422, "validation"),
        "six fields": (422, "validation"),
        "unknown zone": (422, "validation"),
        "browser actions": (422, "validation"),
        "secret values": (422, "validation"),
    }
    async with engine.connect() as conn:
        assert (await conn.execute(select(Schedule.id))).all() == []


# Concurrent changes.


# The scheduler entry.


async def test_a_due_run_is_submitted_once_by_two_schedulers_at_once(
    engine: AsyncEngine, submitting: Submitting, created: ScheduleId
) -> None:
    due = await _due(engine, created, timedelta(seconds=1))

    ran = await asyncio.gather(_run_due(engine, submitting), _run_due(engine, submitting))

    assert sorted(ran) == [0, 1]
    assert len(await _jobs(engine, created)) == 1
    row = await _row(engine, created)
    assert (row.next_run_at, row.last_error) == (due + timedelta(seconds=300), None)
    assert await _run_due(engine, submitting) == 0


# Records.


async def test_a_private_crawl_target_is_refused_at_creation(engine: AsyncEngine, submitting: Submitting) -> None:
    body = {"name": "c", "kind": "crawl", "request": {"url": f"https://{PRIVATE_HOST}/", "formats": ["links"]}}
    new = schedules.NewCrawlSchedule.model_validate({**body, "cron": "0 * * * *"})

    with pytest.raises(TargetsRejected):
        await schedules.create_schedule(engine, submitting, new, api_key_id=None)
