"""`POST /v1/extract` over HTTP (jobs spec): what a client sends and gets back. What an extract job does is the
service's and the worker's (`test_extract.py`)."""

import itertools
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, Job, UrlTask
from crawlerai.llm.client import MeteredClient, ProviderReply
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.storage.fs import FsStore
from tests.db.conftest import PRIVATE_HOST, resolve
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
def pages(own_origin: str) -> dict[str, bytes]:
    return {f"{own_origin}/robots.txt": b"User-agent: *\nAllow: /\n", f"{own_origin}/p/1": PAGE}


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(
        [ProviderReply(model="fake-strong", text=json.dumps(to_wire(DRAFT)), tokens_in=9, tokens_out=8)]
    )


@pytest.fixture
async def client(
    database_url: str,
    engine: AsyncEngine,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    pages: dict[str, bytes],
    provider: FakeProvider,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[httpx.AsyncClient]:
    """The app with the engine's data, fetching `pages` (anything else is a 404) and drafting with `provider`.
    `engine` deletes the jobs afterwards; the key is deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")

    async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
        body = pages.get(url)
        return (
            fetch_result(url, 404, b"gone", block_class="not_found") if body is None else fetch_result(url, 200, body)
        )

    async with engine.begin() as conn:
        key = await create_key(conn, "extract-api-test")
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
        yield client
    keys_engine = create_async_engine(database_url)
    async with keys_engine.begin() as conn:
        await conn.execute(update(Job).where(Job.api_key_id == key.id).values(api_key_id=None))
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys_engine.dispose()


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
        assert (await conn.execute(label)).scalar_one() == "extract-api-test"  # its secret signs the webhook
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


async def test_extract_needs_a_key(client: httpx.AsyncClient, own_origin: str) -> None:
    del client.headers["authorization"]

    response = await _post(client, [f"{own_origin}/p/1"], {"prompt": "kettles"})

    assert (response.status_code, response.json()["type"]) == (401, "unauthorized")
