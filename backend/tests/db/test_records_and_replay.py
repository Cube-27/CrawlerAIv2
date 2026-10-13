"""Stored records and capture replay (SPEC-07 §4.6, ARCHITECTURE §13.1, INV-22, INV-27): the records and captures
services, then `GET /v1/records` and `POST /v1/captures/{id}/replay` over HTTP.

Records are made the way a page task makes them (`extract_task`) from synthetic JSON-LD pages on an RFC 2606 host,
and committed, since the replay and the app read them through their own connections.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import AttemptRecord, FetchResult
from crawlerai.api.app import create_app
from crawlerai.api.keys import create_key
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    ApiKey,
    Candidate,
    Capture,
    CaptureId,
    Extraction,
    Job,
    JobId,
    Project,
    Record,
    RecordId,
    Site,
    SiteId,
    SourceKind,
    UrlTask,
)
from crawlerai.db.models import (
    SchemaDef as SchemaRow,
)
from crawlerai.db.queue import insert_claimed
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.task import extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.services import captures, records
from crawlerai.services.captures import CaptureNotFound, NotReplayable
from crawlerai.services.records import RecordFilter
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders={t: ORDER for t in PRECEDENCE_TYPES}, calibration=None)
ATTRIBUTES = {
    "value",
    "status",
    "reason",
    "evidence",
    "confidence",
    "calibrated",
    "source_kind",
    "locator",
    "derived_by",
}


def _document(name: str) -> SchemaDocument:
    return SchemaDocument(
        name=name,
        version=1,
        page_kind="detail",
        fields={
            "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
            "price": FieldSpec(
                type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"
            ),
        },
    )


def _page(name: str, *, price: bool = True) -> bytes:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if price:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'.encode()


@dataclass
class Made:
    job_id: JobId
    capture_id: CaptureId
    record_id: RecordId | None


@dataclass
class World:
    """One site, one schema and an object store, with the pages scraped into it; `close` deletes what it made."""

    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId = field(init=False)
    schema: SchemaDef = field(init=False)
    jobs: list[JobId] = field(default_factory=list)

    async def open(self) -> None:
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            host = self.origin.removeprefix("https://")
            self.site_id = (
                await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))
            ).scalar_one()
            self.schema = await registry.create(conn, _document(f"stored_{uuid7().hex[-12:]}"), "user")

    async def scrape(self, path: str, body: bytes, *, extract: bool = True) -> Made:
        """A page fetched and stored as a capture; with `extract`, a `scrape` job's record made from it."""
        url = f"{self.origin}{path}"
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job_id: JobId = (
                await conn.execute(
                    insert(Job)
                    .values(project_id=project, kind="scrape", request={}, schema_id=self.schema.id, engine_version="e")
                    .returning(Job.id)
                )
            ).scalar_one()
            self.jobs.append(job_id)
            fetched = _fetched(url, body)
            capture_id = await store_capture(conn, self.store, fetched, self.site_id)
            if not extract:
                return Made(job_id, capture_id, None)
            task = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
            stored = await extract_task(
                conn,
                task,
                capture_id=capture_id,
                site_id=self.site_id,
                bundle=fetched.bundle,
                schema=self.schema,
                data=DATA,
                role_c=None,
                mode="adhoc",
                caller_supplied=True,
            )
        return Made(job_id, capture_id, stored.record_id)

    async def close(self) -> None:
        tasks = select(UrlTask.id).where(UrlTask.job_id.in_(self.jobs))
        extractions = select(Extraction.id).where(Extraction.url_task_id.in_(tasks))
        async with self.engine.begin() as conn:
            await conn.execute(delete(Record).where(Record.job_id.in_(self.jobs)))
            await conn.execute(delete(Candidate).where(Candidate.extraction_id.in_(extractions)))
            await conn.execute(delete(Extraction).where(Extraction.id.in_(extractions)))
            await conn.execute(delete(UrlTask).where(UrlTask.job_id.in_(self.jobs)))
            await conn.execute(delete(Job).where(Job.id.in_(self.jobs)))
            await conn.execute(delete(SchemaRow).where(SchemaRow.id == self.schema.id))


def _fetched(url: str, body: bytes) -> FetchResult:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=url,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(body),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    attempt = AttemptRecord(method="http", status=200, block_class="ok", duration_ms=1)
    return FetchResult(
        bundle=CaptureBundle(manifest=manifest, body=body, network=()), duration_ms=1, attempts=(attempt,)
    )


@pytest.fixture
async def world(engine: AsyncEngine, own_origin: str, tmp_path: Path) -> AsyncIterator[World]:
    made = World(engine, FsStore(tmp_path / "objects"), own_origin)
    await made.open()
    yield made
    await made.close()


async def _list(engine: AsyncEngine, **query: Any) -> records.RecordPage:
    async with engine.connect() as conn:
        return await records.list_records(conn, RecordFilter(**query))


# The records service.


async def test_a_stored_record_carries_every_field_with_its_meta_and_where_it_came_from(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))

    page = await _list(world.engine, job_id=made.job_id)

    [record] = page.items
    assert (record.id, record.capture_id, record.schema_id, record.version) == (
        made.record_id,
        made.capture_id,
        world.schema.id,
        1,
    )
    assert (record.mode, record.complete, page.next_cursor) == ("adhoc", True, None)
    assert {name: set(f.model_dump()) for name, f in record.fields.items()} == {
        "title": ATTRIBUTES,
        "price": ATTRIBUTES,
    }
    assert {name: (f.status, f.value) for name, f in record.fields.items()} == {
        "title": ("published", "Blue kettle"),
        "price": ("published", {"amount": "19.90", "currency": "EUR"}),
    }
    # Without a calibration no field is calibrated, so the record has no confidence (§10).
    assert record.confidence is None


async def test_a_field_that_did_not_publish_is_listed_without_a_value(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle", price=False))

    [record] = (await _list(world.engine, job_id=made.job_id)).items

    assert record.complete is False
    assert (record.fields["price"].status, record.fields["price"].value) == ("missing", None)


async def test_pages_are_newest_first_and_the_cursor_walks_them_without_overlap(world: World) -> None:
    made = [await world.scrape(f"/p/{n}", _page(f"Kettle {n}")) for n in range(3)]

    first = await _list(world.engine, schema_id=world.schema.id, limit=2)
    assert first.next_cursor is not None
    second = await _list(world.engine, schema_id=world.schema.id, limit=2, cursor=first.next_cursor)

    assert [r.id for r in first.items + second.items] == [m.record_id for m in reversed(made)]
    assert second.next_cursor is None


async def test_filters_narrow_by_job_site_and_schema(world: World) -> None:
    one = await world.scrape("/p/1", _page("Kettle 1"))
    two = await world.scrape("/p/2", _page("Kettle 2"))
    host = world.origin.removeprefix("https://")

    by_job = await _list(world.engine, job_id=one.job_id)
    by_site = await _list(world.engine, site=host)
    by_both = await _list(world.engine, site=host, job_id=two.job_id)
    elsewhere = await _list(world.engine, site="other.example.test", schema_id=world.schema.id)

    assert [r.id for r in by_job.items] == [one.record_id]
    assert [r.id for r in by_site.items] == [two.record_id, one.record_id]
    assert [r.id for r in by_both.items] == [two.record_id]
    assert elsewhere.items == []


async def test_a_record_whose_capture_expired_is_listed_without_one(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    async with world.engine.begin() as conn:
        await conn.execute(delete(Capture).where(Capture.id == made.capture_id))

    [record] = (await _list(world.engine, job_id=made.job_id)).items

    assert (record.id, record.capture_id) == (made.record_id, None)


# The captures service.


async def test_a_replay_with_the_same_engine_remakes_the_stored_record_and_stores_nothing(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle", price=False))
    [stored] = (await _list(world.engine, job_id=made.job_id)).items
    count = select(func.count()).select_from(Record).where(Record.site_id == world.site_id)
    async with world.engine.connect() as conn:
        before = (await conn.execute(count)).scalar_one()

    [replayed] = await captures.replay(world.engine, world.store, DATA, made.capture_id)

    assert replayed.model_dump() == stored.model_dump(include={"mode", "complete", "confidence", "fields"})
    async with world.engine.connect() as conn:
        assert (await conn.execute(count)).scalar_one() == before


async def test_a_replay_extracts_the_capture_again_rather_than_reading_the_stored_record(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    # As if an older engine had stored the record: its price did not publish.
    older: dict[str, Any] = {"status": "missing", "reason": "no_candidates", "evidence": None, "confidence": None}
    older |= {"calibrated": False, "source_kind": None, "locator": None, "derived_by": None}
    async with world.engine.begin() as conn:
        meta: dict[str, Any] = (
            await conn.execute(select(Record.field_meta).where(Record.id == made.record_id))
        ).scalar_one()
        await conn.execute(
            update(Record).where(Record.id == made.record_id).values(field_meta={**meta, "price": older})
        )

    [replayed] = await captures.replay(world.engine, world.store, DATA, made.capture_id)

    assert (replayed.fields["price"].status, replayed.fields["price"].value) == (
        "published",
        {"amount": "19.90", "currency": "EUR"},
    )


async def test_replaying_an_unknown_capture_is_not_found(world: World) -> None:
    unknown = CaptureId(uuid7())
    with pytest.raises(CaptureNotFound):
        await captures.replay(world.engine, world.store, DATA, unknown)


async def test_replaying_a_capture_whose_bundle_is_gone_is_not_found(world: World, tmp_path: Path) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    empty_store = FsStore(tmp_path / "elsewhere")
    with pytest.raises(CaptureNotFound, match="no longer stored"):
        await captures.replay(world.engine, empty_store, DATA, made.capture_id)


async def test_a_capture_no_record_was_made_from_is_not_replayable(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"), extract=False)
    with pytest.raises(NotReplayable):
        await captures.replay(world.engine, world.store, DATA, made.capture_id)


async def test_a_capture_whose_records_follow_a_listing_schema_is_not_replayable_yet(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    listing = SchemaDocument.model_validate(
        {**_document(f"listed_{uuid7().hex[-12:]}").model_dump(), "page_kind": "listing"}
    )
    async with world.engine.begin() as conn:
        schema = await registry.create(conn, listing, "user")
        await conn.execute(update(Record).where(Record.id == made.record_id).values(schema_id=schema.id))
    try:
        with pytest.raises(NotReplayable, match="listing"):
            await captures.replay(world.engine, world.store, DATA, made.capture_id)
    finally:
        async with world.engine.begin() as conn:
            await conn.execute(update(Record).where(Record.id == made.record_id).values(schema_id=world.schema.id))
            await conn.execute(delete(SchemaRow).where(SchemaRow.id == schema.id))


# Over HTTP.


@pytest.fixture
def engine_data() -> EngineData | None:
    """The engine data the app replays with; a test parametrizes it to None for an app without its data files."""
    return DATA


@pytest.fixture
async def client(
    world: World, database_url: str, engine_data: EngineData | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, reading captures from the world's object store, with no LLM provider key."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.delenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", raising=False)
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with world.engine.begin() as conn:
        key = await create_key(conn, "records-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        app.state.engine_data = engine_data
        yield client
    keys = create_async_engine(database_url)
    async with keys.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys.dispose()


async def test_records_are_listed_in_the_field_shape_with_a_cursor(client: httpx.AsyncClient, world: World) -> None:
    made = [await world.scrape(f"/p/{n}", _page(f"Kettle {n}")) for n in range(2)]

    first = await client.get("/v1/records", params={"schema_id": str(world.schema.id), "limit": 1})
    assert first.status_code == 200, first.text
    second = await client.get(
        "/v1/records", params={"schema_id": str(world.schema.id), "limit": 1, "cursor": first.json()["next_cursor"]}
    )

    [newest] = first.json()["items"]
    assert set(newest) == {"id", "capture_id", "schema_id", "version", "mode", "complete", "confidence", "fields"}
    assert (newest["id"], newest["capture_id"]) == (str(made[1].record_id), str(made[1].capture_id))
    assert newest["fields"]["price"]["value"] == {"amount": "19.90", "currency": "EUR"}
    assert set(newest["fields"]["title"]) == ATTRIBUTES
    assert [r["id"] for r in second.json()["items"]] == [str(made[0].record_id)]
    assert second.json()["next_cursor"] is None


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 201}, {"cursor": "not-an-id"}, {"page": 2}])
async def test_a_query_outside_the_filters_is_a_validation_problem(
    client: httpx.AsyncClient, query: dict[str, Any]
) -> None:
    response = await client.get("/v1/records", params=query)

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "validation"


async def test_records_and_replay_need_a_key(client: httpx.AsyncClient, world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    del client.headers["authorization"]

    listed = await client.get("/v1/records")
    replayed = await client.post(f"/v1/captures/{made.capture_id}/replay", json={})

    assert (listed.status_code, replayed.status_code) == (401, 401)


async def test_a_replay_answers_the_records_without_ids(client: httpx.AsyncClient, world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))

    response = await client.post(f"/v1/captures/{made.capture_id}/replay", json={})

    assert response.status_code == 200, response.text
    [record] = response.json()["records"]
    assert set(record) == {"mode", "complete", "confidence", "fields"}
    assert record["fields"]["title"]["value"] == "Blue kettle"


async def test_replay_problems(client: httpx.AsyncClient, world: World) -> None:
    unextracted = await world.scrape("/p/1", _page("Blue kettle"), extract=False)

    unknown = await client.post(f"/v1/captures/{uuid7()}/replay", json={})
    no_schema = await client.post(f"/v1/captures/{unextracted.capture_id}/replay", json={})

    assert (unknown.status_code, unknown.json()["type"]) == (404, "not_found")
    assert (no_schema.status_code, no_schema.json()["type"]) == (409, "conflict")


@pytest.mark.parametrize("engine_data", [None])
async def test_without_the_engine_data_a_replay_is_unavailable(client: httpx.AsyncClient, world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))

    response = await client.post(f"/v1/captures/{made.capture_id}/replay", json={})

    assert (response.status_code, response.json()["type"]) == (503, "records_unavailable")
