"""The adapter registry and the adapter rung (SPEC-02 §4.4, §4.9; SPEC-15 §4.2, §4.6): only active adapters answer
(C6), a URL an active adapter detects is fetched by it first, a page it does not serve falls back to the page rungs
(INV-40), and a host whose answer lacks the platform's signal is declined for a while.

The adapters are stubs that detect one synthetic host; no network.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import pytest

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import Content, Exchange, as_error, fetch_result
from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_PLATFORM, NOT_SERVED, Adapter, AdapterMatch, Shape
from crawlerai.adapters.registry import DECLINE_SECONDS, MAX_DECLINED, Registry, platform_adapters
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import PageKind

BOARD = "https://board.example.test/tenant"


def _result(url: str, method: CaptureMethod, status: int, block_class: BlockClass) -> FetchResult:
    return fetch_result(
        url=url,
        method=method,
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url=url, status=status, request_headers=(), response_headers=()),
        content=Content(body=b"{}" if block_class == "ok" else b""),
        block_class=block_class,
        error=None,
    )


@dataclass
class Rung:
    """Answers every URL with `status` and `block_class` by `method`, and records the URLs it got."""

    method: CaptureMethod
    status: int = 200
    block_class: BlockClass = "ok"
    reason: str | None = None  # an adapter answer that does not serve the page (`as_error`)
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        result = _result(url, self.method, self.status, self.block_class)
        return result if self.reason is None else as_error(result, self.reason)


@dataclass
class StubAdapter:
    """Detects every URL on `host` (any host when it is empty) as a listing; answers with its `rung`."""

    name: str
    host: str
    rung: Rung = field(default_factory=lambda: Rung("api"))

    def detect(self, url: str) -> AdapterMatch | None:
        on_host = not self.host or urlsplit(url).hostname == self.host
        return AdapterMatch(tenant="tenant", page_kind="listing") if on_host else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return urlsplit(endpoint).path.startswith(f"/api/{match.tenant}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        return await self.rung(url, policy)

    def shapes(self, page_kind: PageKind) -> tuple[Shape, ...]:
        return ()


async def _send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("the stub adapters answer themselves")


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def test_an_active_adapter_answers_for_the_urls_it_detects() -> None:
    board = StubAdapter("board", "board.example.test")
    registry = Registry([StubAdapter("other", "other.example.test"), board], active={"other", "board"})

    assert registry.detect(BOARD) is board
    assert registry.detect("https://shop.example.test/item") is None


def test_an_inactive_adapter_never_answers() -> None:
    board = StubAdapter("board", "board.example.test")

    assert Registry([board], active=()).detect(BOARD) is None
    assert Registry([board], active={"board"}).detect(BOARD) is board


def test_an_unknown_active_name_is_refused() -> None:
    adapters = [StubAdapter("board", "board.example.test")]
    with pytest.raises(ValueError, match="no adapter named"):
        Registry(adapters, active={"missing"})


def test_two_adapters_with_one_name_are_refused() -> None:
    adapters = [StubAdapter("board", "board.example.test"), StubAdapter("board", "other.example.test")]
    with pytest.raises(ValueError, match="repeat"):
        Registry(adapters, active=())


def test_every_platform_adapter_has_its_own_name() -> None:
    adapters: tuple[Adapter, ...] = platform_adapters()

    names = [adapter.name for adapter in adapters]
    assert set(names) == {"greenhouse", "lever", "shopify"}
    Registry(adapters, active=names)  # refuses repeated names


def test_a_capture_is_read_by_the_adapter_that_detects_its_page_and_serves_its_endpoint() -> None:
    # INV-39.
    board = StubAdapter("board", "board.example.test")
    registry = Registry([board], active={"board"})

    found = registry.reader(BOARD, "https://board.example.test/api/tenant/list")
    assert found is not None
    assert found[0] is board
    assert registry.reader(BOARD, "https://data.example.test/list") is None
    assert registry.reader(BOARD, "https://board.example.test/api/other/list") is None
    assert registry.reader("https://shop.example.test/api/x", "https://shop.example.test/api/x") is None


def test_a_detected_url_served_by_its_adapter_takes_no_other_rung() -> None:
    adapter = StubAdapter("board", "board.example.test")
    http, browser = Rung("http"), Rung("browser")
    rungs = Rungs(http=http, browser=browser, adapters=Registry([adapter], active={"board"}))

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs, send=_send))

    assert [(a.method, a.block_class) for a in result.attempts] == [("api", "ok")]
    assert adapter.rung.calls == [BOARD]
    assert (http.calls, browser.calls) == ([], [])


def test_no_adapter_runs_without_a_json_fetch() -> None:
    adapter = StubAdapter("board", "board.example.test")
    http = Rung("http")
    rungs = Rungs(http=http, browser=Rung("browser"), adapters=Registry([adapter], active={"board"}))

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs))

    assert result.method == "http"
    assert (http.calls, adapter.rung.calls) == ([BOARD], [])


@pytest.mark.parametrize(
    "answer",
    [
        Rung("api", status=404, block_class="not_found"),
        Rung("api", status=200, reason=NOT_SERVED),
        Rung("api", status=404, block_class="not_found", reason=NOT_PLATFORM),
    ],
)
def test_a_page_its_adapter_does_not_serve_is_fetched_by_the_page_rungs(answer: Rung) -> None:
    # INV-40: the fallback goes after its own turn at the site's rate, and the result lists both attempts.
    adapter = StubAdapter("board", "board.example.test", answer)
    http = Rung("http")
    rungs = Rungs(http=http, browser=Rung("browser"), adapters=Registry([adapter], active={"board"}))
    admitted: list[bool] = []

    async def admit_next() -> bool:
        admitted.append(True)
        return True

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs, send=_send, admit_next=admit_next))

    assert (result.method, result.block_class, http.calls, admitted) == ("http", "ok", [BOARD], [True])
    assert [(a.method, a.block_class) for a in result.attempts] == [
        ("api", answer.block_class if answer.reason is None else "error"),
        ("http", "ok"),
    ]


def _admit(answer: bool, asked: list[bool]) -> Admit:
    async def admit_next() -> bool:
        asked.append(answer)
        return answer

    return admit_next


@pytest.mark.parametrize("status", [429, 503])
def test_an_adapter_answer_asking_for_fewer_requests_falls_back_to_the_page_on_its_turn(status: int) -> None:
    # The endpoint asked for fewer requests; the page is a request of its own, sent when the site's rate (which holds
    # the pause the endpoint asked for) admits it.
    adapter = StubAdapter("board", "board.example.test", Rung("api", status=status, block_class="blocked"))
    http = Rung("http")
    rungs = Rungs(http=http, browser=Rung("browser"), adapters=Registry([adapter], active={"board"}))
    asked: list[bool] = []

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(True, asked)))

    assert (result.method, result.block_class, http.calls, asked) == ("http", "ok", [BOARD], [True])
    assert [(a.method, a.status) for a in result.attempts] == [("api", status), ("http", 200)]


def test_an_adapter_answer_asking_for_fewer_requests_is_kept_when_the_page_is_not_admitted() -> None:
    adapter = StubAdapter("board", "board.example.test", Rung("api", status=429, block_class="blocked"))
    http = Rung("http")
    rungs = Rungs(http=http, browser=Rung("browser"), adapters=Registry([adapter], active={"board"}))
    asked: list[bool] = []

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(False, asked)))

    assert (result.method, result.block_class, http.calls, asked) == ("api", "blocked", [], [False])


def test_a_host_answering_without_the_platform_signal_is_declined_for_the_window() -> None:
    # INV-40: one request per host per window, and after the window the host is tried again.
    adapter = StubAdapter("board", "board.example.test", Rung("api", status=404, reason=NOT_PLATFORM))
    clock = Clock()
    registry = Registry([adapter], active={"board"}, clock=clock)

    asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    clock.now = DECLINE_SECONDS - 1
    declined = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    clock.now = DECLINE_SECONDS + 1
    retried = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))

    assert (declined, retried is not None, len(adapter.rung.calls)) == (None, True, 2)


def test_an_answer_the_platform_gives_for_another_page_declines_no_host() -> None:
    adapter = StubAdapter("board", "board.example.test", Rung("api", reason=NOT_SERVED))
    registry = Registry([adapter], active={"board"})

    asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    again = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))

    assert (again is not None, len(adapter.rung.calls)) == (True, 2)


def test_declined_hosts_are_bounded_and_the_oldest_is_forgotten_first() -> None:
    adapter = StubAdapter("board", "", Rung("api", status=404, reason=NOT_PLATFORM))
    registry = Registry([adapter], active={"board"})
    urls = [f"https://h{i}.example.test/" for i in range(MAX_DECLINED + 1)]

    async def serve_all() -> None:
        for url in urls:
            await registry.serve(url, FetchPolicy(), _send)

    asyncio.run(serve_all())

    async def served(url: str) -> bool:
        return await registry.serve(url, FetchPolicy(), _send) is not None

    assert asyncio.run(served(urls[1])) is False
    assert asyncio.run(served(urls[-1])) is False
    assert asyncio.run(served(urls[0])) is True
