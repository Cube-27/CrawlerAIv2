"""Field names drafted into a schema by role S (SPEC-14 §4.10, D-0810), over HTTP: `POST /v1/schemas/draft`, and
`schema.fields` on every run type (scrape, batch, crawl, extract), each using the one stored draft of the names.

The app runs against the test database with stub fetching (synthetic pages on RFC 2606 hosts, a stub resolver) and a
fake LLM provider: nothing leaves the process.
"""

import itertools
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import JsonValue
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, Job
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.llm.client import MeteredClient, ProviderReply, Unconfigured
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.llm.roles.s_schema import fields_name
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.storage.fs import FsStore
from tests.db.conftest import _delete_schemas, resolve

pytestmark = pytest.mark.anyio

PAGE = (
    b"<!doctype html><html><head><title>Blue kettle</title></head><body><main><h1>Blue kettle</h1></main></body></html>"
)


def draft(names: list[str], page_kind: str = "detail") -> ProviderReply:
    """A role S reply with one described text field per name."""
    document: dict[str, JsonValue] = {
        "page_kind": page_kind,
        "fields": {name: {"type": "text", "description": f"The {name} of the item"} for name in names},
    }
    return ProviderReply(model="fake-strong", text=json.dumps(to_wire(document)), tokens_in=9, tokens_out=8)


@pytest.fixture
async def names(engine: AsyncEngine) -> AsyncIterator[list[str]]:
    """Two field names no other test drafts; their drafts, for either page kind, are deleted afterwards."""
    suffix = uuid.uuid4().hex[:8]
    chosen = [f"title_{suffix}", f"colour_{suffix}"]
    yield chosen
    for page_kind in ("detail", "listing"):
        await _delete_schemas(engine, fields_name(chosen, page_kind))


@pytest.fixture
def provider(names: list[str]) -> FakeProvider:
    return FakeProvider([draft(names)])


@dataclass(frozen=True)
class Api:
    http: httpx.AsyncClient
    app: FastAPI

    def without_llm(self) -> None:
        self.app.state.llm = Unconfigured("no LLM provider is configured")

    def drafting_with(self, provider: FakeProvider, engine: AsyncEngine) -> None:
        self.app.state.llm = MeteredClient([provider], engine)


@pytest.fixture
async def api(
    database_url: str,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    own_origin: str,
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[Api]:
    """The app with the engine's data, fetching one page of `own_origin` (anything else is a 404) and drafting with
    `provider`. `engine` deletes the jobs afterwards; the key is deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    pages = {f"{own_origin}/robots.txt": b"User-agent: *\nAllow: /\n", f"{own_origin}/p/1": PAGE}

    async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
        body = pages.get(url)
        return (
            fetch_result(url, 404, b"gone", block_class="not_found") if body is None else fetch_result(url, 200, body)
        )

    async with engine.begin() as conn:
        key = await create_key(conn, "fields-draft-test")
    app = create_app(eval_ui=False)
    clock = itertools.count(step=3600)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        limiter = HostLimiter(clock=lambda: float(next(clock)))
        store = FsStore(tmp_path / "objects")
        app.state.fetching = Fetching(Rungs(http=fetch, browser=fetch), SafeConnector(resolve), store, limiter)
        app.state.engine_data = engine_data
        app.state.llm = MeteredClient([provider], engine)
        yield Api(client, app)
    keys_engine = create_async_engine(database_url)
    async with keys_engine.begin() as conn:
        await conn.execute(update(Job).where(Job.api_key_id == key.id).values(api_key_id=None))
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys_engine.dispose()


async def _drafts(engine: AsyncEngine, name: str) -> int:
    async with engine.connect() as conn:
        count: int = (
            await conn.execute(select(func.count()).select_from(SchemaRow).where(SchemaRow.name == name))
        ).scalar_one()
    return count


async def test_names_are_drafted_into_a_stored_schema_with_exactly_those_fields(
    api: Api, engine: AsyncEngine, names: list[str], provider: FakeProvider
) -> None:
    response = await api.http.post("/v1/schemas/draft", json={"fields": names, "page_kind": "detail"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["origin"], body["page_kind"]) == (
        fields_name(names, "detail"),
        "prompt_draft",
        "detail",
    )
    assert sorted(body["fields"]) == sorted(names)
    assert f'<fields page_kind="detail">\n{chr(10).join(sorted(names))}\n</fields>' in provider.calls[0].user


async def test_the_same_names_in_another_order_reuse_the_draft_without_a_call(
    api: Api, engine: AsyncEngine, names: list[str], provider: FakeProvider
) -> None:
    first = await api.http.post("/v1/schemas/draft", json={"fields": names, "page_kind": "detail"})
    second = await api.http.post("/v1/schemas/draft", json={"fields": names[::-1], "page_kind": "detail"})

    assert second.json() == first.json()
    assert len(provider.calls) == 1
    assert await _drafts(engine, fields_name(names, "detail")) == 1


@pytest.mark.parametrize(
    "replies",
    [
        pytest.param("other names", id="fields other than the names"),
        pytest.param("other page kind", id="a draft of another page kind"),
    ],
)
async def test_a_draft_that_does_not_match_the_names_is_retried_then_refused(
    api: Api, engine: AsyncEngine, names: list[str], replies: str
) -> None:
    wrong = draft([names[0]]) if replies == "other names" else draft(names, "listing")
    provider = FakeProvider([wrong, wrong])
    api.drafting_with(provider, engine)

    response = await api.http.post("/v1/schemas/draft", json={"fields": names, "page_kind": "detail"})

    assert (response.status_code, response.json()["type"]) == (502, "llm_output_invalid")
    assert len(provider.calls) == 2
    assert "rejected: " in provider.calls[1].user
    assert await _drafts(engine, fields_name(names, "detail")) == 0


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(["Product price"], id="not a field name"),
        pytest.param(["price", "price"], id="a name twice"),
        pytest.param([], id="no name"),
    ],
)
async def test_names_that_are_not_distinct_field_names_are_refused(
    api: Api, provider: FakeProvider, fields: list[str]
) -> None:
    response = await api.http.post("/v1/schemas/draft", json={"fields": fields, "page_kind": "detail"})

    assert (response.status_code, response.json()["type"]) == (422, "validation")
    assert provider.calls == []


async def test_without_an_llm_the_draft_is_unavailable_and_nothing_is_stored(
    api: Api, engine: AsyncEngine, names: list[str]
) -> None:
    api.without_llm()

    response = await api.http.post("/v1/schemas/draft", json={"fields": names, "page_kind": "detail"})

    assert (response.status_code, response.json()["type"]) == (503, "llm_unavailable")
    assert await _drafts(engine, fields_name(names, "detail")) == 0


def _runs(own_origin: str, names: list[str]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Each run type's path and body, its schema given as `names`."""
    schema = {"fields": names}
    url = f"{own_origin}/p/1"
    return {
        "scrape": ("/v1/scrape", {"url": url, "formats": ["records"], "schema": schema, "page_kind": "detail"}),
        "batch": ("/v1/batch/scrape", {"urls": [url], "formats": ["records"], "schema": schema, "page_kind": "detail"}),
        "crawl": (
            "/v1/crawl",
            {
                "url": url,
                "formats": ["records"],
                "schema": schema,
                "page_kind_rules": [{"pattern": f"{own_origin}/p/*", "page_kind": "detail"}],
            },
        ),
        "extract": ("/v1/extract", {"urls": [url], "schema": schema, "page_kind": "detail"}),
    }


@pytest.mark.parametrize("run", ["scrape", "batch", "crawl", "extract"])
async def test_every_run_type_extracts_with_the_draft_of_its_field_names(
    api: Api, engine: AsyncEngine, own_origin: str, names: list[str], run: str
) -> None:
    drafted = (await api.http.post("/v1/schemas/draft", json={"fields": names, "page_kind": "detail"})).json()
    path, body = _runs(own_origin, names)[run]

    response = await api.http.post(path, json=body)

    assert response.status_code in {200, 202}, response.text
    async with engine.connect() as conn:
        job = (await conn.execute(select(Job.schema_id, Job.request).where(Job.id == response.json()["job_id"]))).one()
    assert (str(job.schema_id), job.request["schema"]) == (drafted["id"], {"fields": names})


@pytest.mark.parametrize("run", ["scrape", "batch", "crawl", "extract"])
async def test_a_run_whose_names_cannot_be_drafted_is_refused_and_stores_no_job(
    api: Api, engine: AsyncEngine, own_origin: str, names: list[str], run: str
) -> None:
    api.without_llm()
    path, body = _runs(own_origin, names)[run]
    async with engine.connect() as conn:
        before = (await conn.execute(select(func.count()).select_from(Job))).scalar_one()

    response = await api.http.post(path, json=body)

    assert (response.status_code, response.json()["type"]) == (503, "llm_unavailable")
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Job))).scalar_one() == before
