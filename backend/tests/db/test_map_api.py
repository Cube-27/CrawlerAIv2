"""`POST /v1/map` over HTTP (jobs spec): what a client sends and gets back. What a map does is the service's
(`test_map_service.py`)."""

import itertools
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
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey
from crawlerai.services.fetching import Fetching
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


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
    sitemap = f'<urlset xmlns="{NS}"><url><loc>{own_origin}/p/1</loc></url></urlset>'
    return {
        f"{own_origin}/robots.txt": (200, f"User-agent: *\nSitemap: {own_origin}/s.xml\n".encode()),
        f"{own_origin}/s.xml": (200, sitemap.encode()),
        f"{own_origin}/": (200, b'<html><body><a href="/c/1">c</a><a href="/p/1">p</a></body></html>'),
    }


@pytest.fixture
def fetching(fetch_result: Callable[..., FetchResult], pages: dict[str, tuple[int, bytes]], tmp_path: Path) -> Fetching:
    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        status, body = pages.get(url, (404, b""))
        return fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found")

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    clock = itertools.count(step=3600)
    limiter = HostLimiter(clock=lambda: float(next(clock)))
    return Fetching(Rungs(http=http, browser=http), SafeConnector(resolve), FsStore(tmp_path / "objects"), limiter)


@pytest.fixture
async def client(database: AsyncEngine, fetching: Fetching) -> AsyncIterator[httpx.AsyncClient]:
    async with database.begin() as conn:
        key = await create_key(conn, "map-api-test")
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
    return await client.post("/v1/map", json=body)


async def test_answers_the_urls_found_with_their_sources(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/"})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "urls": [f"{own_origin}/p/1", f"{own_origin}/c/1"],
        "sources": {"sitemap": 1, "links": 1},
        "truncated": False,
    }


async def test_a_private_target_is_an_ssrf_problem(client: httpx.AsyncClient) -> None:
    response = await _post(client, {"url": f"https://{PRIVATE_HOST}/"})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "ssrf_rejected",
        "detail": "ssrf_rejected: private_address",
    }


async def test_a_request_without_a_key_is_unauthorized(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await client.post("/v1/map", json={"url": f"{own_origin}/"}, headers={"authorization": ""})

    assert response.status_code == 401
    assert response.json()["type"] == "unauthorized"
