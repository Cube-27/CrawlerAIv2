"""Stored records and capture replay (SPEC-07 §4.6, ARCHITECTURE §13.1, INV-22, INV-27): the records and captures
services, then `GET /v1/records` and `POST /v1/captures/{id}/replay` over HTTP.

Records are made the way a page task makes them (`extract_task`) from synthetic JSON-LD pages on an RFC 2606 host,
and committed, since the replay and the app read them through their own connections.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.api.app import create_app
from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    ApiKey,
    Capture,
    CaptureId,
    ExtractionConfig,
    Job,
    JobId,
    Project,
    Record,
    RecordId,
    Site,
    SiteId,
)
from crawlerai.db.queue import insert_claimed
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.task import extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaChanges, SchemaDef, SchemaDocument
from crawlerai.services import captures, records
from crawlerai.services.captures import CaptureNotFound, NotReplayable
from crawlerai.services.keys import create_key
from crawlerai.services.records import RecordFilter
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

ATTRIBUTES = {"value", "status", "reason", "evidence", "confidence", "calibrated", "source_kind", "locator"}
ATTRIBUTES |= {"derived_by"}


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


def _product(name: str, *, price: bool = True, amount: str = "19.90") -> dict[str, Any]:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if price:
        node["offers"] = {"@type": "Offer", "price": amount, "priceCurrency": "EUR"}
    return node


def _html(node: dict[str, Any]) -> bytes:
    return f'<html><head><script type="application/ld+json">{json.dumps(node)}</script></head></html>'.encode()


def _page(name: str, *, price: bool = True, amount: str = "19.90") -> bytes:
    return _html(_product(name, price=price, amount=amount))


@dataclass
class Made:
    job_id: JobId
    capture_id: CaptureId
    record_id: RecordId | None


@dataclass
class World:
    """One site, one schema and an object store, with the pages scraped into it. The `engine`, `own_origin` and
    `schema_name` fixtures delete what it made."""

    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId
    schema: SchemaDef
    data: EngineData
    fetch_result: Callable[..., FetchResult]

    async def scrape(self, path: str, body: bytes, *, extract: bool = True) -> Made:
        """A page fetched and stored as a capture; with `extract`, a `scrape` job's record made from it."""
        url = f"{self.origin}{path}"
        fetched = self.fetch_result(url, 200, body, (("Content-Type", "text/html"),))
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job = insert(Job).values(project_id=project, kind="scrape", request={}, schema_id=self.schema.id)
            job_id: JobId = (await conn.execute(job.values(engine_version="e").returning(Job.id))).scalar_one()
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
                data=self.data,
                role_c=None,
                config=None,
                caller_supplied=True,
                write_records=store_records,
            )
        return Made(job_id, capture_id, stored.records[0].id if stored.records else None)


@pytest.fixture
async def world(
    engine: AsyncEngine,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    tmp_path: Path,
) -> World:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(site.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    store = FsStore(tmp_path / "objects")
    return World(engine, store, own_origin, site_id, schema, engine_data, fetch_result)


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
    by_site = await _list(world.engine, site=host.upper())
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


async def test_a_page_scraped_again_unchanged_answers_with_its_record_and_stores_no_other(world: World) -> None:
    first = await world.scrape("/p/1", _page("Blue kettle"))

    again = await world.scrape("/p/1", _page("Blue kettle"))

    assert again.record_id == first.record_id
    assert [r.id for r in (await _list(world.engine, schema_id=world.schema.id)).items] == [first.record_id]
    assert (await _list(world.engine, job_id=again.job_id)).items == []


async def test_a_changed_price_is_listed_as_version_2_naming_price(world: World) -> None:
    first = await world.scrape("/p/1", _page("Blue kettle"))

    changed = await world.scrape("/p/1", _page("Blue kettle", amount="17.50"))

    newest, oldest = (await _list(world.engine, schema_id=world.schema.id)).items
    assert (newest.id, newest.version, newest.changed_fields) == (changed.record_id, 2, ["price"])
    assert newest.fields["price"].value == {"amount": "17.50", "currency": "EUR"}
    assert (oldest.id, oldest.version, oldest.changed_fields) == (first.record_id, 1, [])


async def test_changed_since_lists_the_new_versions_and_new_entities_stored_from_then(world: World) -> None:
    await world.scrape("/p/1", _page("Kettle 1"))
    await world.scrape("/p/2", _page("Kettle 2"))
    async with world.engine.connect() as conn:
        since = (await conn.execute(select(func.now()))).scalar_one()
    changed = await world.scrape("/p/1", _page("Kettle 1", amount="17.50"))
    await world.scrape("/p/2", _page("Kettle 2"))
    new = await world.scrape("/p/3", _page("Kettle 3"))

    page = await _list(world.engine, schema_id=world.schema.id, changed_since=since)

    assert [(r.id, r.version, r.changed_fields) for r in page.items] == [
        (new.record_id, 1, []),
        (changed.record_id, 2, ["price"]),
    ]


# The captures service.


async def test_a_replay_with_the_same_engine_remakes_the_stored_record_and_stores_nothing(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle", price=False))
    [stored] = (await _list(world.engine, job_id=made.job_id)).items
    count = select(func.count()).select_from(Record).where(Record.site_id == world.site_id)
    async with world.engine.connect() as conn:
        before = (await conn.execute(count)).scalar_one()

    [replayed] = await captures.replay(world.engine, world.store, world.data, made.capture_id)

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

    [replayed] = await captures.replay(world.engine, world.store, world.data, made.capture_id)

    assert (replayed.fields["price"].status, replayed.fields["price"].value) == (
        "published",
        {"amount": "19.90", "currency": "EUR"},
    )


async def test_a_schema_version_with_an_active_config_replays_with_it(world: World) -> None:
    # SPEC-08 §4.8: the page is extracted as one fetched now would be, in `config` mode.
    made = await world.scrape("/p/1", _page("Blue kettle"))
    ir = {
        "ir_version": "1",
        "site": world.origin.removeprefix("https://"),
        "schema": {"name": world.schema.name, "version": 1},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"title": {"steps": [{"jsonld": "$['name']", "when_type": "Product"}], "status": "operator"}},
        "provenance": {
            "origin": "operator",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
    }
    config = insert(ExtractionConfig).values(
        site_id=world.site_id,
        schema_id=world.schema.id,
        schema_version=1,
        page_kind="detail",
        version=1,
        status="active",
        ir=ir,
        origin="operator",
    )
    async with world.engine.begin() as conn:
        config_id = (await conn.execute(config.returning(ExtractionConfig.id))).scalar_one()
    try:
        [replayed] = await captures.replay(world.engine, world.store, world.data, made.capture_id)
    finally:
        async with world.engine.begin() as conn:
            await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.id == config_id))

    title = replayed.fields["title"]
    assert (replayed.mode, title.value, title.source_kind) == ("config", "Blue kettle", "jsonld")


async def test_replaying_an_unknown_capture_is_not_found(world: World) -> None:
    unknown = CaptureId(uuid7())
    with pytest.raises(CaptureNotFound):
        await captures.replay(world.engine, world.store, world.data, unknown)


async def test_replaying_a_capture_whose_bundle_is_gone_is_not_found(world: World, tmp_path: Path) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))
    empty_store = FsStore(tmp_path / "elsewhere")
    with pytest.raises(CaptureNotFound, match="no longer stored"):
        await captures.replay(world.engine, empty_store, world.data, made.capture_id)


async def test_a_capture_no_record_was_made_from_is_not_replayable(world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"), extract=False)
    with pytest.raises(NotReplayable):
        await captures.replay(world.engine, world.store, world.data, made.capture_id)


async def test_a_listing_replays_one_record_per_row_as_the_page_task_stored_them(world: World) -> None:
    url = FieldSpec(type=FieldType.URL, description="d", required=True, schema_org="Product.url")
    listed = SchemaChanges(page_kind="listing", fields={**world.schema.fields, "url": url})
    async with world.engine.begin() as conn:
        world.schema = await registry.new_version(conn, world.schema.name, listed, "user")
    rows = [_product(f"Kettle {n}") | {"url": f"{world.origin}/p/{n}"} for n in (1, 2)]
    items = [{"@type": "ListItem", "position": n, "item": row} for n, row in enumerate(rows, start=1)]
    made = await world.scrape(
        "/kettles", _html({"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items})
    )
    stored = (await _list(world.engine, job_id=made.job_id)).items

    replayed = await captures.replay(world.engine, world.store, world.data, made.capture_id)

    content = {"mode", "complete", "confidence", "fields"}
    by_title = {str(record.fields["title"].value): record.model_dump() for record in replayed}
    assert sorted(by_title) == ["Kettle 1", "Kettle 2"]
    assert by_title == {str(record.fields["title"].value): record.model_dump(include=content) for record in stored}


# Over HTTP.


@pytest.fixture
def app_data(world: World) -> EngineData | None:
    """The engine data the app replays with; a test parametrizes it to None for an app without its data files."""
    return world.data


@pytest.fixture
async def client(
    world: World, database_url: str, app_data: EngineData | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        app.state.engine_data = app_data
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
    assert set(newest) == {
        "id",
        "capture_id",
        "schema_id",
        "version",
        "changed_fields",
        "mode",
        "complete",
        "confidence",
        "fields",
    }
    assert (newest["id"], newest["capture_id"]) == (str(made[1].record_id), str(made[1].capture_id))
    assert newest["fields"]["price"]["value"] == {"amount": "19.90", "currency": "EUR"}
    assert set(newest["fields"]["title"]) == ATTRIBUTES
    assert [r["id"] for r in second.json()["items"]] == [str(made[0].record_id)]
    assert second.json()["next_cursor"] is None


async def test_changed_since_narrows_the_listed_records(client: httpx.AsyncClient, world: World) -> None:
    await world.scrape("/p/1", _page("Kettle 1"))
    async with world.engine.connect() as conn:
        since = (await conn.execute(select(func.now()))).scalar_one()
    changed = await world.scrape("/p/1", _page("Kettle 1", amount="17.50"))

    query = {"schema_id": str(world.schema.id), "changed_since": since.isoformat()}
    response = await client.get("/v1/records", params=query)

    assert response.status_code == 200, response.text
    [record] = response.json()["items"]
    assert (record["id"], record["version"], record["changed_fields"]) == (str(changed.record_id), 2, ["price"])


@pytest.mark.parametrize(
    "query",
    [
        {"limit": 0},
        {"limit": 201},
        {"cursor": "not-an-id"},
        {"page": 2},
        {"changed_since": "yesterday"},
        # A time without its offset names no instant (RFC 3339 §4.4).
        {"changed_since": "2026-10-01T00:00:00"},
    ],
)
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


@pytest.mark.parametrize("app_data", [None])
async def test_without_the_engine_data_a_replay_is_unavailable(client: httpx.AsyncClient, world: World) -> None:
    made = await world.scrape("/p/1", _page("Blue kettle"))

    response = await client.post(f"/v1/captures/{made.capture_id}/replay", json={})

    assert (response.status_code, response.json()["type"]) == (503, "records_unavailable")
