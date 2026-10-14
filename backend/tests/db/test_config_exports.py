"""`POST /v1/configs/{id}/export` (SPEC-08 §4.10 to §4.12, ARCHITECTURE §12.2, §12.3, INV-20): a stored config exported
as `json` or `platform_draft`, with the release check run on the captures it was validated on, against the records
the engine stored from them.

Pages are scraped the way a page task stores them (`extract_task`) from synthetic JSON-LD pages on an RFC 2606 host,
and committed, since the app reads them through its own connections.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, insert, select
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
    ExtractionConfigId,
    Job,
    Project,
    Site,
    SiteId,
)
from crawlerai.db.queue import insert_claimed
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.task import extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.services.keys import create_key
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

# The engine publishes `title` from JSON-LD; the config reads it from the `<h1>`, which says the same on every page but
# the one built with `heading`.
TITLE_STEP = {"xpath": "normalize-space(//h1)"}


def _html(name: str, heading: str | None = None) -> bytes:
    node = {"@context": "https://schema.org", "@type": "Product", "name": name}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    return f"<html><head>{script}</head><body><h1> {heading or name} </h1></body></html>".encode()


@dataclass
class World:
    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId
    schema: SchemaDef
    data: EngineData
    fetch_result: Callable[..., FetchResult]

    async def scrape(self, path: str, body: bytes) -> CaptureId:
        """A page fetched, stored as a capture, and extracted into a `scrape` job's record."""
        url = f"{self.origin}{path}"
        fetched = self.fetch_result(url, 200, body, (("Content-Type", "text/html"),))
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job = insert(Job).values(project_id=project, kind="scrape", request={}, schema_id=self.schema.id)
            job_id = (await conn.execute(job.values(engine_version="e").returning(Job.id))).scalar_one()
            capture_id = await store_capture(conn, self.store, fetched, self.site_id)
            task = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
            await extract_task(
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
        return capture_id

    async def config(self, validated_on: list[CaptureId], **fields: dict[str, Any]) -> ExtractionConfigId:
        ir = {
            "ir_version": "1",
            "site": self.origin.removeprefix("https://"),
            "schema": {"name": self.schema.name, "version": self.schema.version},
            "page_kind": "detail",
            "fetch": {"method": "http"},
            "fields": {name: {"steps": [step], "status": "uncorroborated"} for name, step in fields.items()},
            "provenance": {
                "origin": "induced",
                "validated_on": [str(capture) for capture in validated_on],
                "learned_at": "2026-10-04T00:00:00Z",
                "engine_version": "test",
            },
        }
        row = {
            "site_id": self.site_id,
            "schema_id": self.schema.id,
            "schema_version": self.schema.version,
            "page_kind": "detail",
            "version": 1,
            "status": "active",
            "ir": ir,
            "origin": "induced",
        }
        async with self.engine.begin() as conn:
            config_id: ExtractionConfigId = (
                await conn.execute(insert(ExtractionConfig).values(**row).returning(ExtractionConfig.id))
            ).scalar_one()
        return config_id


@pytest.fixture
async def world(
    engine: AsyncEngine,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    tmp_path: Path,
) -> AsyncIterator[World]:
    document = SchemaDocument(
        name=schema_name,
        version=1,
        page_kind="detail",
        fields={"title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")},
    )
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(site.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, document, "user")
    yield World(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)
    async with engine.begin() as conn:
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


@pytest.fixture
async def client(
    world: World, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, reading captures from the world's object store."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with world.engine.begin() as conn:
        key = await create_key(conn, "config-export-test")
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


async def _export(client: httpx.AsyncClient, config_id: ExtractionConfigId, fmt: str) -> dict[str, Any]:
    response = await client.post(f"/v1/configs/{config_id}/export", json={"format": fmt})
    assert response.status_code == 200, response.text
    exported: dict[str, Any] = response.json()
    return exported


async def test_a_config_is_exported_as_its_ir_with_the_release_check_on_its_held_out_pages(
    client: httpx.AsyncClient, world: World
) -> None:
    captures = [await world.scrape(f"/p/{n}", _html(f"Kettle {n}")) for n in range(3)]
    config_id = await world.config(captures, title=TITLE_STEP)

    exported = await _export(client, config_id, "json")

    assert exported["format"] == "json"
    assert exported["export"]["fields"]["title"]["steps"] == [{"xpath": "normalize-space(//h1)", "post": []}]
    assert exported["release"] == {
        "held_out": [str(capture) for capture in captures],
        "fields": {"title": {"published": 3, "reproduced": 3, "manual": False}},
        "listing": None,
    }


async def test_a_field_not_reproduced_on_a_held_out_page_is_manual_in_the_platform_draft(
    client: httpx.AsyncClient, world: World
) -> None:
    captures = [await world.scrape(f"/p/{n}", _html(f"Kettle {n}")) for n in range(2)]
    captures.append(await world.scrape("/p/2", _html("Kettle 2", heading="Kettle 2 (sale)")))
    config_id = await world.config(captures, title=TITLE_STEP)

    exported = await _export(client, config_id, "platform_draft")

    assert exported["export"]["draft"] is True
    assert exported["export"]["fields"]["title"] == {
        "steps": [{"xpath": "normalize-space(//h1)", "post": []}],
        "manual": True,
    }
    assert exported["release"]["fields"]["title"] == {"published": 3, "reproduced": 2, "manual": True}


async def test_a_capture_whose_bundle_expired_is_left_out(client: httpx.AsyncClient, world: World) -> None:
    captures = [await world.scrape(f"/p/{n}", _html(f"Kettle {n}")) for n in range(3)]
    config_id = await world.config(captures, title=TITLE_STEP)
    async with world.engine.connect() as conn:
        key = (await conn.execute(select(Capture.object_key).where(Capture.id == captures[0]))).scalar_one()
    world.store.delete(key)

    exported = await _export(client, config_id, "json")

    assert exported["release"]["held_out"] == [str(capture) for capture in captures[1:]]
    assert exported["release"]["fields"]["title"] == {"published": 2, "reproduced": 2, "manual": False}


async def test_export_problems(client: httpx.AsyncClient, world: World) -> None:
    unknown = await client.post(f"/v1/configs/{uuid7()}/export", json={"format": "json"})
    bad_format = await client.post(f"/v1/configs/{uuid7()}/export", json={"format": "gmc"})
    del client.headers["authorization"]
    no_key = await client.post(f"/v1/configs/{uuid7()}/export", json={"format": "json"})

    assert (unknown.status_code, bad_format.status_code, no_key.status_code) == (404, 422, 401)
    assert unknown.headers["content-type"] == "application/problem+json"
