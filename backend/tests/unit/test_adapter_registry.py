"""The adapter registry and the adapter rung: only active adapters answer
(C6), a URL an active adapter detects is fetched by it first, a page it does not serve falls back to the page rungs,
and a host whose answer lacks the platform's signal is declined for a while.

The adapters are stubs that detect one synthetic host; no network.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_PLATFORM, AdapterMatch, Shape
from crawlerai.adapters.registry import DECLINE_FOR, Registry
from tests.support.captures import ScriptedRung

BOARD = "https://board.example.test/tenant"


@dataclass
class StubAdapter:
    """Detects every URL on `host` (any host when it is empty) as a listing; answers with its `rung`."""

    name: str
    host: str
    rung: ScriptedRung = field(default_factory=lambda: ScriptedRung("api", ok_body=b"{}"))

    def detect(self, url: str) -> AdapterMatch | None:
        on_host = not self.host or urlsplit(url).hostname == self.host
        return AdapterMatch(tenant="tenant", page_kind="listing") if on_host else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return urlsplit(endpoint).path.startswith(f"/api/{match.tenant}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        return await self.rung(url, policy)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return ()


async def _send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("the stub adapters answer themselves")


T0 = datetime(2026, 10, 17, tzinfo=UTC)


@dataclass
class Clock:
    now: datetime = T0

    def __call__(self) -> datetime:
        return self.now


def test_an_active_adapter_answers_for_the_urls_it_detects() -> None:
    board = StubAdapter("board", "board.example.test")
    registry = Registry([StubAdapter("other", "other.example.test"), board])

    assert registry.detect(BOARD) is board
    assert registry.detect("https://shop.example.test/item") is None


def test_a_capture_is_read_by_the_adapter_that_detects_its_page_and_serves_its_endpoint() -> None:
    board = StubAdapter("board", "board.example.test")
    registry = Registry([board])

    found = registry.reader(BOARD, "https://board.example.test/api/tenant/list")
    assert found is not None
    assert found[0] is board
    assert registry.reader(BOARD, "https://data.example.test/list") is None
    assert registry.reader(BOARD, "https://board.example.test/api/other/list") is None
    assert registry.reader("https://shop.example.test/api/x", "https://shop.example.test/api/x") is None


def test_a_host_answering_without_the_platform_signal_is_declined_for_the_window() -> None:
    # One request per host per window, and after the window the host is tried again.
    adapter = StubAdapter("board", "board.example.test", ScriptedRung("api", status=404, reason=NOT_PLATFORM))
    clock = Clock()
    registry = Registry([adapter], clock=clock)

    asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    clock.now = T0 + DECLINE_FOR - timedelta(seconds=1)
    declined = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    clock.now = T0 + DECLINE_FOR + timedelta(seconds=1)
    retried = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))

    assert (declined, retried is not None, len(adapter.rung.calls)) == (None, True, 2)
