"""Run events (jobs spec): the events a finished task leaves, the webhook a job's end owes, and the event stream
through the events service and over SSE (`GET /v1/jobs/{id}/events`), with `Last-Event-ID` resume."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

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
    JobId,
    JobStatus,
    Project,
    Record,
    Site,
    TaskRecord,
    UrlTask,
)
from crawlerai.db.queue import claim_tasks, complete_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDocument, document_digest

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
    the record; without, the record is unchanged: an earlier task's extraction stored it (jobs spec). Returns the
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


# The webhook events a job's end owes (`db.webhook_outbox`).


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
