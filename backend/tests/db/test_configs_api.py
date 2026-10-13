"""The config API (SPEC-08 §4.10, ARCHITECTURE §13.1, C5): a site's configs and one config over HTTP; an operator's
correction becomes the next version, validated on the site's held-out pages, active when validation keeps it and a
`draft` with its report when not; forced learning starts a `learn` job. Also the held-out loader the correction
validates with (§4.4, §4.7).

Pages are made the way a page task makes them (`extract_task`) from synthetic JSON-LD pages on an RFC 2606 host, and
committed, since the app reads them through its own connections.
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
from crawlerai.api.keys import create_key
from crawlerai.config_ir.held_out import load_held_out
from crawlerai.db.models import (
    ApiKey,
    Capture,
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
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.task import extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

H1 = {"xpath": "normalize-space(//h1)", "post": []}
H2 = {"xpath": "normalize-space(//h2)", "post": []}


def _document(name: str) -> SchemaDocument:
    title = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
    return SchemaDocument(name=name, version=1, page_kind="detail", fields={"title": title})


def _page(name: str) -> bytes:
    node = {"@context": "https://schema.org", "@type": "Product", "name": name}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    return f"<html><head>{script}</head><body><h1>{name}</h1><h2>Other</h2></body></html>".encode()


def _ir(host: str, schema: SchemaDef, step: dict[str, Any]) -> dict[str, Any]:
    return {
        "ir_version": "1",
        "site": host,
        "schema": {"name": schema.name, "version": schema.version},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"title": {"steps": [step], "status": "uncorroborated", "yield": 1.0, "validity": 1.0}},
        "listing": None,
        "api_recipe": None,
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
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
            stored = await extract_task(
                conn,
                task,
                capture_id=capture_id,
                site_id=self.site_id,
                bundle=fetched.bundle,
                schema=schema,
                data=self.data,
                role_c=None,
                mode="adhoc",
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

    async def active_config(self, step: dict[str, Any]) -> ExtractionConfigId:
        """Version 1 of the site's config, active, with `step` for `title`, and the state active on it."""
        key = {"site_id": self.site_id, "schema_id": self.schema.id, "schema_version": 1, "page_kind": "detail"}
        async with self.engine.begin() as conn:
            config = insert(ExtractionConfig).values(
                **key,
                version=1,
                status="active",
                ir=_ir(self.host, self.schema, step),
                origin="induced",
                field_status={"title": "uncorroborated"},
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
) -> AsyncIterator[World]:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(site.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    yield World(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)
    # The site's configs, which `own_origin` does not know of, go before it deletes the site.
    async with engine.begin() as conn:
        await conn.execute(delete(ProgressiveState).where(ProgressiveState.site_id == site_id))
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


@pytest.fixture
def app_data(world: World) -> EngineData | None:
    """The engine data the app validates with; a test parametrizes it to None for an app without its data files."""
    return world.data


@pytest.fixture
async def client(
    world: World, database_url: str, app_data: EngineData | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, reading captures from the world's object store."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.delenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", raising=False)
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with world.engine.begin() as conn:
        key = await create_key(conn, "configs-api-test")
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
                "schema_version": 1,
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


async def test_unknown_sites_and_configs_are_not_found(client: httpx.AsyncClient, world: World) -> None:
    site = await client.get("/v1/sites/nowhere.example.test/configs")
    config = await client.get(f"/v1/configs/{world.schema.id}")

    assert (site.status_code, config.status_code) == (404, 404)
    assert site.headers["content-type"] == "application/problem+json"


async def test_the_config_api_needs_a_key(client: httpx.AsyncClient, world: World) -> None:
    config_id = await world.active_config(H2)
    client.headers.pop("authorization")

    responses = [
        await client.get(f"/v1/sites/{world.host}/configs"),
        await client.get(f"/v1/configs/{config_id}"),
        await client.put(f"/v1/configs/{config_id}", json={"confirm": ["title"]}),
        await client.post(f"/v1/sites/{world.host}/learn", json={"schema_id": str(world.schema.id)}),
    ]

    assert [r.status_code for r in responses] == [401, 401, 401, 401]


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
    assert body["ir"]["fields"]["title"] == {"steps": [H1], "status": "operator", "yield": 1.0, "validity": 1.0}
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


async def test_a_correction_that_fails_validation_is_kept_as_a_draft_with_its_report(
    client: httpx.AsyncClient, world: World
) -> None:
    await _pages(world, 3)
    first = await world.active_config(H1)

    response = await client.put(f"/v1/configs/{first}", json={"fields": {"title": {"steps": [H2]}}})

    assert response.status_code == 200
    body = response.json()
    assert (body["version"], body["status"], body["field_status"]) == (2, "draft", {"title": "operator"})
    assert body["ir"]["fields"]["title"]["steps"] == [H2]
    report = body["validation_report"]
    assert (report["refused"], report["fields"]["title"]["dropped"]) == ("no_field_kept", "not_reproduced")
    assert await world.configs() == [(1, "active", "induced"), (2, "draft", "operator")]
    assert str((await world.state()).active_config_id) == str(first)


async def test_a_correction_without_three_held_out_pages_is_a_draft(client: httpx.AsyncClient, world: World) -> None:
    await _pages(world, 2)
    first = await world.active_config(H2)

    response = await client.put(f"/v1/configs/{first}", json={"fields": {"title": {"steps": [H1]}}})

    assert (response.json()["status"], response.json()["validation_report"]["refused"]) == (
        "draft",
        "too_few_held_out",
    )


async def test_a_confirmation_on_a_site_with_no_state_yet_activates(client: httpx.AsyncClient, world: World) -> None:
    await _pages(world, 3)
    first = await world.active_config(H1)
    async with world.engine.begin() as conn:
        await conn.execute(delete(ProgressiveState).where(ProgressiveState.site_id == world.site_id))

    response = await client.put(f"/v1/configs/{first}", json={"confirm": ["title"]})

    assert (response.json()["status"], response.json()["field_status"]) == ("active", {"title": "operator"})
    state = await world.state()
    assert (state.mode, str(state.active_config_id)) == ("active", response.json()["id"])


async def test_only_the_latest_version_is_corrected(client: httpx.AsyncClient, world: World) -> None:
    await _pages(world, 3)
    first = await world.active_config(H1)
    await client.put(f"/v1/configs/{first}", json={"confirm": ["title"]})

    response = await client.put(f"/v1/configs/{first}", json={"confirm": ["title"]})

    assert response.status_code == 409
    assert response.json()["detail"] == f"config {first} is version 1; correct the latest, version 2"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"fields": {"price": {"steps": [H1]}}}, "fields.price"),
        ({"confirm": []}, ""),
        ({"fields": {"title": {"steps": [{"xpath": "upper-case(//h1)"}]}}}, "fields.title.steps.0.xpath.xpath"),
        ({"fields": {"title": {"steps": [H1]}}, "status": "active"}, "status"),
    ],
)
async def test_a_correction_that_does_not_fit_is_a_validation_problem(
    client: httpx.AsyncClient, world: World, body: dict[str, Any], field: str
) -> None:
    first = await world.active_config(H1)

    response = await client.put(f"/v1/configs/{first}", json=body)

    assert response.status_code == 422
    assert field in [error["field"] for error in response.json()["errors"]]
    assert await world.configs() == [(1, "active", "induced")]


async def test_correcting_an_unknown_config_is_not_found(client: httpx.AsyncClient, world: World) -> None:
    response = await client.put(f"/v1/configs/{world.schema.id}", json={"confirm": ["title"]})
    assert response.status_code == 404


@pytest.mark.parametrize("app_data", [None])
async def test_without_the_engine_data_a_correction_is_unavailable(client: httpx.AsyncClient, world: World) -> None:
    first = await world.active_config(H1)

    response = await client.put(f"/v1/configs/{first}", json={"confirm": ["title"]})

    assert response.status_code == 503
    assert await world.configs() == [(1, "active", "induced")]


# Learning.


async def _learn(client: httpx.AsyncClient, world: World, **body: Any) -> httpx.Response:
    return await client.post(f"/v1/sites/{world.host}/learn", json={"schema_id": str(world.schema.id), **body})


async def test_learn_starts_a_learn_job_for_the_schema_version(client: httpx.AsyncClient, world: World) -> None:
    response = await _learn(client, world)

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    async with world.engine.connect() as conn:
        job = (await conn.execute(select(Job.kind, Job.schema_id, Job.request).where(Job.id == job_id))).one()
    assert (job.kind, job.schema_id) == ("learn", world.schema.id)
    assert (job.request["page_kind"], job.request["force"]) == ("detail", False)
    assert (await world.state()).mode == "learning"


async def test_learn_is_refused_while_a_run_is_in_flight(client: httpx.AsyncClient, world: World) -> None:
    await _learn(client, world)

    again = await _learn(client, world, force=True)

    assert again.status_code == 409


async def test_an_active_site_relearns_only_when_forced(client: httpx.AsyncClient, world: World) -> None:
    await world.active_config(H1)

    unforced = await _learn(client, world)
    forced = await _learn(client, world, force=True)

    assert (unforced.status_code, forced.status_code) == (409, 202)
    state = await world.state()
    assert (state.mode, state.learning_started_at is not None) == ("active", True)


async def test_learning_an_unknown_site_or_schema_is_not_found(client: httpx.AsyncClient, world: World) -> None:
    site = await client.post("/v1/sites/nowhere.example.test/learn", json={"schema_id": str(world.schema.id)})
    schema = await client.post(f"/v1/sites/{world.host}/learn", json={"schema_id": str(world.site_id)})
    missing = await client.post(f"/v1/sites/{world.host}/learn", json={"force": True})

    assert (site.status_code, schema.status_code, missing.status_code) == (404, 404, 422)


# The held-out loader.


async def test_held_out_pages_are_the_latest_extracted_captures_with_their_published_values(world: World) -> None:
    captures = await _pages(world, 4)
    async with world.engine.connect() as conn:
        pages = await load_held_out(conn, world.store, world.site_id, world.schema, limit=3)

    assert [page.capture_id for page in pages] == captures[:0:-1]
    assert [page.facts.published for page in pages] == [{"title": f"Kettle {n}"} for n in (3, 2, 1)]
    assert pages[0].facts.references == {"title": ["Kettle 3"]}
    assert pages[0].page.html.startswith("<html>")


async def test_held_out_pages_skip_expired_bundles_and_pages_without_records(world: World) -> None:
    kept, expired = await _pages(world, 2)
    await world.store_only("/unextracted", _page("Toaster"))
    async with world.engine.connect() as conn:
        key = (await conn.execute(select(Capture.object_key).where(Capture.id == expired))).scalar_one()
    world.store.delete(key)

    async with world.engine.connect() as conn:
        pages = await load_held_out(conn, world.store, world.site_id, world.schema, limit=8)

    assert [page.capture_id for page in pages] == [kept]
