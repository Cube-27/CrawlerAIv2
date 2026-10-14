"""A learning run's recipe replays (SPEC-09 §4.6, §4.7) go out as politely as a served recipe's request (SPEC-02 §4.6,
D-0731): only where the endpoint host's robots.txt allows, at that host's rate.

The web is a stub that answers robots.txt and JSON on RFC 2606 hosts: no network.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Site
from crawlerai.services.fetching import Fetching, learning_replay
from crawlerai.storage.fs import FsStore
from tests.db.conftest import resolve

pytestmark = pytest.mark.anyio


@dataclass
class Web:
    """Answers robots.txt from `robots` and every endpoint with one JSON object; the browser is never used."""

    fetch_result: Callable[..., FetchResult]
    robots: bytes
    requested: list[str] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        assert url.endswith("/robots.txt"), "a replay fetches no page"
        return self.fetch_result(url, 200, self.robots)

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("a replay never needs a browser")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request.url)
        return self.fetch_result(request.page_url, 200, json.dumps({"data": {}}).encode(), method="api")


@pytest.fixture
async def api_host(engine: AsyncEngine) -> AsyncIterator[str]:
    """An endpoint host no other test uses; the site row the replay creates for it is deleted afterwards."""
    host = f"api-{uuid7().hex[-12:]}.example.test"
    yield host
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.host == host))


def _fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.http, browser=web.browser, json=web.json)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


def _admissions(fetching: Fetching) -> list[str]:
    """The hosts `fetching`'s limiter admits a request to from now on, in order."""
    admitted: list[str] = []
    admit = fetching.limiter.admit

    def recording(host: str, interval: timedelta) -> timedelta:
        wait = admit(host, interval)
        if not wait:
            admitted.append(host)
        return wait

    fetching.limiter.admit = recording  # type: ignore[method-assign]
    return admitted


async def test_a_replay_robots_txt_allows_is_sent_at_the_endpoint_host_rate(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], api_host: str, tmp_path: Path
) -> None:
    web = Web(fetch_result, b"User-agent: *\nAllow: /\n")
    fetching = _fetching(web, tmp_path)
    admitted = _admissions(fetching)
    replay = learning_replay(engine, fetching)
    assert replay is not None
    endpoint = f"https://{api_host}/v1/products/item-a"

    result = await replay(JsonRequest(endpoint, "https://shop.example.test/p/item-a"))

    assert (result.block_class, web.requested, admitted) == ("ok", [endpoint], [api_host])


async def test_a_replay_robots_txt_disallows_is_not_sent(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], api_host: str, tmp_path: Path
) -> None:
    web = Web(fetch_result, b"User-agent: *\nDisallow: /v1/\n")
    replay = learning_replay(engine, _fetching(web, tmp_path))
    assert replay is not None

    result = await replay(JsonRequest(f"https://{api_host}/v1/products/item-a", "https://shop.example.test/p/item-a"))

    assert (result.block_class, result.attempts[-1].error, web.requested) == ("blocked", "robots", [])


async def test_without_a_json_rung_there_is_no_replay(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], tmp_path: Path
) -> None:
    web = Web(fetch_result, b"")
    rungs = Rungs(http=web.http, browser=web.browser)
    fetching = Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())

    assert learning_replay(engine, fetching) is None
