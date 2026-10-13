"""`POST /v1/scrape` over HTTP (SPEC-07 §4.4, §4.8): what a client sends and gets back. What a scrape does is the
service's (`test_scrape_service.py`).

The app runs with its real settings against the test database; its fetching is replaced by a stub web of synthetic
pages on RFC 2606 hosts and a stub resolver, so nothing leaves the process.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
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
from crawlerai.db.models import ApiKey
from crawlerai.services.scrape import Fetching
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
PAGE = b"""<!doctype html><html lang="en"><head><title>Blue kettle</title></head>
<body><h1>Blue kettle</h1><a href="/kettles/red">Red kettle</a></body></html>"""


@pytest.fixture
async def database(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[AsyncEngine]:
    """The app's settings pointed at the test database. `engine` deletes the jobs afterwards; the keys a test added
    are deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    keys_engine = create_async_engine(database_url)
    async with keys_engine.connect() as conn:
        keys = set((await conn.execute(select(ApiKey.id))).scalars())
    yield engine
    async with keys_engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id.not_in(keys)))
    await keys_engine.dispose()


@pytest.fixture
def pages(own_origin: str) -> dict[str, tuple[int, bytes]]:
    return {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")}


@pytest.fixture
def fetching(fetch_result: Callable[..., FetchResult], pages: dict[str, tuple[int, bytes]], tmp_path: Path) -> Fetching:
    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        if url.endswith("/slow"):
            await asyncio.sleep(5)
        status, body = pages.get(url, (404, b""))
        return fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found")

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    store = FsStore(tmp_path / "objects")
    return Fetching(Rungs(http=http, browser=http), SafeConnector(resolve), store, HostLimiter())


@pytest.fixture
async def client(database: AsyncEngine, fetching: Fetching) -> AsyncIterator[httpx.AsyncClient]:
    async with database.begin() as conn:
        key = await create_key(conn, "scrape-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        app.state.fetching = fetching
        yield client


async def _post(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/v1/scrape", json=body)


async def test_answers_the_requested_formats_and_only_those(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    response = await _post(client, {"url": url, "formats": ["links", "metadata"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        *("job_id", "capture_id", "url", "final_url", "fetched_at", "outcome", "fetch", "usage"),
        *("links", "metadata"),
    }
    assert (body["url"], body["final_url"], body["outcome"]) == (url, url, "extracted")
    assert body["links"] == [f"{own_origin}/kettles/red"]
    assert body["metadata"] == {
        "title": "Blue kettle",
        "description": None,
        "language": "en",
        "canonical": None,
        "og": {},
        "structured_data_types": [],
    }
    assert body["fetch"] == {
        "method": "http",
        "status_code": 200,
        "block_class": "ok",
        "attempts": [{"method": "http", "status": 200, "block_class": "ok", "duration_ms": 1, "error": None}],
    }
    assert body["usage"] == {
        "llm_calls": 0,
        "llm_tokens_in": 0,
        "llm_tokens_out": 0,
        "browser_seconds": 0,
        "http_requests": 2,
    }


async def test_a_page_not_found_is_an_outcome_in_a_200(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/gone", "formats": ["markdown"]})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "not_found"
    assert "markdown" not in body


async def test_a_private_target_is_an_ssrf_problem(client: httpx.AsyncClient) -> None:
    response = await _post(client, {"url": f"https://{PRIVATE_HOST}/", "formats": ["markdown"]})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "ssrf_rejected",
        "detail": "ssrf_rejected: private_address",
    }


async def test_a_scrape_past_its_timeout_is_a_timeout_problem(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/slow", "formats": ["markdown"], "timeout_s": 0.2})

    assert response.status_code == 504
    assert response.json()["type"] == "timeout"


async def test_an_invalid_request_is_a_validation_problem(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/", "formats": ["markdown"], "timeout_s": 121})

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "validation"
    assert [error["field"] for error in problem["errors"]] == ["timeout_s"]


async def test_a_request_without_a_key_is_unauthorized(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await client.post(
        "/v1/scrape", json={"url": f"{own_origin}/", "formats": ["markdown"]}, headers={"authorization": ""}
    )

    assert response.status_code == 401
    assert response.json()["type"] == "unauthorized"
