"""Stored records and capture replay (rest-api spec, INV-22, INV-27): the records and captures
services, then `GET /v1/records` and `POST /v1/captures/{id}/replay` over HTTP."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.db.models import (
    CaptureId,
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
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.task import store_extraction
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.services import captures, records
from crawlerai.services.records import RecordFilter
from crawlerai.storage.fs import FsStore
from tests.db.support import api

pytestmark = pytest.mark.anyio

ATTRIBUTES = {"value", "status", "reason", "evidence", "confidence", "calibrated", "source_kind", "locator"}
ATTRIBUTES |= {"derived_by"}


def _document(name: str) -> SchemaDocument:
    return SchemaDocument(
        name=name,
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

    async def scrape(
        self,
        path: str,
        body: bytes,
        *,
        extract: bool = True,
        before_commit: Callable[[], Awaitable[None]] | None = None,
    ) -> Made:
        """A page fetched and stored as a capture; with `extract`, a `scrape` job's record made from it. `before_commit`
        runs once the record is stored, before its transaction commits."""
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
            result = await extract_page(fetched.bundle, self.schema, None, None, data=self.data)
            stored = await store_extraction(
                conn,
                task,
                result,
                capture_id=capture_id,
                site_id=self.site_id,
                schema=self.schema,
                caller_supplied=True,
                write_records=store_records,
            )
            if before_commit is not None:
                await before_commit()
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
        "price": ("published", {"amount": 19.9, "currency": "EUR"}),
    }
    # Without a calibration no field is calibrated, so the record has no confidence (§10).
    assert record.confidence is None


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


# Over HTTP.


@pytest.fixture
def app_data(world: World) -> EngineData | None:
    """The engine data the app replays with; a test parametrizes it to None for an app without its data files."""
    return world.data


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch, world: World, app_data: EngineData | None
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, reading captures from the world's object store, with no LLM provider key."""
    app_env.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    async with api(world.engine) as (app, client):
        app.state.engine_data = app_data
        yield client


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
        "egress_country",
        "egress_basis",
        "delta",
    }
    assert (newest["id"], newest["capture_id"]) == (str(made[1].record_id), str(made[1].capture_id))
    assert newest["fields"]["price"]["value"] == {"amount": 19.9, "currency": "EUR"}
    assert set(newest["fields"]["title"]) == ATTRIBUTES
    assert [r["id"] for r in second.json()["items"]] == [str(made[0].record_id)]
    assert second.json()["next_cursor"] is None
