"""Jobs (SPEC-10 §4.2): a job's summary, its cancel and its results, including the clean `json_values` items (SPEC-14
§4.4), through the jobs service and then over HTTP (`GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}`,
`GET /v1/jobs/{id}/results`).

Jobs, tasks and records are written directly, as the queue and the page tasks would leave them, and committed,
since the app reads them through its own connections. Hosts are RFC 2606 names.
"""

import csv
import io
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.api.app import create_app
from crawlerai.core.ids import uuid7
from crawlerai.db.jobs import start_jobs
from crawlerai.db.keys import create_key
from crawlerai.db.models import (
    ApiKey,
    Capture,
    CaptureId,
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
    UrlTaskId,
)
from crawlerai.db.queue import complete_task, insert_claimed
from crawlerai.recurring.record_fp import document_digest
from crawlerai.recurring.versions import link_records
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.jobs import (
    ExportPage,
    JobListQuery,
    JobPage,
    JsonValuesPage,
    PageOutputPage,
    ResultsQuery,
)
from crawlerai.services.records import RecordPage
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

OUTCOMES = {"extracted", "partial", "unchanged", "links_only", "blocked", "shell", "not_found", "no_match", "failed"}


def _document(name: str) -> SchemaDocument:
    text = FieldSpec(type=FieldType.TEXT, description="d")
    return SchemaDocument(
        name=name,
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

    async def tasks(
        self, job_id: JobId, rows: Sequence[tuple[TaskStatus, TaskOutcome | None]], *, last_error: str | None = None
    ) -> None:
        async with self.engine.begin() as conn:
            for status, outcome in rows:
                url = f"{self.origin}/p/{uuid7().hex}"
                values = {"job_id": job_id, "url": url, "canonical_url": url, "status": status, "outcome": outcome}
                await conn.execute(insert(UrlTask).values(**values, last_error=last_error))

    async def record(self, job_id: JobId, data: Mapping[str, Any], field_meta: Mapping[str, Any]) -> RecordId:
        """A record of the world's schema, stored as a page task stores it."""
        async with self.engine.begin() as conn:
            task_id, url = await self._task(conn, job_id, "extracted", None)
            [record_id] = await self._store(conn, job_id, task_id, [(url, data, field_meta)])
        return record_id

    async def page(
        self,
        job_id: JobId,
        outcome: TaskOutcome,
        rows: Sequence[Mapping[str, Any]] = (),
        *,
        capture_id: CaptureId | None = None,
    ) -> tuple[UrlTaskId, str]:
        """A finished task whose page stored one record per entry of `rows` (a listing's rows), each publishing the
        fields it names, from the capture `capture_id` if given; its id and URL."""
        async with self.engine.begin() as conn:
            task_id, url = await self._task(conn, job_id, outcome, capture_id)
            records = [
                (f"{url}#{i}", data, {n: meta(_status(n, data)) for n in self.schema.fields})
                for i, data in enumerate(rows)
            ]
            await self._store(conn, job_id, task_id, records)
        return task_id, url

    async def _task(
        self, conn: AsyncConnection, job_id: JobId, outcome: TaskOutcome, capture_id: CaptureId | None
    ) -> tuple[UrlTaskId, str]:
        url = f"{self.origin}/p/{uuid7().hex}"
        status = "failed" if outcome == "failed" else "done"
        values = {"job_id": job_id, "url": url, "canonical_url": url, "status": status, "outcome": outcome}
        task = await conn.execute(insert(UrlTask).values(**values, capture_id=capture_id).returning(UrlTask.id))
        return task.scalar_one(), url

    async def _store(
        self,
        conn: AsyncConnection,
        job_id: JobId,
        task_id: UrlTaskId,
        records: Sequence[tuple[str, Mapping[str, Any], Mapping[str, Any]]],
    ) -> list[RecordId]:
        """Store `records` (entity key, data, field meta) as the task's page's, in order, and link them to it."""
        if not records:
            return []
        extraction = await conn.execute(
            insert(Extraction).values(url_task_id=task_id, engine_version="e", mode="adhoc").returning(Extraction.id)
        )
        extraction_id = extraction.scalar_one()
        made: list[RecordId] = []
        for entity_key, data, field_meta in records:
            values = {
                "extraction_id": extraction_id,
                "job_id": job_id,
                "site_id": self.site_id,
                "schema_id": self.schema.id,
                "schema_digest": document_digest(self.schema),
                "entity_key": entity_key,
                "data": dict(data),
                "field_meta": dict(field_meta),
                "complete": "title" in data,
                "mode": "adhoc",
            }
            made.append((await conn.execute(insert(Record).values(**values).returning(Record.id))).scalar_one())
        await link_records(conn, task_id, made)
        return made

    async def records(self, job_id: JobId, n: int) -> list[RecordId]:
        """`n` records, oldest first, the even ones without a colour."""
        made = []
        for i in range(n):
            data = {"title": f"Kettle {i}"} | ({"colour": "blue"} if i % 2 else {})
            field_meta = {"title": meta("published"), "colour": meta("published" if i % 2 else "missing")}
            made.append(await self.record(job_id, data, field_meta))
        return made


def _status(name: str, data: Mapping[str, Any]) -> str:
    return "published" if name in data else "missing"


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


async def _results(
    engine: AsyncEngine, job_id: JobId, **query: Any
) -> RecordPage | ExportPage | PageOutputPage | JsonValuesPage:
    async with engine.connect() as conn:
        # These jobs have no captures: the store is never read.
        return await jobs.job_results(conn, job_id, ResultsQuery(**query), store=FsStore(Path("unused")))


async def _task_statuses(conn: AsyncConnection, job_id: JobId) -> list[str]:
    return sorted((await conn.execute(select(UrlTask.status).where(UrlTask.job_id == job_id))).scalars())


# The summary.


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


# The list.


async def test_each_listed_job_has_the_counts_of_its_own_tasks(world: World) -> None:
    busy = await world.job(status="running", usage={"llm_calls": 2})
    await world.tasks(busy, [("queued", None), ("done", "extracted"), ("done", "links_only"), ("failed", "failed")])
    idle = await world.job()

    page = await _list(world.engine)

    assert [(job.id, job.counts.model_dump(), job.usage) for job in page.items] == [
        (idle, {"queued": 0, "claimed": 0, "done": 0, "failed": 0, "cancelled": 0}, {}),
        (busy, {"queued": 1, "claimed": 0, "done": 2, "failed": 1, "cancelled": 0}, {"llm_calls": 2}),
    ]
    assert (page.items[1].outcomes.extracted, page.items[1].outcomes.links_only) == (1, 1)


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


# Cancel.


async def test_a_running_job_is_cancelled_once_its_claimed_task_finishes(world: World) -> None:
    job_id = await world.job()
    await world.tasks(job_id, [("queued", None)])
    async with world.engine.begin() as conn:
        url = f"{world.origin}/p/claimed"
        running = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
        await start_jobs(conn, [job_id])

    during = await _cancel(world.engine, job_id)
    async with world.engine.begin() as conn:
        await complete_task(conn, running, "extracted")
    after = await _summary(world.engine, job_id)

    # The queued task never runs; the claimed one finishes, and then the job ends.
    assert (during.status, during.counts.queued, during.counts.cancelled, during.counts.claimed) == ("running", 0, 1, 1)
    assert during.cancel_requested is True
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

    assert (second, second.status) == (first, "cancelled")
    async with world.engine.connect() as conn:
        events = (await conn.execute(select(JobEvent.kind).where(JobEvent.job_id == job_id))).scalars().all()
    assert events == ["cancelled"]


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


async def _json_values(engine: AsyncEngine, job_id: JobId, **query: Any) -> JsonValuesPage:
    page = await _results(engine, job_id, format="json_values", **query)
    assert isinstance(page, JsonValuesPage)
    return page


async def test_json_values_has_one_item_per_task_oldest_first_with_its_clean_records(world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    _, detail = await world.page(job_id, "partial", [{"colour": "blue"}])
    _, failed = await world.page(job_id, "failed")
    _, listing = await world.page(job_id, "extracted", [{"title": "Kettle", "colour": "red"}, {"title": "Mug"}])
    _, blocked = await world.page(job_id, "blocked")
    await world.tasks(job_id, [("queued", None)])
    other = await world.job(schema_id=world.schema.id, status="completed")
    await world.page(other, "extracted", [{"title": "Lamp"}])

    page = await _json_values(world.engine, job_id)

    # A clean record has the schema's fields in name order, null where none published, and no status.
    assert [(item.url, item.outcome, item.records) for item in page.items[:4]] == [
        (detail, "partial", [{"colour": "blue", "title": None}]),
        (failed, "failed", []),
        (listing, "extracted", [{"colour": "red", "title": "Kettle"}, {"colour": None, "title": "Mug"}]),
        (blocked, "blocked", []),
    ]
    assert [list(record) for record in page.items[2].records] == [["colour", "title"]] * 2
    assert (len(page.items), page.items[4].outcome, page.items[4].records) == (5, None, [])
    assert (page.format, page.next_cursor) == ("json_values", None)


async def test_an_unchanged_page_shows_the_latest_record_of_its_entity(world: World) -> None:
    first = await world.job(schema_id=world.schema.id, status="completed")
    [stored] = await world.records(first, 1)
    rerun = await world.job(schema_id=world.schema.id, status="completed")
    unchanged, url = await world.page(rerun, "unchanged")
    async with world.engine.begin() as conn:
        await link_records(conn, unchanged, [stored])

    page = await _json_values(world.engine, rerun)

    assert [(item.url, item.outcome, item.records) for item in page.items] == [
        (url, "unchanged", [{"title": "Kettle 0", "colour": None}])
    ]


async def test_a_task_read_before_it_ends_has_no_records(world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="running")
    [stored] = await world.records(job_id, 1)
    url = f"{world.origin}/p/claimed"
    async with world.engine.begin() as conn:
        values = {"job_id": job_id, "url": url, "canonical_url": url, "status": "claimed", "outcome": None}
        running = (await conn.execute(insert(UrlTask).values(**values).returning(UrlTask.id))).scalar_one()
        await link_records(conn, running, [stored])

    page = await _json_values(world.engine, job_id)

    assert (page.items[-1].url, page.items[-1].outcome, page.items[-1].records) == (url, None, [])


async def test_json_values_of_a_job_without_a_schema_lists_its_tasks_with_no_records(world: World) -> None:
    job_id = await world.job(status="completed")
    await world.tasks(job_id, [("done", "extracted"), ("failed", "failed")])

    page = await _json_values(world.engine, job_id)

    assert [(item.outcome, item.records) for item in page.items] == [("extracted", []), ("failed", [])]


async def test_json_values_pages_with_the_task_id_as_cursor(world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    made = [await world.page(job_id, "extracted", [{"title": f"Kettle {i}"}]) for i in range(3)]

    first = await _json_values(world.engine, job_id, limit=2)
    second = await _json_values(world.engine, job_id, limit=2, cursor=first.next_cursor)

    assert first.next_cursor == made[1][0]
    assert [item.url for item in first.items + second.items] == [url for _, url in made]
    assert second.next_cursor is None


# Over HTTP.


@pytest.fixture
async def client(
    world: World, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
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
    job_id = await world.job(status="running", request={"urls": ["https://shop.test/a"], "formats": ["markdown"]})
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
        "llm_cost_usd",
        "webhook_url",
        "engine_version",
        "cancel_requested",
        "start_url",
        "url_count",
    }
    assert (body["id"], body["status"], body["counts"]["queued"], body["outcomes"]["partial"]) == (
        str(job_id),
        "running",
        1,
        1,
    )
    assert (body["start_url"], body["url_count"]) == (None, 1)


async def test_a_jobs_stored_request_is_served_and_its_start_url_summarized(
    client: httpx.AsyncClient, world: World
) -> None:
    stored = {"url": "https://shop.test/", "formats": ["markdown"], "limit": 500}
    job_id = await world.job(kind="crawl", request=stored)

    request = await client.get(f"/v1/jobs/{job_id}/request")
    summary = await client.get(f"/v1/jobs/{job_id}")
    missing = await client.get(f"/v1/jobs/{uuid7()}/request")

    assert (request.status_code, request.json()) == (200, stored)
    assert (summary.json()["start_url"], summary.json()["url_count"]) == ("https://shop.test/", None)
    assert missing.status_code == 404


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


async def test_delete_cancels_a_queued_job_and_its_tasks_at_once(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job()
    await world.tasks(job_id, [("queued", None), ("queued", None)])

    response = await client.delete(f"/v1/jobs/{job_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["status"], body["cancel_requested"]) == ("cancelled", True)
    assert body["counts"] == {"queued": 0, "claimed": 0, "done": 0, "failed": 0, "cancelled": 2}
    async with world.engine.connect() as conn:
        events = (await conn.execute(select(JobEvent.kind).where(JobEvent.job_id == job_id))).scalars().all()
    assert events == ["cancelled"]


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


async def test_a_csv_safe_export_quotes_formula_cells_and_the_default_keeps_them(
    client: httpx.AsyncClient, world: World
) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    await world.record(job_id, {"title": "=SUM(1)"}, {"title": meta("published"), "colour": meta("missing")})

    plain = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "csv_records"})
    safe = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "csv_records", "csv_safe": "true"})

    header = "colour,title,_status_colour,_status_title\r\n"
    assert plain.json()["content"] == header + ",=SUM(1),missing,published\r\n"
    assert safe.json()["content"] == header + ",'=SUM(1),missing,published\r\n"


async def test_csv_safe_is_refused_without_csv_records(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")

    responses = [
        await client.get(f"/v1/jobs/{job_id}/results", params={"csv_safe": "true"}),
        await client.get(f"/v1/jobs/{job_id}/results", params={"format": "markdown", "csv_safe": "true"}),
    ]

    assert [(r.status_code, r.json()["type"]) for r in responses] == [(422, "validation")] * 2


async def test_page_outputs_are_served_with_each_tasks_last_error(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(status="completed")
    await world.tasks(job_id, [("failed", "failed")], last_error="budget_exhausted")
    await world.tasks(job_id, [("done", "blocked")], last_error="robots")
    await world.tasks(job_id, [("done", "not_found")])

    response = await client.get(f"/v1/jobs/{job_id}/results")

    assert response.status_code == 200, response.text
    assert [(item["status"], item["outcome"], item["last_error"]) for item in response.json()["items"]] == [
        ("failed", "failed", "budget_exhausted"),
        ("done", "blocked", "robots"),
        ("done", "not_found", None),
    ]


async def test_json_values_carry_metadata_only_when_asked_and_the_capture_is_kept(
    client: httpx.AsyncClient, world: World, tmp_path: Path, fetch_result: Callable[..., FetchResult]
) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")
    store = FsStore(tmp_path / "objects")
    body = b"<html lang='en'><head><title>Kettle</title></head><body><h1>Kettle</h1></body></html>"
    async with world.engine.begin() as conn:
        captures = [
            await store_capture(conn, store, fetch_result(f"{world.origin}/c/{i}", body=body), world.site_id)
            for i in range(4)
        ]
        expired = (await conn.execute(select(Capture.object_key).where(Capture.id == captures[3]))).scalar_one()
    store.delete(expired)
    await world.page(job_id, "extracted", [{"title": "Kettle"}], capture_id=captures[0])
    await world.page(job_id, "partial", [{"colour": "blue"}], capture_id=captures[1])
    await world.page(job_id, "not_found", capture_id=captures[2])
    await world.page(job_id, "extracted", [{"title": "Mug"}], capture_id=captures[3])
    await world.page(job_id, "failed")

    plain = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "json_values"})
    asked = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "json_values", "include": "metadata"})

    assert plain.status_code == 200, plain.text
    assert [set(item) for item in plain.json()["items"]] == [{"url", "outcome", "records"}] * 5
    assert asked.status_code == 200, asked.text
    items = asked.json()["items"]
    # Only an extracted or partial page whose capture is still kept has metadata; it is never null.
    assert ["metadata" in item for item in items] == [True, True, False, False, False]
    assert (items[0]["metadata"]["title"], items[0]["metadata"]["language"]) == ("Kettle", "en")
    assert (items[0]["records"], asked.json()["format"]) == ([{"title": "Kettle", "colour": None}], "json_values")


async def test_json_values_are_served_for_a_job_without_a_schema(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(status="completed")
    await world.tasks(job_id, [("done", "extracted")])

    response = await client.get(f"/v1/jobs/{job_id}/results", params={"format": "json_values", "limit": 1})

    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    assert (item["outcome"], item["records"], response.json()["next_cursor"]) == ("extracted", [], None)


async def test_include_is_refused_without_json_values(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job(schema_id=world.schema.id, status="completed")

    responses = [
        await client.get(f"/v1/jobs/{job_id}/results", params={"include": "metadata"}),
        await client.get(f"/v1/jobs/{job_id}/results", params={"format": "csv_records", "include": "metadata"}),
        await client.get(f"/v1/jobs/{job_id}/results", params={"format": "json_values", "include": "markdown"}),
    ]

    assert [(r.status_code, r.json()["type"]) for r in responses] == [(422, "validation")] * 3


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
