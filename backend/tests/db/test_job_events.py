"""Run events (SPEC-10 §4.2): the events a finished task leaves, the webhook a job's end owes, and the event stream
through the events service and over SSE (`GET /v1/jobs/{id}/events`), with `Last-Event-ID` resume.

Jobs, tasks and events are written as the queue and the page tasks leave them. Hosts are RFC 2606 names.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.db.jobs import record_event, transition_job
from crawlerai.db.keys import create_key
from crawlerai.db.models import (
    ApiKey,
    Capture,
    Extraction,
    Job,
    JobEvent,
    JobEventId,
    JobId,
    JobStatus,
    Project,
    Record,
    Site,
    TaskRecord,
    UrlTask,
    WebhookDelivery,
)
from crawlerai.db.queue import cancel_task, claim_tasks, complete_task, fail_task
from crawlerai.recurring.record_fp import document_digest
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument
from crawlerai.services import events, jobs
from crawlerai.services.events import StreamEvent

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/p/1"


async def _job(conn: AsyncConnection, status: JobStatus = "running", **columns: Any) -> JobId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values: dict[str, Any] = {"project_id": project, "kind": "batch_scrape", "request": {}, "engine_version": "e"}
    values["status"] = status
    job_id: JobId = (await conn.execute(insert(Job).values(**values | columns).returning(Job.id))).scalar_one()
    return job_id


async def _task(conn: AsyncConnection, job_id: JobId, url: str = URL) -> None:
    await conn.execute(insert(UrlTask).values(job_id=job_id, url=url, canonical_url=url))


async def _events(conn: AsyncConnection, job_id: JobId) -> list[tuple[str, dict[str, Any]]]:
    rows = await conn.execute(
        select(JobEvent.kind, JobEvent.payload).where(JobEvent.job_id == job_id).order_by(JobEvent.id)
    )
    return [(row.kind, row.payload) for row in rows]


async def _page(conn: AsyncConnection, job_id: JobId, *, stored: bool = True) -> Any:
    """A claimed task of `job_id` whose page was fetched by the browser and extracted with 2 LLM calls; the task stands
    for one record that published `title` and abstained on `price` and `brand`. With `stored`, its extraction stored
    the record; without, the record is unchanged: an earlier task's extraction stored it (SPEC-11 §4.4). Returns the
    task and the capture."""
    if not stored:
        await _task(conn, job_id, "https://shop.example.test/earlier")
    await _task(conn, job_id)
    [*earlier, task] = await claim_tasks(conn, "w1", 2)
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    site = insert(Site).values(project_id=project, host="events.example.test").returning(Site.id)
    site_id = (await conn.execute(site)).scalar_one()
    capture = {
        "site_id": site_id,
        "url": URL,
        "fetched_at": func.now(),
        "method": "browser",
        "status_code": 200,
        "final_url": URL,
        "block_class": "ok",
        "object_key": f"captures/{task.id}",
        "html_sha256": "0" * 64,
        "size_bytes": 1,
        "duration_ms": 1,
    }
    capture_id = (await conn.execute(insert(Capture).values(**capture).returning(Capture.id))).scalar_one()
    extraction_ids = []
    for extracting in (*earlier, task):
        values = {"url_task_id": extracting.id, "engine_version": "e", "mode": "config", "llm_calls": 2}
        extraction = insert(Extraction).values(values)
        extraction_ids.append((await conn.execute(extraction.returning(Extraction.id))).scalar_one())
    text = FieldSpec(type=FieldType.TEXT, description="d")
    fields = {"title": text, "price": text, "brand": text}
    document = SchemaDocument(name=f"synthetic_{task.id.hex}", page_kind="detail", fields=fields)
    schema = await registry.create(conn, document, "user")
    meta = {"title": {"status": "published"}, "price": {"status": "abstained"}, "brand": {"status": "abstained"}}
    record = {
        "extraction_id": extraction_ids[0],
        "job_id": job_id,
        "site_id": site_id,
        "schema_id": schema.id,
        "schema_digest": document_digest(schema),
        "entity_key": URL,
        "data": {"title": "Kettle"},
        "field_meta": meta,
        "complete": True,
        "mode": "config",
    }
    record_id = (await conn.execute(insert(Record).values(**record).returning(Record.id))).scalar_one()
    await conn.execute(insert(TaskRecord).values(url_task_id=task.id, record_id=record_id))
    return task, capture_id


# The events a finished task leaves.


async def test_a_finished_task_records_its_fetch_extraction_and_abstentions_before_the_jobs_end(
    conn: AsyncConnection,
) -> None:
    job_id = await _job(conn)
    task, capture_id = await _page(conn, job_id)

    await complete_task(conn, task, "partial", capture_id=capture_id)

    assert await _events(conn, job_id) == [
        ("task_fetched", {"url": URL, "method": "browser", "block_class": "ok"}),
        ("task_extracted", {"url": URL, "outcome": "partial", "mode": "config", "llm_calls": 2}),
        ("task_abstained", {"url": URL, "fields": ["brand", "price"]}),
        ("completed", {}),
    ]


async def test_a_task_whose_record_was_unchanged_records_the_abstentions_of_the_record_it_stands_for(
    conn: AsyncConnection,
) -> None:
    job_id = await _job(conn)
    task, capture_id = await _page(conn, job_id, stored=False)

    await complete_task(conn, task, "partial", capture_id=capture_id)

    events = [event for event in await _events(conn, job_id) if event[1].get("url") == URL]
    assert events[1:] == [
        ("task_extracted", {"url": URL, "outcome": "partial", "mode": "config", "llm_calls": 2}),
        ("task_abstained", {"url": URL, "fields": ["brand", "price"]}),
    ]


async def test_a_task_that_fails_for_good_records_why_before_the_jobs_end(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _task(conn, job_id)
    [task] = await claim_tasks(conn, "w1", 1)

    await fail_task(conn, task, "no handler", transient=False)

    failed = {"task_id": str(task.id), "url": URL, "attempts": 1, "last_error": "no handler"}
    assert await _events(conn, job_id) == [("task_failed", failed), ("failed", {})]


async def test_a_failed_task_records_what_it_did_before_its_failure(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    task, capture_id = await _page(conn, job_id)

    await fail_task(conn, task, "internal_error", transient=False, capture_id=capture_id)

    kinds = [kind for kind, _ in await _events(conn, job_id)]
    assert kinds == ["task_fetched", "task_extracted", "task_abstained", "task_failed", "failed"]


async def test_a_task_failure_that_is_retried_records_no_event(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _task(conn, job_id)
    [task] = await claim_tasks(conn, "w1", 1)

    await fail_task(conn, task, "timeout", transient=True)

    assert await _events(conn, job_id) == []


async def test_a_task_that_ends_blocked_records_no_failure(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    await _task(conn, job_id)
    [task] = await claim_tasks(conn, "w1", 1)

    await complete_task(conn, task, "blocked", reason="robots")

    assert await _events(conn, job_id) == [("completed", {})]


async def test_a_cancelled_task_records_no_task_event(conn: AsyncConnection) -> None:
    job_id = await _job(conn, cancel_requested=True)
    task, _ = await _page(conn, job_id)

    await cancel_task(conn, task)

    assert await _events(conn, job_id) == [("cancelled", {})]


async def test_a_retried_task_reports_its_last_extraction(conn: AsyncConnection) -> None:
    job_id = await _job(conn)
    task, _ = await _page(conn, job_id)
    later = insert(Extraction).values(url_task_id=task.id, engine_version="e", mode="adhoc", llm_calls=0)
    await conn.execute(later)

    await complete_task(conn, task, "extracted")

    [extracted] = [payload for kind, payload in await _events(conn, job_id) if kind == "task_extracted"]
    assert extracted == {"url": URL, "outcome": "extracted", "mode": "adhoc", "llm_calls": 0}


# The webhook a job's end owes.


async def test_a_job_owes_a_pending_webhook_when_it_ends_only_if_it_has_a_webhook_url(conn: AsyncConnection) -> None:
    hooked = await _job(conn, webhook_url="https://hooks.example.test/done")
    plain = await _job(conn)

    for job_id in (hooked, plain):
        await transition_job(conn, job_id, "failed")

    rows = await conn.execute(
        select(WebhookDelivery.job_id, WebhookDelivery.status, WebhookDelivery.attempts).where(
            WebhookDelivery.job_id.in_([hooked, plain])
        )
    )
    assert rows.all() == [(hooked, "pending", 0)]


async def test_cancelling_a_queued_job_with_a_webhook_url_owes_its_webhook(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        job_id = await _job(conn, status="queued", webhook_url="https://hooks.example.test/done")

    async with engine.begin() as conn:
        await jobs.cancel_job(conn, job_id)

    async with engine.connect() as conn:
        status = select(WebhookDelivery.status).where(WebhookDelivery.job_id == job_id)
        assert (await conn.execute(status)).scalar_one() == "pending"


# The stream.


async def _stored(engine: AsyncEngine, kinds: list[str], *, status: JobStatus = "running") -> tuple[JobId, list[str]]:
    """A job with one done task and one event of each of `kinds`, in order; the ids of the events."""
    async with engine.begin() as conn:
        job_id = await _job(conn, status=status)
        await conn.execute(
            insert(UrlTask).values(job_id=job_id, url=URL, canonical_url=URL, status="done", outcome="extracted")
        )
    for kind in kinds:
        # One transaction each, as workers write them.
        async with engine.begin() as conn:
            await record_event(conn, job_id, kind, {"n": len(kind)})
    async with engine.connect() as conn:
        rows = await conn.execute(select(JobEvent.id).where(JobEvent.job_id == job_id).order_by(JobEvent.id))
        return job_id, [str(event_id) for event_id in rows.scalars()]


def _id(text: str) -> JobEventId:
    return JobEventId(uuid.UUID(text))


async def _drain(stream: AsyncIterator[StreamEvent]) -> list[tuple[str | None, str, dict[str, Any]]]:
    async with asyncio.timeout(10):
        return [(None if e.id is None else str(e.id), e.kind, e.data) for e in [event async for event in stream]]


PROGRESS = {
    "counts": {"queued": 0, "claimed": 0, "done": 1, "failed": 0, "cancelled": 0},
    "outcomes": {
        "extracted": 1,
        "partial": 0,
        "unchanged": 0,
        "links_only": 0,
        "blocked": 0,
        "shell": 0,
        "not_found": 0,
        "no_match": 0,
        "failed": 0,
    },
}


async def test_a_stream_resumed_after_the_end_closes_at_once(engine: AsyncEngine) -> None:
    job_id, ids = await _stored(engine, ["task_fetched", "completed"], status="completed")

    assert await _drain(events.stream(engine, job_id, _id(ids[-1]), poll_s=0.01)) == []


async def test_the_stream_waits_for_events_written_after_it_started(engine: AsyncEngine) -> None:
    job_id, _ = await _stored(engine, [])
    received: list[str] = []

    async def follow() -> None:
        async for event in events.stream(engine, job_id, None, poll_s=0.01):
            received.append(event.kind)

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.1)
    async with engine.begin() as conn:
        await record_event(conn, job_id, "task_fetched")
    async with engine.begin() as conn:
        await transition_job(conn, job_id, "completed")
    async with asyncio.timeout(10):
        await follower

    assert received[0] == "task_fetched"
    assert received[-1] == "completed"


async def test_a_stream_cancelled_mid_poll_leaves_the_pool_usable(engine: AsyncEngine, database_url: str) -> None:
    # A client that drops the stream cancels it wherever it is, often inside a poll's query. The server cancels it
    # through an anyio cancel scope, which cancels every await under it until it exits, the connection's cleanup's
    # too. One pooled connection makes every request after it reuse the connection the stream held.
    job_id, _ = await _stored(engine, [])
    pooled = create_async_engine(database_url, pool_size=1, max_overflow=0)
    statuses = []
    try:
        for round_ in range(30):
            with anyio.move_on_after(0.002 * round_):
                await _drain(events.stream(pooled, job_id, None, poll_s=0))
            async with pooled.connect() as conn:
                statuses.append((await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one())
    finally:
        await pooled.dispose()

    assert statuses == ["running"] * 30


# Over HTTP.


@pytest.fixture
async def client(
    engine: AsyncEngine, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with engine.begin() as conn:
        key = await create_key(conn, "events-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        yield client
    keys = create_async_engine(database_url)
    async with keys.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys.dispose()


def _sse(body: str) -> list[dict[str, Any]]:
    """The events of an SSE body (WHATWG HTML §9.2.6): blocks separated by a blank line, of `field: value` lines; a
    comment line starts with `:`. `data` is parsed as the JSON it carries."""
    blocks = [[line for line in block.splitlines() if not line.startswith(":")] for block in body.split("\n\n")]
    events = [dict(line.split(": ", 1) for line in lines) for lines in blocks if lines]
    return [event | {"data": json.loads(event["data"])} for event in events]


async def test_events_are_served_as_server_sent_events(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    job_id, ids = await _stored(engine, ["task_fetched", "completed"], status="completed")

    response = await client.get(f"/v1/jobs/{job_id}/events")

    assert response.headers["content-type"].startswith("text/event-stream")
    assert _sse(response.text) == [
        {"event": "task_fetched", "data": {"n": 12}, "id": ids[0]},
        {"event": "progress", "data": PROGRESS},
        {"event": "completed", "data": {"n": 9}, "id": ids[1]},
    ]


async def test_last_event_id_resumes_the_stream(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    job_id, ids = await _stored(engine, ["task_fetched", "task_extracted", "completed"], status="completed")

    response = await client.get(f"/v1/jobs/{job_id}/events", headers={"Last-Event-ID": ids[1]})

    assert [(event["event"], event.get("id")) for event in _sse(response.text)] == [
        ("progress", None),
        ("completed", ids[2]),
    ]


async def test_the_events_of_an_unknown_job_are_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/v1/jobs/018f0000-0000-7000-8000-000000000000/events")

    assert (response.status_code, response.headers["content-type"]) == (404, "application/problem+json")
    assert response.json()["type"] == "not_found"


async def test_a_last_event_id_that_is_not_an_event_id_is_422(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    job_id, _ = await _stored(engine, ["completed"], status="completed")

    response = await client.get(f"/v1/jobs/{job_id}/events", headers={"Last-Event-ID": "seven"})

    assert response.status_code == 422
    problem = response.json()
    assert (problem["type"], [error["field"] for error in problem["errors"]]) == (
        "validation",
        ["header.last-event-id"],
    )


async def test_an_idle_stream_sends_heartbeats_until_the_job_ends(
    client: httpx.AsyncClient, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FastAPI's keep-alive interval is 15 s, the heartbeat §4.2 asks for; shortened so the test need not wait.
    monkeypatch.setattr("fastapi.routing._PING_INTERVAL", 0.05)
    job_id, _ = await _stored(engine, [])

    async def end_later() -> None:
        await asyncio.sleep(0.5)
        async with engine.begin() as conn:
            await transition_job(conn, job_id, "completed")

    ending = asyncio.create_task(end_later())
    async with asyncio.timeout(10):
        response = await client.get(f"/v1/jobs/{job_id}/events")
    await ending

    assert ": ping" in response.text.split("\n\n")
    assert [event["event"] for event in _sse(response.text)] == ["progress", "completed"]
