"""Recurring schedules (§22 "Recurring schedule storage", admitted 2026-10-17): `/v1/schedules` over HTTP, and the
scheduler entry that submits due runs exactly once (`run_due_schedules` of `crawlerai.services.schedules`).

The app runs as `submit_client` (conftest) sets it up: nothing leaves the process, and `PRIVATE_HOST` resolves to a
private address. Hosts are RFC 2606 names.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.cli import main
from crawlerai.db.models import Job, JobId, Schedule, ScheduleId
from crawlerai.llm.client import NO_LLM
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import schedules
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.schedules import NewBatchSchedule, NewExtractSchedule, Submitting, Unschedulable
from crawlerai.services.scrape import RecordsUnavailable
from crawlerai.storage.fs import FsStore
from tests.db.conftest import PRIVATE_HOST, resolve

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/kettles/blue"
HOOK = "https://hooks.example.test/runs"
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


async def test_a_scrape_is_scheduled_as_the_batch_of_its_url(submit_client: httpx.AsyncClient) -> None:
    scrape = {"url": URL, "formats": ["markdown", "links"], "timeout_s": 30}

    response = await _create(submit_client, kind="scrape", request=scrape, cron="0 6 * * 1", timezone="Europe/Berlin")

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["kind"], body["request"]["urls"], body["request"]["formats"]) == (
        "batch_scrape",
        [URL],
        ["markdown", "links"],
    )
    assert datetime.fromisoformat(body["next_run_at"]).astimezone().weekday() in {0, 6}  # Monday 06:00 Berlin


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


async def test_run_now_submits_a_job_the_schedules_history_lists(submit_client: httpx.AsyncClient) -> None:
    hooked = {**BATCH, "webhook_url": HOOK, "webhook_events": ["record", "job_completed"]}
    schedule = (await _create(submit_client, kind="batch_scrape", request=hooked, interval_s=3600)).json()

    run = await submit_client.post(f"/v1/schedules/{schedule['id']}/run")

    assert run.status_code == 202, run.text
    job_id = run.json()["job_id"]
    history = (await submit_client.get("/v1/jobs", params={"schedule_id": schedule["id"]})).json()["items"]
    assert [(job["id"], job["schedule_id"], job["webhook_url"]) for job in history] == [(job_id, schedule["id"], HOOK)]
    after = (await submit_client.get(f"/v1/schedules/{schedule['id']}")).json()
    assert (after["last_job_id"], after["next_run_at"]) == (job_id, schedule["next_run_at"])


async def test_a_paused_schedule_resumes_from_its_next_time_after_now(
    submit_client: httpx.AsyncClient, engine: AsyncEngine, submitting: Submitting
) -> None:
    schedule = (await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=300)).json()
    schedule_id = ScheduleId(schedule["id"])

    paused = await submit_client.post(f"/v1/schedules/{schedule_id}/pause")
    await _due(engine, schedule_id, timedelta(hours=1))
    ran = await _run_due(engine, submitting)
    resumed = (await submit_client.post(f"/v1/schedules/{schedule_id}/resume")).json()

    assert (paused.json()["paused"], ran, await _jobs(engine, schedule_id)) == (True, 0, [])
    row = await _row(engine, schedule_id)
    assert resumed["paused"] is False
    assert row.now < row.next_run_at <= row.now + timedelta(seconds=300)


async def test_an_update_changes_name_and_cadence_and_checks_the_request(
    submit_client: httpx.AsyncClient,
) -> None:
    schedule = (await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=300)).json()
    path = f"/v1/schedules/{schedule['id']}"

    renamed = await submit_client.patch(path, json={"name": "daily kettles", "cron": "15 3 * * *"})
    kind_alone = await submit_client.patch(path, json={"kind": "crawl"})
    private = await submit_client.patch(
        path, json={"kind": "batch_scrape", "request": {**BATCH, "urls": [f"https://{PRIVATE_HOST}/"]}}
    )
    invalid = await submit_client.patch(path, json={"kind": "crawl", "request": {"url": URL}})
    huge = await submit_client.patch(path, json={"interval_s": 2**31})

    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert (body["name"], body["cron"], body["interval_s"]) == ("daily kettles", "15 3 * * *", None)
    assert datetime.fromisoformat(body["next_run_at"]).astimezone().strftime("%M") == "15"
    assert (kind_alone.status_code, private.status_code, invalid.status_code, huge.status_code) == (422, 422, 422, 422)
    assert private.json()["type"] == "ssrf_rejected"
    assert "request.formats" in [error["field"] for error in invalid.json()["errors"]]


async def test_a_deleted_schedules_jobs_stay(submit_client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    schedule = (await _create(submit_client, kind="batch_scrape", request=BATCH, interval_s=300)).json()
    job_id = (await submit_client.post(f"/v1/schedules/{schedule['id']}/run")).json()["job_id"]

    deleted = await submit_client.delete(f"/v1/schedules/{schedule['id']}")

    assert deleted.status_code == 204
    assert (await submit_client.get(f"/v1/schedules/{schedule['id']}")).status_code == 404
    assert (await submit_client.get(f"/v1/jobs/{job_id}")).json()["schedule_id"] is None


# Concurrent changes.


async def _waiting_on_a_lock(engine: AsyncEngine) -> None:
    """Return once another session of the database waits on a lock (PostgreSQL `pg_stat_activity.wait_event_type`)."""
    waiting = (
        select(func.count())
        .select_from(text("pg_stat_activity"))
        .where(text("datname = current_database() AND wait_event_type = 'Lock'"))
    )
    async with engine.connect() as conn:
        for _ in range(500):
            if (await conn.execute(waiting)).scalar_one():
                return
            await asyncio.sleep(0.01)
    raise AssertionError("no session waited on a lock")


async def test_an_update_from_a_stale_read_keeps_a_concurrent_cadence_change(
    engine: AsyncEngine, submitting: Submitting, created: ScheduleId, monkeypatch: pytest.MonkeyPatch
) -> None:
    checked = schedules._checked

    async def cadence_changed_meanwhile(*args: Any) -> Any:
        # Another update commits while this one checks its new request, after this one read the schedule.
        await schedules.update_schedule(engine, submitting, created, schedules.ScheduleUpdate(interval_s=900))
        return await checked(*args)

    monkeypatch.setattr(schedules, "_checked", cadence_changed_meanwhile)
    change = schedules.ScheduleUpdate(name="renamed", kind="batch_scrape", request=BATCH)

    updated = await schedules.update_schedule(engine, submitting, created, change)

    assert (updated.name, updated.interval_s) == ("renamed", 900)


async def test_a_resume_racing_a_pause_runs_from_its_next_time_after_now(
    engine: AsyncEngine, created: ScheduleId
) -> None:
    await _due(engine, created, timedelta(hours=1))
    async with engine.connect() as pausing:
        await pausing.begin()
        await schedules.set_paused(pausing, created, paused=True)

        async def resume() -> None:
            async with engine.begin() as conn:
                await schedules.set_paused(conn, created, paused=False)

        resuming = asyncio.create_task(resume())
        await _waiting_on_a_lock(engine)
        await pausing.commit()
        await resuming

    row = await _row(engine, created)
    # The resume read the pause it waited on: the hour it missed is not made up.
    assert row.now < row.next_run_at <= row.now + timedelta(seconds=300)


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


async def test_a_schedule_that_missed_many_runs_runs_once_on_its_phase(
    engine: AsyncEngine, submitting: Submitting, created: ScheduleId
) -> None:
    due = await _due(engine, created, timedelta(minutes=50, seconds=10))

    await _run_due(engine, submitting)

    assert len(await _jobs(engine, created)) == 1
    row = await _row(engine, created)
    assert row.now < row.next_run_at <= row.now + timedelta(seconds=300)
    assert (row.next_run_at - due).total_seconds() % 300 == 0


async def test_a_refused_run_stores_no_job_and_says_why(
    engine: AsyncEngine, submitting: Submitting, created: ScheduleId
) -> None:
    async with engine.begin() as conn:
        private = {**BATCH, "urls": [f"https://{PRIVATE_HOST}/"]}
        await conn.execute(update(Schedule).where(Schedule.id == created).values(request=private))
    await _due(engine, created, timedelta(seconds=1))

    await _run_due(engine, submitting)

    assert await _jobs(engine, created) == []
    row = await _row(engine, created)
    assert row.last_error is not None
    assert PRIVATE_HOST not in row.last_error
    assert row.next_run_at > row.now


async def test_a_scheduled_job_carries_its_requests_webhook_options(
    engine: AsyncEngine, submitting: Submitting
) -> None:
    hooked = {
        **BATCH,
        "webhook_url": HOOK,
        "webhook_events": ["page"],
        "webhook_batch": {"max_events": 5, "max_seconds": 30},
    }
    new = NewBatchSchedule.model_validate(
        {"name": "pages", "kind": "batch_scrape", "request": hooked, "interval_s": 60}
    )
    schedule = await schedules.create_schedule(engine, submitting, new, api_key_id=None)
    await _due(engine, schedule.id, timedelta(seconds=1))

    await _run_due(engine, submitting)

    async with engine.connect() as conn:
        columns = (Job.webhook_url, Job.webhook_events, Job.webhook_batch)
        row = (await conn.execute(select(*columns).where(Job.schedule_id == schedule.id))).one()
    assert tuple(row) == (HOOK, ["page"], {"max_events": 5, "max_seconds": 30.0})


# Records.


async def test_a_records_schedule_stores_its_inline_schema_by_id(
    engine: AsyncEngine, submitting: Submitting, schema_name: str
) -> None:
    inline = {
        "name": schema_name,
        "page_kind": "detail",
        "fields": {"title": {"type": "text", "required": True, "description": "The name"}},
    }
    request = {"urls": [URL], "formats": ["records"], "page_kind": "detail", "schema": {"inline": inline}}
    new = NewBatchSchedule.model_validate({"name": "r", "kind": "batch_scrape", "request": request, "interval_s": 60})

    schedule = await schedules.create_schedule(engine, submitting, new, api_key_id=None)
    await _due(engine, schedule.id, timedelta(seconds=1))
    await _run_due(engine, submitting)

    assert set(schedule.request["schema"]) == {"id"}
    async with engine.connect() as conn:
        job_schema = select(Job.schema_id).where(Job.schedule_id == schedule.id)
        assert str((await conn.execute(job_schema)).scalar_one()) == schedule.request["schema"]["id"]


async def test_an_extract_with_a_prompt_is_refused(engine: AsyncEngine, submitting: Submitting) -> None:
    request = {"urls": [URL], "page_kind": "detail", "schema": {"prompt": "kettles"}}
    new = NewExtractSchedule.model_validate({"name": "e", "kind": "extract", "request": request, "interval_s": 60})

    with pytest.raises(Unschedulable):
        await schedules.create_schedule(engine, submitting, new, api_key_id=None)


async def test_a_private_crawl_target_is_refused_at_creation(engine: AsyncEngine, submitting: Submitting) -> None:
    body = {"name": "c", "kind": "crawl", "request": {"url": f"https://{PRIVATE_HOST}/", "formats": ["links"]}}
    new = schedules.NewCrawlSchedule.model_validate({**body, "cron": "0 * * * *"})

    with pytest.raises(TargetsRejected):
        await schedules.create_schedule(engine, submitting, new, api_key_id=None)


async def test_the_cli_lists_pauses_and_resumes_schedules(
    created: ScheduleId, database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)

    async def cli(*argv: str) -> list[dict[str, Any]]:
        # The CLI runs its own event loop, so it runs on a thread of its own here.
        await asyncio.to_thread(main, list(argv))
        return [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    listed = await cli("schedules", "list")
    paused = await cli("schedules", "pause", str(created))
    resumed = await cli("schedules", "resume", str(created))

    assert [(line["id"], line["interval_s"], line["paused"]) for line in listed] == [(str(created), 300, False)]
    assert [line["paused"] for line in paused + resumed] == [True, False]
    with pytest.raises(SystemExit) as exited:
        await cli("schedules", "pause", "0192a000-0000-7000-8000-00000000dead")
    assert exited.value.code == 2


async def test_a_records_extract_is_refused_without_the_engines_data(
    engine: AsyncEngine, submitting: Submitting, schema_name: str
) -> None:
    inline = {
        "name": schema_name,
        "page_kind": "detail",
        "fields": {"title": {"type": "text", "required": True, "description": "The name"}},
    }
    request = {"urls": [URL], "page_kind": "detail", "schema": {"inline": inline}}
    new = NewExtractSchedule.model_validate({"name": "e", "kind": "extract", "request": request, "interval_s": 60})
    without_data = Submitting(submitting.fetching, None, submitting.llm)

    with pytest.raises(RecordsUnavailable):
        await schedules.create_schedule(engine, without_data, new, api_key_id=None)
    async with engine.connect() as conn:
        assert (await conn.execute(select(Schedule.id))).all() == []
