"""`POST /v1/batch/scrape` over HTTP (SPEC-10 §4.3): what a client sends and gets back. What a batch does is the
service's and the worker's (`test_batch_scrape.py`).

The app runs with its real settings against the test database; its fetching is replaced by a stub resolver, so
nothing leaves the process. Hosts are RFC 2606 names.
"""

from collections.abc import AsyncIterator
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.api.keys import create_key
from crawlerai.db.models import ApiKey, Job, UrlTask
from crawlerai.services.scrape import Fetching
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
URL = "https://shop.example.test/kettles/blue"


@pytest.fixture
async def client(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, without the engine's data files. `engine` deletes the jobs afterwards;
    the key is deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    async def never(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("submitting a batch fetches nothing")

    async with engine.begin() as conn:
        key = await create_key(conn, "batch-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        store = FsStore(tmp_path / "objects")
        app.state.fetching = Fetching(Rungs(http=never, browser=never), SafeConnector(resolve), store, HostLimiter())
        app.state.engine_data = None
        yield client
    keys_engine = create_async_engine(database_url)
    async with keys_engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys_engine.dispose()


async def _post(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/v1/batch/scrape", json=body)


async def test_a_batch_is_accepted_and_queued(client: httpx.AsyncClient, engine: AsyncEngine) -> None:
    response = await _post(client, urls=[URL, URL.replace("blue", "red")], formats=["markdown"])

    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    async with engine.connect() as conn:
        tasks = (await conn.execute(select(UrlTask.status).where(UrlTask.job_id == job_id))).scalars().all()
    assert tasks == ["queued", "queued"]
    status = await client.get(f"/v1/jobs/{job_id}")
    assert (status.json()["kind"], status.json()["counts"]["queued"]) == ("batch_scrape", 2)


async def test_a_private_target_is_refused_with_the_member_that_names_it(
    client: httpx.AsyncClient, engine: AsyncEngine
) -> None:
    response = await _post(client, urls=[URL, f"https://{PRIVATE_HOST}/admin"], formats=["markdown"])

    assert response.status_code == 422, response.text
    body = response.json()
    assert (body["type"], [error["field"] for error in body["errors"]]) == ("ssrf_rejected", ["urls[1]"])
    assert PRIVATE_HOST not in response.text
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "batch_scrape"))).all() == []


async def test_batch_problems(client: httpx.AsyncClient) -> None:
    schema = {"id": "01a13754-8791-738c-86ed-bc3b329d7fb1"}
    responses = {
        "prompt": await _post(
            client, urls=[URL], formats=["records"], schema={"prompt": "kettles"}, page_kind="detail"
        ),
        "records with markdown": await _post(
            client, urls=[URL], formats=["records", "markdown"], schema=schema, page_kind="detail"
        ),
        "no engine data": await _post(client, urls=[URL], formats=["records"], schema=schema, page_kind="detail"),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == {
        "prompt": (422, "validation"),
        "records with markdown": (422, "validation"),
        "no engine data": (503, "records_unavailable"),
    }


async def test_a_batch_needs_a_key(client: httpx.AsyncClient) -> None:
    del client.headers["authorization"]

    assert (await _post(client, urls=[URL], formats=["markdown"])).status_code == 401
