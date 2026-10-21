"""`POST /v1/map` over HTTP (jobs spec): what a client sends and gets back. What a map does is the service's
(`test_map_service.py`)."""

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.types import FetchResult
from crawlerai.services.fetching import Fetching
from tests.db.support import PRIVATE_HOST, Web, api

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    sitemap = f'<urlset xmlns="{NS}"><url><loc>{own_origin}/p/1</loc></url></urlset>'
    site = Web(fetch_result)
    site.robots(own_origin, f"User-agent: *\nSitemap: {own_origin}/s.xml\n".encode())
    site.serve(f"{own_origin}/s.xml", sitemap.encode())
    site.serve(f"{own_origin}/", b'<html><body><a href="/c/1">c</a><a href="/p/1">p</a></body></html>')
    return site


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch, engine: AsyncEngine, fetching: Fetching
) -> AsyncIterator[httpx.AsyncClient]:
    async with api(engine) as (app, client):
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
