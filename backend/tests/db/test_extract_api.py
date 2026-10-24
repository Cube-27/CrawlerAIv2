"""`POST /v1/extract` over HTTP: what a client sends and gets back. What an extract job does is the
service's and the worker's (`test_extract.py`)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

import httpx
import pytest
from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.types import FetchResult
from snowcrawl.db.models import ApiKey, Job, UrlTask
from snowcrawl.llm.client import MeteredClient, ProviderReply
from snowcrawl.llm.roles.s_schema import draft_name
from snowcrawl.llm.roles.s_wire import to_wire
from snowcrawl.resolve.pipeline import EngineData
from snowcrawl.services.fetching import Fetching
from tests.db.support import KEY_LABEL, PRIVATE_HOST, UNRESOLVED_HOST, Page, Web, api
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

DRAFT: dict[str, JsonValue] = {
    "page_kind": "detail",
    "fields": {"title": {"type": "text", "required": True, "description": "The name", "schema_org": "Product.name"}},
}
PAGE = (
    b"<!doctype html><html><head><title>Blue kettle</title></head><body><main><h1>Blue kettle</h1></main></body></html>"
)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(
        [ProviderReply(model="fake-strong", text=json.dumps(to_wire(DRAFT)), tokens_in=9, tokens_out=8)]
    )


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    site = Web.site(fetch_result, own_origin)
    site.serve(f"{own_origin}/p/1", PAGE)
    return site


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetching: Fetching,
    provider: FakeProvider,
) -> AsyncIterator[httpx.AsyncClient]:
    """The app with the engine's data, fetching `web` and drafting with `provider`."""
    async with api(engine) as (app, client):
        llm = MeteredClient([provider], engine)
        app.state.runtime = replace(app.state.runtime, fetching=fetching, engine_data=engine_data, llm=llm)
        yield client


async def _post(client: httpx.AsyncClient, urls: list[str], schema: dict[str, Any], **body: Any) -> httpx.Response:
    return await client.post("/v1/extract", json={"urls": urls, "schema": schema, "page_kind": "detail", **body})


async def test_a_prompt_is_answered_with_its_draft_and_the_queued_job(
    client: httpx.AsyncClient, engine: AsyncEngine, own_origin: str, prompt: str
) -> None:
    response = await _post(client, [f"{own_origin}/p/1"], {"prompt": prompt})

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["schema"]["name"], list(body["schema"]["fields"])) == (draft_name(prompt), ["title"])
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.url).where(UrlTask.job_id == body["job_id"]))).scalar_one()
        label = select(ApiKey.label).join(Job, Job.api_key_id == ApiKey.id).where(Job.id == body["job_id"])
        assert (await conn.execute(label)).scalar_one() == KEY_LABEL  # its secret signs the webhook
    assert task == f"{own_origin}/p/1"
    status = await client.get(f"/v1/jobs/{body['job_id']}")
    assert (status.json()["kind"], status.json()["counts"]["queued"]) == ("extract", 1)


async def test_a_glob_on_a_private_host_is_refused_with_its_member(
    client: httpx.AsyncClient, engine: AsyncEngine, own_origin: str, prompt: str
) -> None:
    response = await _post(client, [f"{own_origin}/p/1", f"https://{PRIVATE_HOST}/p/*"], {"prompt": prompt})

    assert response.status_code == 422, response.text
    body = response.json()
    assert (body["type"], [error["field"] for error in body["errors"]]) == ("ssrf_rejected", ["urls[1]"])
    assert PRIVATE_HOST not in response.text
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "extract"))).all() == []


async def test_a_url_whose_host_does_not_resolve_is_queued_and_no_sample_of_the_draft(
    client: httpx.AsyncClient, engine: AsyncEngine, web: Web, own_origin: str, prompt: str
) -> None:
    urls = [f"https://{UNRESOLVED_HOST}/p/2", f"{own_origin}/p/1"]
    # The rungs stand in for the guard: the fetch of the sample at the host records its refusal.
    web.pages[urls[0]] = Page(0, b"", "error", "ssrf_rejected: dns")

    response = await _post(client, urls, {"prompt": prompt})

    assert response.status_code == 202, response.text
    async with engine.connect() as conn:
        tasks = await conn.execute(select(UrlTask.url).where(UrlTask.job_id == response.json()["job_id"]))
        assert sorted(tasks.scalars().all()) == sorted(urls)


async def test_extract_needs_a_key(client: httpx.AsyncClient, own_origin: str) -> None:
    del client.headers["authorization"]

    response = await _post(client, [f"{own_origin}/p/1"], {"prompt": "kettles"})

    assert (response.status_code, response.json()["type"]) == (401, "unauthorized")
