"""The adapter registry and the adapter rung (SPEC-02 §4.4, §4.9): only active adapters answer (C6), and a URL an
active adapter detects is fetched by it alone.

The adapters are stubs that detect one synthetic host; no network.
"""

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import Adapter, AdapterMatch
from crawlerai.adapters.registry import Registry, platform_adapters
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import PageKind

BOARD = "https://board.example.test/tenant"


@dataclass
class Rung:
    """Answers every URL `ok` with `method`, and records the URLs it got."""

    method: CaptureMethod
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        return fetch_result(
            url=url,
            method=self.method,
            policy=policy,
            engine_version="test",
            fetched_at=datetime.now(UTC),
            started=time.monotonic(),
            exchange=Exchange(url=url, status=200, request_headers=(), response_headers=()),
            content=Content(body=b"{}"),
            block_class="ok",
            error=None,
        )


@dataclass
class StubAdapter:
    """Detects every URL on `host` as a listing; fetches with an `api` stub rung."""

    name: str
    host: str
    rung: Rung = field(default_factory=lambda: Rung("api"))

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="tenant", page_kind="listing") if urlsplit(url).hostname == self.host else None

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        return await self.rung(url, policy)

    def map(self, schema_org: Mapping[str, str], page_kind: PageKind) -> dict[str, str]:
        return {}


def test_an_active_adapter_answers_for_the_urls_it_detects() -> None:
    board = StubAdapter("board", "board.example.test")
    registry = Registry([StubAdapter("other", "other.example.test"), board], active={"other", "board"})

    assert registry.detect(BOARD) is board
    assert registry.detect("https://shop.example.test/item") is None


def test_an_inactive_adapter_never_answers() -> None:
    registry = Registry([StubAdapter("board", "board.example.test")], active=())

    assert registry.detect(BOARD) is None


def test_an_unknown_active_name_is_refused() -> None:
    adapters = [StubAdapter("board", "board.example.test")]
    with pytest.raises(ValueError, match="no adapter named"):
        Registry(adapters, active={"missing"})


def test_two_adapters_with_one_name_are_refused() -> None:
    adapters = [StubAdapter("board", "board.example.test"), StubAdapter("board", "other.example.test")]
    with pytest.raises(ValueError, match="repeat"):
        Registry(adapters, active=())


def test_every_platform_adapter_has_its_own_name() -> None:
    async def no_fetch(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
        raise AssertionError("not called")

    adapters: tuple[Adapter, ...] = platform_adapters(no_fetch)

    names = [adapter.name for adapter in adapters]
    assert {"greenhouse", "lever"} <= set(names)
    Registry(adapters, active=names)  # refuses repeated names


def test_a_detected_url_is_fetched_by_its_adapter_and_no_other_rung() -> None:
    adapter = StubAdapter("board", "board.example.test")
    http, browser = Rung("http"), Rung("browser")
    rungs = Rungs(http=http, browser=browser, adapters=Registry([adapter], active={"board"}))

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs))

    assert [(a.method, a.block_class) for a in result.attempts] == [("api", "ok")]
    assert adapter.rung.calls == [BOARD]
    assert (http.calls, browser.calls) == ([], [])


def test_an_undetected_url_takes_the_http_rung() -> None:
    adapter = StubAdapter("board", "board.example.test")
    http = Rung("http")
    rungs = Rungs(http=http, browser=Rung("browser"), adapters=Registry([adapter], active={"board"}))

    result = asyncio.run(acquire("https://shop.example.test/item", FetchPolicy(), "http", rungs))

    assert result.method == "http"
    assert (http.calls, adapter.rung.calls) == (["https://shop.example.test/item"], [])
