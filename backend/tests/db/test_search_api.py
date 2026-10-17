"""`POST /v1/search` (D-1442): what a client sends and gets back, with a stub provider; nothing leaves the process.
How a provider is asked and its answer read is `tests/unit/test_search_providers.py`. Hosts are RFC 2606 names."""

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import UrlTask
from crawlerai.search.providers import SearchFailed
from crawlerai.search.results import Hit
from tests.db.conftest import PRIVATE_HOST

pytestmark = pytest.mark.anyio


@dataclass
class Stub:
    hits: list[Hit]
    asked: list[tuple[str, int]] = field(default_factory=list)
    fail: bool = False

    async def search(self, query: str, limit: int) -> list[Hit]:
        self.asked.append((query, limit))
        if self.fail:
            raise SearchFailed("the search provider answered 500")
        return self.hits[:limit]


HITS = [
    Hit("https://docs.example.test/a", "A", "first"),
    Hit(f"https://{PRIVATE_HOST}/b", "B", "private"),
    Hit("https://docs.example.test/c", "C", "third"),
]


async def _search(app: FastAPI, client: httpx.AsyncClient, provider: Stub | None, **body: Any) -> httpx.Response:
    app.state.search = provider
    return await client.post("/v1/search", json=body)


async def test_the_results_come_in_the_providers_order_up_to_the_limit(
    submit_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    provider = Stub(HITS)

    response = await _search(*submit_app, provider, query="kettles", limit=2)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "query": "kettles",
        "results": [
            {"position": 1, "url": "https://docs.example.test/a", "title": "A", "snippet": "first"},
            {"position": 2, "url": f"https://{PRIVATE_HOST}/b", "title": "B", "snippet": "private"},
        ],
        "job_id": None,
        "skipped": 0,
    }
    assert provider.asked == [("kettles", 2)]


async def test_without_a_provider_search_is_a_503_search_unavailable(
    submit_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    response = await _search(*submit_app, None, query="kettles")

    assert response.status_code == 503
    assert response.json()["type"] == "search_unavailable"


async def test_a_provider_that_fails_is_a_502(submit_app: tuple[FastAPI, httpx.AsyncClient]) -> None:
    response = await _search(*submit_app, Stub(HITS, fail=True), query="kettles")

    assert (response.status_code, response.json()["type"]) == (502, "search_failed")


@pytest.mark.parametrize("body", [{"query": "  "}, {"query": "x", "limit": 0}, {"query": "x", "limit": 51}, {}])
async def test_an_invalid_request_is_a_422(submit_app: tuple[FastAPI, httpx.AsyncClient], body: dict[str, Any]) -> None:
    assert (await _search(*submit_app, Stub(HITS), **body)).status_code == 422


async def test_scrape_queues_a_batch_of_the_results_the_api_may_fetch(
    submit_app: tuple[FastAPI, httpx.AsyncClient], engine: AsyncEngine
) -> None:
    response = await _search(*submit_app, Stub(HITS), query="kettles", scrape={"formats": ["markdown", "links"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["skipped"] == 1
    assert len(body["results"]) == 3  # the refused one stays in the answer, unscraped
    async with engine.connect() as conn:
        urls = (await conn.execute(select(UrlTask.url).where(UrlTask.job_id == body["job_id"]))).scalars().all()
    assert sorted(urls) == ["https://docs.example.test/a", "https://docs.example.test/c"]
    status = await submit_app[1].get(f"/v1/jobs/{body['job_id']}")
    assert status.json()["kind"] == "batch_scrape"


async def test_scrape_of_results_no_one_may_fetch_queues_nothing(
    submit_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    only = Stub([HITS[1]])

    response = await _search(*submit_app, only, query="kettles", scrape={})

    assert response.json()["job_id"] is None
    assert response.json()["skipped"] == 1
