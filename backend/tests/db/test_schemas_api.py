"""`/v1/schemas` over HTTP (SPEC-07 §4.6): bearer-authenticated CRUD whose errors are RFC 9457 problems. The rules
themselves are the service's (`test_schema_service.py`); these tests check what a client sends and gets back."""

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, ExtractionConfig, ProgressiveState, SchemaId, Site
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.schemas import registry
from tests.db.conftest import learned_site

pytestmark = pytest.mark.anyio

TITLE = {"type": "text", "required": True, "description": "Name of the event"}
STARTS = {"type": "datetime", "description": "When the event starts"}
EVENT = {"name": "event_detail", "page_kind": "detail", "fields": {"title": TITLE}}


@pytest.fixture
async def database(database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """The app's settings pointed at the test database, with every key, site and schema a test added deleted
    afterwards."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        keys = set((await conn.execute(select(ApiKey.id))).scalars())
        schemas = set((await conn.execute(select(SchemaRow.id))).scalars())
        sites = set((await conn.execute(select(Site.id))).scalars())
    yield engine
    async with engine.begin() as conn:
        await conn.execute(delete(ProgressiveState).where(ProgressiveState.schema_id.not_in(schemas)))
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.schema_id.not_in(schemas)))
        await conn.execute(delete(Site).where(Site.id.not_in(sites)))
        await conn.execute(delete(SchemaRow).where(SchemaRow.id.not_in(schemas)))
        await conn.execute(delete(ApiKey).where(ApiKey.id.not_in(keys)))
    await engine.dispose()


@pytest.fixture
async def client(database: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with database.begin() as conn:
        key = await create_key(conn, "schemas-api-test")
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


async def _created(client: httpx.AsyncClient, body: dict[str, Any] = EVENT) -> dict[str, Any]:
    response = await client.post("/v1/schemas", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def test_post_creates_a_user_schema(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/schemas", json=EVENT)

    created = response.json()
    assert response.status_code == 201
    assert response.headers["location"] == f"/v1/schemas/{created['id']}"
    assert {k: created[k] for k in ("name", "page_kind", "origin", "status", "required_groups")} == {
        "name": "event_detail",
        "page_kind": "detail",
        "origin": "user",
        "status": "active",
        "required_groups": [],
    }
    assert created["fields"]["title"]["description"] == "Name of the event"
    assert (await client.get(f"/v1/schemas/{created['id']}")).json() == created


async def test_put_edits_the_schema_in_place_and_sends_its_site_configs_back_to_learning(
    client: httpx.AsyncClient, database: AsyncEngine
) -> None:
    first = await _created(client)
    async with database.begin() as conn:
        key = await learned_site(conn, await registry.get_by_id(conn, SchemaId(uuid.UUID(first["id"]))), ["active"])
    edit = {"page_kind": "detail", "fields": {"title": TITLE, "starts": STARTS}}

    response = await client.put(f"/v1/schemas/{first['id']}", json=edit)

    assert response.status_code == 200, response.text
    edited = response.json()
    assert (edited["id"], sorted(edited["fields"]), edited["fields"]["title"]) == (
        first["id"],
        ["starts", "title"],
        first["fields"]["title"],
    )
    assert (await client.get("/v1/schemas", params={"name": "event_detail"})).json() == {"items": [edited]}
    async with database.connect() as conn:
        status = (await conn.execute(select(ExtractionConfig.status).where(*key.config_scope()))).one()
        state = select(ProgressiveState.mode, ProgressiveState.active_config_id).where(*key.where())
        assert (status, (await conn.execute(state)).one()) == (("suspended",), ("cold", None))


async def test_delete_retires_the_schema_and_keeps_it_readable(client: httpx.AsyncClient) -> None:
    created = await _created(client)

    response = await client.delete(f"/v1/schemas/{created['id']}")

    assert response.status_code == 204
    assert (await client.get(f"/v1/schemas/{created['id']}")).json() == {**created, "status": "retired"}
    active = (await client.get("/v1/schemas", params={"name": "event_detail", "status": "active"})).json()
    retired = (await client.get("/v1/schemas", params={"name": "event_detail", "status": "retired"})).json()
    assert active == {"items": []}
    assert [s["id"] for s in retired["items"]] == [created["id"]]


async def test_put_on_a_retired_schema_conflicts(client: httpx.AsyncClient) -> None:
    first = await _created(client)
    await client.delete(f"/v1/schemas/{first['id']}")

    response = await client.put(f"/v1/schemas/{first['id']}", json={"page_kind": "detail", "fields": {"title": TITLE}})

    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert (response.json()["type"], response.json()["detail"]) == ("conflict", "schema event_detail is retired")


async def test_a_taken_name_conflicts(client: httpx.AsyncClient) -> None:
    await _created(client)

    response = await client.post("/v1/schemas", json=EVENT)

    assert response.status_code == 409
    assert (response.json()["type"], response.json()["detail"]) == (
        "conflict",
        "schema event_detail exists; edit it instead",
    )


async def test_a_broken_document_rule_is_a_validation_problem(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/schemas", json={**EVENT, "required_groups": [["sku"]]})

    problem = response.json()
    assert response.status_code == 422
    assert problem["type"] == "validation"
    # The reason is the rule's own message, as labels report theirs (`core.validation.field_error`).
    assert problem["errors"] == [{"field": "", "reason": "required group ['sku'] names unknown fields ['sku']"}]


async def test_a_malformed_field_is_a_validation_problem_naming_it(client: httpx.AsyncClient) -> None:
    response = await client.post("/v1/schemas", json={**EVENT, "fields": {"title": {**TITLE, "type": "colour"}}})

    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == ["fields.title.type"]


async def test_an_unknown_id_is_not_found(client: httpx.AsyncClient) -> None:
    missing = uuid.uuid4()
    edit = {"page_kind": "detail", "fields": {"title": TITLE}}

    responses = [
        await client.get(f"/v1/schemas/{missing}"),
        await client.put(f"/v1/schemas/{missing}", json=edit),
        await client.delete(f"/v1/schemas/{missing}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert {r.json()["type"] for r in responses} == {"not_found"}


async def test_every_route_needs_an_api_key(client: httpx.AsyncClient) -> None:
    some_id = uuid.uuid4()
    client.headers.pop("authorization")

    responses = [
        await client.get("/v1/schemas"),
        await client.post("/v1/schemas", json=EVENT),
        await client.get(f"/v1/schemas/{some_id}"),
        await client.put(f"/v1/schemas/{some_id}", json=EVENT),
        await client.delete(f"/v1/schemas/{some_id}"),
    ]

    assert [r.status_code for r in responses] == [401] * 5
    assert {r.json()["type"] for r in responses} == {"unauthorized"}


async def test_put_labels_edits_the_label_synonyms_without_editing_the_document(client: httpx.AsyncClient) -> None:
    created = await _created(client)

    response = await client.put(f"/v1/schemas/{created['id']}/labels", json={"labels": {"title": ["Event", "Anlass"]}})
    unknown = await client.put(f"/v1/schemas/{created['id']}/labels", json={"labels": {"venue": ["Venue"]}})

    assert response.status_code == 200, response.text
    assert response.json() == {**created, "labels": {"title": ["Event", "Anlass"]}}
    assert unknown.status_code == 422
    assert [e["field"] for e in unknown.json()["errors"]] == ["labels.venue"]
