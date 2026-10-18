"""`POST /v1/search` (D-1442): what a client sends and gets back, with a stub provider; nothing leaves the process.
How a provider is asked and its answer read is `tests/unit/test_search_providers.py`. Hosts are RFC 2606 names."""

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

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


async def test_without_a_provider_search_is_a_503_search_unavailable(
    submit_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    response = await _search(*submit_app, None, query="kettles")

    assert response.status_code == 503
    assert response.json()["type"] == "search_unavailable"


async def test_scrape_of_results_no_one_may_fetch_queues_nothing(
    submit_app: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    only = Stub([HITS[1]])

    response = await _search(*submit_app, only, query="kettles", scrape={})

    assert response.json()["job_id"] is None
    assert response.json()["skipped"] == 1
