"""An adapter's requests go as politely as a page's (SPEC-15 §4.6, §4.8): only where the endpoint host's robots.txt
allows them, at that host's rate, the first one on the turn the caller was admitted for; and the processes that
fetch run every adapter `CRAWLERAI_DISABLED_ADAPTERS` does not name.

Hosts are synthetic (`example.test`, C3); nothing goes to the network.
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.politeness import BACKOFF_MAX, HostLimiter
from crawlerai.acquire.robots import Robots
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.greenhouse import BOARD_HOSTS
from crawlerai.core.settings import AcquireSettings
from crawlerai.services.fetching import Fetching, adapter_send
from crawlerai.storage.capture_bundle import HeaderList
from crawlerai.storage.fs import FsStore

PAGE_HOST = "shop.example.test"
GREENHOUSE_BOARD = sorted(BOARD_HOSTS)[0]


class CountingLimiter(HostLimiter):
    """Admits at once, and records each host a request waited for a turn at."""

    def __init__(self) -> None:
        super().__init__()
        self.waits: list[str] = []

    async def wait(self, host: str, interval: timedelta, bound: timedelta = timedelta.max) -> bool:
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


async def _allowed(_url: str, _policy: FetchPolicy) -> tuple[int | None, Robots | None]:
    return None, None


def test_the_first_request_to_the_page_host_takes_the_callers_turn_and_later_ones_wait(tmp_path: Path) -> None:
    sent: list[str] = []
    limiter = CountingLimiter()
    send = adapter_send(_fetching(tmp_path, sent, limiter), PAGE_HOST, _allowed)
    assert send is not None

    async def three() -> None:
        for host in (PAGE_HOST, PAGE_HOST, "cdn.example.test"):
            await send(_request(host), FetchPolicy())

    asyncio.run(three())

    assert len(sent) == 3
    assert limiter.waits == [PAGE_HOST, "cdn.example.test"]


def test_a_request_robots_txt_disallows_is_not_sent_and_is_blocked(tmp_path: Path) -> None:
    sent: list[str] = []

    async def disallowed(_url: str, _policy: FetchPolicy) -> str:
        return "robots"

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

    assert limiter.admit(PAGE_HOST, timedelta(seconds=1)) == timedelta(seconds=20)


def test_a_slow_down_pauses_the_host_no_longer_than_the_longest_backoff(tmp_path: Path) -> None:
    clock = Clock()
    limiter = HostLimiter(clock)

    async def json(request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
        return _answer(request, 503, (("Retry-After", "86400"),))

    fetching = Fetching(Rungs(http=_never, browser=_never, json=json), SafeConnector(), FsStore(tmp_path), limiter)
    send = adapter_send(fetching, PAGE_HOST, _allowed)
    assert send is not None

    async def one() -> FetchResult:
        return await send(_request(PAGE_HOST), FetchPolicy())

    asyncio.run(one())

    assert limiter.admit(PAGE_HOST, timedelta(seconds=1)) == BACKOFF_MAX


def test_a_slow_down_without_a_retry_after_pauses_the_host_by_the_first_backoff(tmp_path: Path) -> None:
    # SPEC-02 §4.6: without a Retry-After, the backoff starts at 30 s.
    limiter = HostLimiter(Clock())

    async def json(request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
        return _answer(request, 429)

    fetching = Fetching(Rungs(http=_never, browser=_never, json=json), SafeConnector(), FsStore(tmp_path), limiter)
    send = adapter_send(fetching, PAGE_HOST, _allowed)
    assert send is not None

    async def one() -> FetchResult:
        return await send(_request(PAGE_HOST), FetchPolicy())

    asyncio.run(one())

    assert limiter.admit(PAGE_HOST, timedelta(seconds=1)) == timedelta(seconds=30)


def test_there_is_no_adapter_send_without_the_json_rung(tmp_path: Path) -> None:
    fetching = Fetching(Rungs(http=_never, browser=_never), SafeConnector(), FsStore(tmp_path), HostLimiter())

    assert adapter_send(fetching, PAGE_HOST, _allowed) is None


def test_every_adapter_runs_unless_the_setting_disables_it(monkeypatch: pytest.MonkeyPatch) -> None:
    every = adapter_registry(AcquireSettings().disabled_adapters)
    monkeypatch.setenv("CRAWLERAI_DISABLED_ADAPTERS", "greenhouse")
    some = adapter_registry(AcquireSettings().disabled_adapters)
    board = f"https://{GREENHOUSE_BOARD}/example-tenant"
    shop_listing = f"https://{PAGE_HOST}/collections/widgets"

    assert [getattr(every.detect(url), "name", None) for url in (board, shop_listing)] == ["greenhouse", "shopify"]
    assert [getattr(some.detect(url), "name", None) for url in (board, shop_listing)] == [None, "shopify"]


def test_an_unknown_or_repeated_adapter_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="no adapter named"):
        adapter_registry(("shopify", "elsewhere"))
    monkeypatch.setenv("CRAWLERAI_DISABLED_ADAPTERS", "shopify,shopify")
    with pytest.raises(ValueError, match="listed twice"):
        AcquireSettings()
