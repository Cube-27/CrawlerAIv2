"""The config API: a site's configs and one config over HTTP; an operator's
correction becomes the next version, validated on the site's held-out pages, active when validation keeps it and a
`draft` with its report when not; forced learning starts a `learn` job. Also the held-out loader the correction
validates with."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.db.models import (
    CaptureId,
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    ProgressiveState,
    Project,
    Site,
    SiteId,
)
from crawlerai.db.queue import complete_task, insert_claimed
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument, document_digest
from crawlerai.services.page_store import store_extraction
from crawlerai.storage.fs import FsStore
from tests.db.support import api

pytestmark = pytest.mark.anyio

H1 = {"xpath": "normalize-space(//h1)", "post": []}
H2 = {"xpath": "normalize-space(//h2)", "post": []}


def _document(name: str) -> SchemaDocument:
    title = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
    about = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.description")
    return SchemaDocument(name=name, page_kind="detail", fields={"title": title, "about": about})


def _page(name: str) -> bytes:
    node = {"@context": "https://schema.org", "@type": "Product", "name": name, "description": f"About {name}"}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    body = f"<h1>{name}</h1><h2>Other</h2><p>About {name}</p>"
    return f"<html><head>{script}</head><body>{body}</body></html>".encode()


# The field sources a stored config states.
SOURCED: Final = {"needs": "http", "call": None}


def _ir(host: str, schema: SchemaDef, step: dict[str, Any], **more: dict[str, Any]) -> dict[str, Any]:
    steps = {"title": step, **more}
    return {
        "ir_version": "1",
        "site": host,
        "schema": {"name": schema.name, "digest": document_digest(schema)},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {
            name: {"steps": [field_step], "status": "uncorroborated", "yield": 1.0, "validity": 1.0, **SOURCED}
            for name, field_step in steps.items()
        },
        "listing": None,
        "api_recipe": None,
        "recipes": {},
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
        "absent": [],
    }


@dataclass
class World:
    """One site, one schema and an object store, with pages scraped into it. Its fixture, `engine`, `own_origin` and
    `schema_name` delete what it made."""

    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId
    schema: SchemaDef
    data: EngineData
    fetch_result: Callable[..., FetchResult]

    @property
    def host(self) -> str:
        return self.origin.removeprefix("https://")

    async def scrape(self, path: str, body: bytes, schema: SchemaDef | None = None) -> CaptureId:
        """A page fetched, stored as a capture, and extracted by a `scrape` job's task, which the worker then
        completes with the page's outcome."""
        schema = schema or self.schema
        url = f"{self.origin}{path}"
        fetched = self.fetch_result(url, 200, body, (("Content-Type", "text/html"),))
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job = insert(Job).values(project_id=project, kind="scrape", request={}, schema_id=schema.id)
            job_id: JobId = (await conn.execute(job.values(engine_version="e").returning(Job.id))).scalar_one()
            capture_id = await store_capture(conn, self.store, fetched, self.site_id)
            task = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
            result = await extract_page(fetched.bundle, schema, None, None, data=self.data)
            stored = await store_extraction(
                conn,
                task,
                result,
                capture_id=capture_id,
                site_id=self.site_id,
                schema=schema,
                caller_supplied=True,
            )
            outcome = stored.outcome
            assert outcome != "failed"
            await complete_task(conn, task, outcome, capture_id=capture_id)
        return capture_id

    async def store_only(self, path: str, body: bytes) -> CaptureId:
        """A page fetched and stored as a capture, never extracted."""
        fetched = self.fetch_result(f"{self.origin}{path}", 200, body, (("Content-Type", "text/html"),))
        async with self.engine.begin() as conn:
            return await store_capture(conn, self.store, fetched, self.site_id)

    async def active_config(self, step: dict[str, Any], **more: dict[str, Any]) -> ExtractionConfigId:
        """Version 1 of the site's config, active, with `step` for `title` (and `more` steps by field), and the state
        active on it."""
        key = {"site_id": self.site_id, "schema_id": self.schema.id, "page_kind": "detail"}
        async with self.engine.begin() as conn:
            config = insert(ExtractionConfig).values(
                **key,
                version=1,
                status="active",
                ir=_ir(self.host, self.schema, step, **more),
                origin="induced",
                field_status=dict.fromkeys(["title", *more], "uncorroborated"),
                validation_report=None,
            )
            config_id: ExtractionConfigId = (await conn.execute(config.returning(ExtractionConfig.id))).scalar_one()
            await conn.execute(insert(ProgressiveState).values(**key, mode="active", active_config_id=config_id))
        return config_id

    async def configs(self) -> list[tuple[int, str, str]]:
        async with self.engine.connect() as conn:
            rows = select(ExtractionConfig.version, ExtractionConfig.status, ExtractionConfig.origin).where(
                ExtractionConfig.site_id == self.site_id
            )
            return [
                (r.version, r.status, r.origin) for r in await conn.execute(rows.order_by(ExtractionConfig.version))
            ]

    async def state(self) -> Any:
        async with self.engine.connect() as conn:
            query = select(ProgressiveState).where(ProgressiveState.site_id == self.site_id)
            return (await conn.execute(query)).one()


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
    return World(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)


@pytest.fixture
def app_data(world: World) -> EngineData | None:
    """The engine data the app validates with; a test parametrizes it to None for an app without its data files."""
    return world.data


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch, world: World, app_data: EngineData | None
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, reading captures from the world's object store."""
    app_env.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    async with api(world.engine) as (app, client):
        app.state.engine_data = app_data
        yield client


async def _pages(world: World, count: int) -> list[CaptureId]:
    return [await world.scrape(f"/p/{n}", _page(f"Kettle {n}")) for n in range(count)]


# Reading configs.


async def test_a_sites_configs_are_listed_with_their_status_and_one_config_has_its_ir(
    client: httpx.AsyncClient, world: World
) -> None:
    config_id = await world.active_config(H2)

    listed = await client.get(f"/v1/sites/{world.host.upper()}/configs")
    one = await client.get(f"/v1/configs/{config_id}")

    assert listed.status_code == 200
    assert listed.json() == {
        "items": [
            {
                "id": str(config_id),
                "site": world.host,
                "schema_id": str(world.schema.id),
                "page_kind": "detail",
                "version": 1,
                "status": "active",
                "origin": "induced",
                "field_status": {"title": "uncorroborated"},
                "validation_report": None,
            }
        ]
    }
    assert one.status_code == 200
    assert one.json() == {**listed.json()["items"][0], "ir": _ir(world.host, world.schema, H2)}


async def test_the_config_api_needs_a_key(client: httpx.AsyncClient, world: World) -> None:
    config_id = await world.active_config(H2)
    client.headers.pop("authorization")

    responses = [
        await client.get(f"/v1/sites/{world.host}/configs"),
        await client.get(f"/v1/configs/{config_id}"),
        await client.put(f"/v1/configs/{config_id}", json={"confirm": ["title"]}),
        await client.post(f"/v1/sites/{world.host}/learn", json={"schema_id": str(world.schema.id)}),
        await client.post(f"/v1/configs/{config_id}/approve"),
        await client.post(f"/v1/configs/{config_id}/reject"),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401, 401, 401, 401]


# Approval.


async def test_approving_a_pending_config_makes_it_the_active_one(client: httpx.AsyncClient, world: World) -> None:
    first = await world.active_config(H2)
    key = {"site_id": world.site_id, "schema_id": world.schema.id, "page_kind": "detail"}
    async with world.engine.begin() as conn:
        pending = insert(ExtractionConfig).values(
            **key, version=2, status="pending_approval", ir=_ir(world.host, world.schema, H1), origin="induced"
        )
        second: ExtractionConfigId = (await conn.execute(pending.returning(ExtractionConfig.id))).scalar_one()

    approved = await client.post(f"/v1/configs/{second}/approve")
    again = await client.post(f"/v1/configs/{second}/approve")
    old = await client.post(f"/v1/configs/{first}/approve")

    assert (approved.status_code, approved.json()["status"]) == (200, "active")
    assert await world.configs() == [(1, "suspended", "induced"), (2, "active", "induced")]
    assert ((await world.state()).mode, (await world.state()).active_config_id) == ("active", second)
    assert [(r.status_code, r.json()["detail"]) for r in (again, old)] == [
        (409, f"config {second} is active, not the latest version waiting for approval"),
        (409, f"config {first} is suspended, not the latest version waiting for approval"),
    ]


# Corrections.


async def test_a_correction_that_validates_becomes_the_active_operator_version(
    client: httpx.AsyncClient, world: World
) -> None:
    held_out = await _pages(world, 3)
    first = await world.active_config(H2)

    response = await client.put(f"/v1/configs/{first}", json={"fields": {"title": {"steps": [H1]}}})

    assert response.status_code == 200
    body = response.json()
    assert (body["version"], body["status"], body["origin"]) == (2, "active", "operator")
    assert body["field_status"] == {"title": "operator"}
    assert body["ir"]["fields"]["title"] == {
        "steps": [H1],
        "status": "operator",
        "yield": 1.0,
        "validity": 1.0,
        **SOURCED,
    }
    assert body["ir"]["provenance"]["origin"] == "operator"
    assert set(body["ir"]["provenance"]["validated_on"]) == {str(c) for c in held_out}
    report = body["validation_report"]
    assert set(report["held_out"]) == {str(c) for c in held_out}
    # The published titles came from JSON-LD, which the config's values equal on every page.
    assert report["fields"]["title"] | {"status": "operator"} == {
        "pages": 3,
        "matched": 3,
        "valid": 3,
        "published": 3,
        "reproduced": 3,
        "comparable": 3,
        "corroborated_on": 3,
        "status": "operator",
        "yield": 1.0,
        "validity": 1.0,
        "dropped": None,
    }
    assert await world.configs() == [(1, "suspended", "induced"), (2, "active", "operator")]
    state = await world.state()
    assert (state.mode, str(state.active_config_id)) == ("active", body["id"])


# Learning.


async def _learn(client: httpx.AsyncClient, world: World, **body: Any) -> httpx.Response:
    return await client.post(f"/v1/sites/{world.host}/learn", json={"schema_id": str(world.schema.id), **body})


async def test_learn_is_refused_while_a_run_is_in_flight(client: httpx.AsyncClient, world: World) -> None:
    await _learn(client, world)

    again = await _learn(client, world, force=True)

    assert (again.status_code, again.json()["type"]) == (409, "conflict")


# The held-out loader.


# Refusal.
