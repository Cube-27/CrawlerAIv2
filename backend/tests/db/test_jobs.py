"""Jobs (SPEC-10 §4.2): a job's summary, its cancel and its results, through the jobs service and then over HTTP
(`GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results`).

Jobs, tasks and records are written directly, as the queue and the page tasks would leave them, and committed,
since the app reads them through its own connections. Hosts are RFC 2606 names.
"""

import csv
import io
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.core.ids import uuid7
from crawlerai.db.jobs import start_jobs
from crawlerai.db.models import (
    ApiKey,
    Extraction,
    Job,
    JobEvent,
    JobId,
    Project,
    Record,
    RecordId,
    SchemaId,
    Site,
    SiteId,
    TaskOutcome,
    TaskStatus,
    UrlTask,
)
from crawlerai.db.queue import complete_task, insert_claimed
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.jobs import (
    ExportPage,
    JobEnded,
    JobListQuery,
    JobNotFound,
    JobPage,
    NotExportable,
    PageOutputPage,
    ResultsQuery,
)
from crawlerai.services.keys import create_key
from crawlerai.services.records import RecordPage
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

OUTCOMES = {"extracted", "partial", "unchanged", "links_only", "blocked", "shell", "not_found", "no_match", "failed"}


def _document(name: str) -> SchemaDocument:
    text = FieldSpec(type=FieldType.TEXT, description="d")
    return SchemaDocument(
        name=name,
        version=1,
        page_kind="detail",
        fields={"title": text.model_copy(update={"required": True}), "colour": text},
    )


def meta(status: str) -> dict[str, Any]:
    """A `field_meta` entry; only a published field has a source (INV-22)."""
    published = status == "published"
    return {
        "status": status,
        "reason": None if published else "no candidate",
        "evidence": "structured" if published else None,
        "confidence": None,
        "calibrated": False,
        "source_kind": "jsonld" if published else None,
        "locator": "jsonld:0:$.name" if published else None,
        "derived_by": None,
    }


@dataclass
class World:
    """One site and one schema; the `engine`, `own_origin` and `schema_name` fixtures delete what it made."""

    engine: AsyncEngine
    origin: str
    site_id: SiteId
    schema: SchemaDef

    async def job(self, *, schema_id: SchemaId | None = None, status: str = "queued", **columns: Any) -> JobId:
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            values = {"kind": "batch_scrape", "request": {}, "engine_version": "e", "status": status} | columns
            statement = insert(Job).values(project_id=project, schema_id=schema_id, **values).returning(Job.id)
            job_id: JobId = (await conn.execute(statement)).scalar_one()
        return job_id

    async def tasks(self, job_id: JobId, rows: Sequence[tuple[TaskStatus, TaskOutcome | None]]) -> None:
        async with self.engine.begin() as conn:
            for status, outcome in rows:
                url = f"{self.origin}/p/{uuid7().hex}"
                values = {"job_id": job_id, "url": url, "canonical_url": url, "status": status, "outcome": outcome}
                await conn.execute(insert(UrlTask).values(**values))

    async def record(self, job_id: JobId, data: Mapping[str, Any], field_meta: Mapping[str, Any]) -> RecordId:
        """A record of the world's schema, stored as a page task stores it."""
        async with self.engine.begin() as conn:
            url = f"{self.origin}/p/{uuid7().hex}"
            task = await conn.execute(
                insert(UrlTask)
                .values(job_id=job_id, url=url, canonical_url=url, status="done", outcome="extracted")
                .returning(UrlTask.id)
            )
            extraction = await conn.execute(
                insert(Extraction)
                .values(url_task_id=task.scalar_one(), engine_version="e", mode="adhoc")
                .returning(Extraction.id)
            )
            values = {
                "extraction_id": extraction.scalar_one(),
                "job_id": job_id,
                "site_id": self.site_id,
                "schema_id": self.schema.id,
                "schema_version": self.schema.version,
                "entity_key": url,
                "data": dict(data),
                "field_meta": dict(field_meta),
                "complete": "title" in data,
                "mode": "adhoc",
            }
            record_id: RecordId = (
                await conn.execute(insert(Record).values(**values).returning(Record.id))
            ).scalar_one()
        return record_id

    async def records(self, job_id: JobId, n: int) -> list[RecordId]:
        """`n` records, oldest first, the even ones without a colour."""
        made = []
        for i in range(n):
            data = {"title": f"Kettle {i}"} | ({"colour": "blue"} if i % 2 else {})
            field_meta = {"title": meta("published"), "colour": meta("published" if i % 2 else "missing")}
            made.append(await self.record(job_id, data, field_meta))
        return made


@pytest.fixture
async def world(engine: AsyncEngine, own_origin: str, schema_name: str) -> World:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(site.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    return World(engine, own_origin, site_id, schema)


async def _summary(engine: AsyncEngine, job_id: JobId) -> jobs.JobSummary:
    async with engine.connect() as conn:
        return await jobs.get_job(conn, job_id)


async def _list(engine: AsyncEngine, **query: Any) -> JobPage:
    async with engine.connect() as conn:
        return await jobs.list_jobs(conn, JobListQuery(**query))


async def _cancel(engine: AsyncEngine, job_id: JobId) -> jobs.JobSummary:
    async with engine.begin() as conn:
        return await jobs.cancel_job(conn, job_id)


async def _results(engine: AsyncEngine, job_id: JobId, **query: Any) -> RecordPage | ExportPage | PageOutputPage:
    async with engine.connect() as conn:
        # These jobs have no captures: the store is never read.
        return await jobs.job_results(conn, job_id, ResultsQuery(**query), store=FsStore(Path("unused")))


async def _task_statuses(conn: AsyncConnection, job_id: JobId) -> list[str]:
    return sorted((await conn.execute(select(UrlTask.status).where(UrlTask.job_id == job_id))).scalars())


# The summary.


async def test_a_new_job_is_queued_with_every_count_at_zero(world: World) -> None:
    job_id = await world.job(webhook_url="https://hooks.example.test/done")

    summary = await _summary(world.engine, job_id)

    assert (summary.id, summary.kind, summary.status) == (job_id, "batch_scrape", "queued")
    assert (summary.started_at, summary.finished_at) == (None, None)
    assert summary.counts.model_dump() == {"queued": 0, "claimed": 0, "done": 0, "failed": 0, "cancelled": 0}
    assert summary.outcomes.model_dump() == dict.fromkeys(OUTCOMES, 0)
    assert (summary.usage, summary.webhook_url, summary.engine_version) == ({}, "https://hooks.example.test/done", "e")


async def test_the_summary_counts_tasks_by_status_and_by_outcome(world: World) -> None:
    job_id = await world.job(status="running", usage={"llm_calls": 3})
    await world.tasks(
        job_id,
        [
            ("queued", None),
            ("queued", None),
            ("claimed", None),
            ("done", "extracted"),
            ("done", "extracted"),
            ("done", "links_only"),
            ("done", "blocked"),
            ("failed", "failed"),
            ("cancelled", None),
        ],
    )

    summary = await _summary(world.engine, job_id)

    assert summary.counts.model_dump() == {"queued": 2, "claimed": 1, "done": 4, "failed": 1, "cancelled": 1}
    expected = dict.fromkeys(OUTCOMES, 0) | {"extracted": 2, "links_only": 1, "blocked": 1, "failed": 1}
    assert summary.outcomes.model_dump() == expected
    assert summary.usage == {"llm_calls": 3}


async def test_an_unknown_job_is_not_found(world: World) -> None:
    unknown = JobId(uuid7())

    with pytest.raises(JobNotFound):
        await _summary(world.engine, unknown)
    with pytest.raises(JobNotFound):
        await _cancel(world.engine, unknown)
    with pytest.raises(JobNotFound):
        await _results(world.engine, unknown)


# The list.


async def test_the_list_pages_through_every_job_newest_first(world: World) -> None:
    made = [await world.job() for _ in range(3)]

    first = await _list(world.engine, limit=2)
    second = await _list(world.engine, limit=2, cursor=first.next_cursor)

    assert [job.id for job in first.items + second.items] == made[::-1]
    assert first.next_cursor == made[1]
    assert second.next_cursor is None


async def test_each_listed_job_has_the_summary_of_its_own(world: World) -> None:
    busy = await world.job(status="running", usage={"llm_calls": 2})
    await world.tasks(busy, [("queued", None), ("done", "extracted"), ("done", "links_only"), ("failed", "failed")])
    idle = await world.job()

    page = await _list(world.engine)

    assert page.items == [await _summary(world.engine, idle), await _summary(world.engine, busy)]
    assert page.items[1].counts.model_dump() == {"queued": 1, "claimed": 0, "done": 2, "failed": 1, "cancelled": 0}


async def test_the_list_keeps_the_jobs_of_the_kind_and_status_asked_for(world: World) -> None:
    crawl_done = await world.job(kind="crawl", status="completed")
    crawl_queued = await world.job(kind="crawl")
    batch_done = await world.job(status="completed")

    crawls = await _list(world.engine, kind="crawl")
    completed = await _list(world.engine, status="completed")
    both = await _list(world.engine, kind="crawl", status="completed")
    none = await _list(world.engine, kind="map")

    assert [job.id for job in crawls.items] == [crawl_queued, crawl_done]
    assert [job.id for job in completed.items] == [batch_done, crawl_done]
    assert [job.id for job in both.items] == [crawl_done]
    assert none == JobPage(items=[], next_cursor=None)


async def test_a_filtered_list_pages_within_its_filter(world: World) -> None:
    older = await world.job(kind="crawl")
    await world.job()
    newer = await world.job(kind="crawl")

    first = await _list(world.engine, kind="crawl", limit=1)
    second = await _list(world.engine, kind="crawl", limit=1, cursor=first.next_cursor)

    assert ([job.id for job in first.items], first.next_cursor) == ([newer], newer)
    assert ([job.id for job in second.items], second.next_cursor) == ([older], None)


# Cancel.


async def test_cancelling_a_queued_job_cancels_it_and_its_tasks_at_once(world: World) -> None:
    job_id = await world.job()
    await world.tasks(job_id, [("queued", None), ("queued", None)])

    summary = await _cancel(world.engine, job_id)

    assert summary.status == "cancelled"
    assert summary.finished_at is not None
    assert summary.counts.cancelled == 2
    async with world.engine.connect() as conn:
        events = (await conn.execute(select(JobEvent.kind).where(JobEvent.job_id == job_id))).scalars().all()
    assert events == ["cancelled"]


async def test_a_running_job_is_cancelled_once_its_claimed_task_finishes(world: World) -> None:
    job_id = await world.job()
    await world.tasks(job_id, [("queued", None)])
    async with world.engine.begin() as conn:
        url = f"{world.origin}/p/running"
        running = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
        await start_jobs(conn, [job_id])

    during = await _cancel(world.engine, job_id)
    async with world.engine.begin() as conn:
        await complete_task(conn, running, "extracted")
    after = await _summary(world.engine, job_id)

    # The queued task never runs; the claimed one finishes, and then the job ends.
    assert (during.status, during.counts.queued, during.counts.cancelled, during.counts.claimed) == ("running", 0, 1, 1)
    assert (after.status, after.counts.done, after.outcomes.extracted) == ("cancelled", 1, 1)


async def test_a_running_job_with_no_claimed_task_is_cancelled_at_once(world: World) -> None:
    job_id = await world.job(status="running")
    await world.tasks(job_id, [("done", "extracted"), ("queued", None)])

    summary = await _cancel(world.engine, job_id)

    assert summary.status == "cancelled"
    assert summary.counts.model_dump() == {"queued": 0, "claimed": 0, "done": 1, "failed": 0, "cancelled": 1}


async def test_cancelling_a_cancelled_job_again_changes_nothing(world: World) -> None:
    job_id = await world.job()
    first = await _cancel(world.engine, job_id)

    second = await _cancel(world.engine, job_id)

    assert second == first


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_a_job_that_ended_cannot_be_cancelled(world: World, status: str) -> None:
    job_id = await world.job(status=status)
    await world.tasks(job_id, [("done", "extracted")])

    with pytest.raises(JobEnded):
        await _cancel(world.engine, job_id)
    assert (await _summary(world.engine, job_id)).status == status


# Results.


async def test_results_page_through_the_jobs_records_newest_first(world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    other = await world.job(schema_id=world.schema.id, status="completed")
    made = await world.records(job_id, 3)
    await world.records(other, 1)

    first = await _results(world.engine, job_id, limit=2)
    assert isinstance(first, RecordPage)
    second = await _results(world.engine, job_id, limit=2, cursor=first.next_cursor)
    assert isinstance(second, RecordPage)

    assert [r.id for r in first.items + second.items] == made[::-1]
    assert second.next_cursor is None
    newest = first.items[0]
    assert (newest.fields["title"].value, newest.fields["colour"].value) == ("Kettle 2", None)
    assert newest.fields["colour"].status == "missing"


async def test_results_export_the_records_in_the_schemas_columns(world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    await world.records(job_id, 2)

    page = await _results(world.engine, job_id, format="csv_records", limit=1)
    rest = await _results(world.engine, job_id, format="json_records", cursor=getattr(page, "next_cursor", None))
    markdown = await _results(world.engine, job_id, format="markdown")

    assert isinstance(page, ExportPage)
    assert isinstance(rest, ExportPage)
    assert isinstance(markdown, ExportPage)
    assert list(csv.reader(io.StringIO(page.content))) == [
        ["colour", "title", "_status_colour", "_status_title"],
        ["blue", "Kettle 1", "published", "published"],
    ]
    assert json.loads(rest.content) == [
        {"colour": None, "title": "Kettle 0", "_status_colour": "missing", "_status_title": "published"}
    ]
    assert rest.next_cursor is None
    assert markdown.content.count("\n") == 4  # header, delimiter, two records


async def test_a_job_without_a_schema_has_no_records_to_export(world: World) -> None:
    job_id = await world.job(status="completed")

    json_page = await _results(world.engine, job_id)

    assert json_page == PageOutputPage(items=[], next_cursor=None)
    with pytest.raises(NotExportable):
        await _results(world.engine, job_id, format="csv_records")


# Over HTTP.


@pytest.fixture
async def client(
    world: World, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.delenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", raising=False)
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with world.engine.begin() as conn:
        key = await create_key(conn, "jobs-api-test")
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


async def test_a_jobs_summary_is_served_with_its_counts(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(status="running")
    await world.tasks(job_id, [("done", "partial"), ("queued", None)])

    response = await client.get(f"/v1/jobs/{job_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "kind",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "counts",
        "outcomes",
        "usage",
        "webhook_url",
        "engine_version",
    }
    assert (body["id"], body["status"], body["counts"]["queued"], body["outcomes"]["partial"]) == (
        str(job_id),
        "running",
        1,
        1,
    )


async def test_the_jobs_are_listed_a_page_at_a_time(client: httpx.AsyncClient, world: World) -> None:
    older = await world.job(kind="crawl", status="completed")
    newer = await world.job(kind="crawl", status="completed")
    await world.job()

    first = await client.get("/v1/jobs", params={"kind": "crawl", "status": "completed", "limit": 1})
    cursor = first.json()["next_cursor"]
    second = await client.get("/v1/jobs", params={"kind": "crawl", "status": "completed", "cursor": cursor})

    assert first.status_code == 200, first.text
    assert [job["id"] for job in first.json()["items"]] == [str(newer)]
    assert cursor == str(newer)
    assert second.json() == {"items": [(await client.get(f"/v1/jobs/{older}")).json()], "next_cursor": None}


async def test_delete_cancels_the_job(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job()

    response = await client.delete(f"/v1/jobs/{job_id}")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"


async def test_job_problems(client: httpx.AsyncClient, world: World) -> None:
    unknown = uuid7()
    ended = await world.job(status="completed")

    responses = {
        "get unknown": await client.get(f"/v1/jobs/{unknown}"),
        "cancel unknown": await client.delete(f"/v1/jobs/{unknown}"),
        "results unknown": await client.get(f"/v1/jobs/{unknown}/results"),
        "cancel ended": await client.delete(f"/v1/jobs/{ended}"),
        "export without schema": await client.get(f"/v1/jobs/{ended}/results", params={"format": "csv_records"}),
        "unknown format": await client.get(f"/v1/jobs/{ended}/results", params={"format": "xml"}),
        "bad id": await client.get("/v1/jobs/not-an-id"),
        "list unknown kind": await client.get("/v1/jobs", params={"kind": "search"}),
        "list unknown status": await client.get("/v1/jobs", params={"status": "paused"}),
        "list bad cursor": await client.get("/v1/jobs", params={"cursor": "not-an-id"}),
        "list over the page limit": await client.get("/v1/jobs", params={"limit": 201}),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == {
        "get unknown": (404, "not_found"),
        "cancel unknown": (404, "not_found"),
        "results unknown": (404, "not_found"),
        "cancel ended": (409, "conflict"),
        "export without schema": (409, "conflict"),
        "unknown format": (422, "validation"),
        "bad id": (422, "validation"),
        "list unknown kind": (422, "validation"),
        "list unknown status": (422, "validation"),
        "list bad cursor": (422, "validation"),
        "list over the page limit": (422, "validation"),
    }


async def test_results_are_served_as_records_or_as_an_export(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    [made] = await world.records(job_id, 1)

    records = await client.get(f"/v1/jobs/{job_id}/results")
    exported = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "csv_records"})

    assert records.status_code == 200, records.text
    assert [r["id"] for r in records.json()["items"]] == [str(made)]
    assert records.json()["items"][0]["fields"]["title"]["value"] == "Kettle 0"
    assert exported.json() == {
        "format": "csv_records",
        "content": "colour,title,_status_colour,_status_title\r\n,Kettle 0,missing,published\r\n",
        "next_cursor": None,
    }


async def test_jobs_need_a_key(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job()
    del client.headers["authorization"]

    responses = [
        await client.get("/v1/jobs"),
        await client.get(f"/v1/jobs/{job_id}"),
        await client.delete(f"/v1/jobs/{job_id}"),
        await client.get(f"/v1/jobs/{job_id}/results"),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401, 401]
    assert (await _summary(world.engine, job_id)).status == "queued"
