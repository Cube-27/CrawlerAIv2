"""An adapter's requests go as politely as a page's: only where the endpoint host's robots.txt
allows them, at that host's rate, the first one on the turn the caller was admitted for; and the processes that
fetch run every adapter `CRAWLERAI_DISABLED_ADAPTERS` does not name.

Hosts are synthetic (`example.test`, C3); nothing goes to the network.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.services.fetching import Fetching, adapter_send
from crawlerai.services.polite import HostRules
from crawlerai.storage.capture_bundle import HeaderList
from crawlerai.storage.fs import FsStore

PAGE_HOST = "shop.example.test"


class CountingLimiter(HostLimiter):
    """Admits at once, and records each host a request waited for a turn at."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[str] = []

    async def wait(
        self, host: str, interval: timedelta, bound: timedelta = timedelta.max, *, after: timedelta = timedelta(0)
    ) -> bool:
        self.waits.append(host)
        return True


def _answer(request: JsonRequest, status: int = 200, headers: HeaderList = ()) -> FetchResult:
    return fetch_result(
        url=request.page_url,
        method="api",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url=request.url, status=status, request_headers=(), response_headers=headers),
        content=Content(body=b"{}" if status == 200 else b""),
        block_class="ok" if status == 200 else "blocked",
        error=None,
    )


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


async def _never(_url: str, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("no page is fetched here")


def _fetching(tmp_path: Path, sent: list[str], limiter: HostLimiter) -> Fetching:
    async def json(request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
        sent.append(request.url)
        return _answer(request)

    rungs = Rungs(http=_never, browser=_never, json=json)
    return Fetching(rungs, SafeConnector(), FsStore(tmp_path), limiter)


def _request(host: str) -> JsonRequest:
    return JsonRequest(
        url=f"https://{host}/api/graphql.json", page_url=f"https://{PAGE_HOST}/products/w", method="POST"
    )


async def _allowed(_url: str, _policy: FetchPolicy) -> HostRules:
    return HostRules()


def test_a_request_robots_txt_disallows_is_not_sent_and_is_blocked(tmp_path: Path) -> None:
    sent: list[str] = []

    async def disallowed(_url: str, _policy: FetchPolicy) -> HostRules:
        return HostRules(Robots("User-agent: *\nDisallow: /\n"))

    send = adapter_send(_fetching(tmp_path, sent, CountingLimiter()), PAGE_HOST, disallowed)
    assert send is not None

    async def one() -> FetchResult:
        return await send(_request(PAGE_HOST), FetchPolicy())

    result = asyncio.run(one())

    assert (sent, result.block_class, result.attempts[-1].error) == ([], "blocked", "robots")


def test_a_slow_down_with_a_retry_after_pauses_the_endpoint_host(tmp_path: Path) -> None:
    # RFC 6585 §4, RFC 9110 §10.2.3: the pause goes on the host's rate, so the page's fallback request waits it out.
    clock = Clock()
    limiter = HostLimiter(clock)

    async def json(request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
        return _answer(request, 429, (("Retry-After", "20"),))

    fetching = Fetching(Rungs(http=_never, browser=_never, json=json), SafeConnector(), FsStore(tmp_path), limiter)
    send = adapter_send(fetching, PAGE_HOST, _allowed)
    assert send is not None

    async def one() -> FetchResult:
        return await send(_request(PAGE_HOST), FetchPolicy())

    asyncio.run(one())

    assert asyncio.run(limiter.admit(PAGE_HOST, timedelta(seconds=1))) == timedelta(seconds=20)
