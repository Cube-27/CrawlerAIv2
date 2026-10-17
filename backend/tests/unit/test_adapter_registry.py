"""The adapter registry and the adapter rung (SPEC-02 §4.4, §4.9; SPEC-15 §4.2, §4.6): only active adapters answer
(C6), a URL an active adapter detects is fetched by it first, a page it does not serve falls back to the page rungs
(INV-40), and a host whose answer lacks the platform's signal is declined for a while.

The adapters are stubs that detect one synthetic host; no network.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import Content, Exchange, as_error, fetch_result
from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_PLATFORM, NOT_SERVED, Adapter, AdapterMatch, PageRefs, Shape
from crawlerai.adapters.registry import DECLINE_FOR, Registry, platform_adapters
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
    assert set(names) == {
        "greenhouse",
        "lever",
        "shopify",
        "workday",
        "oracle_recruiting",
        "ashby",
        "smartrecruiters",
        "recruitee",
        "workable",
        "rippling",
        "bamboohr",
        "teamtailor",
        "ukg",
        "personio",
        "adp",
    }
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

    async def admit_next(*, after: timedelta = timedelta(0)) -> bool:
        admitted.append(True)
        return True

    result = asyncio.run(acquire(BOARD, FetchPolicy(), "http", rungs, send=_send, admit_next=admit_next))

    assert (result.method, result.block_class, http.calls, admitted) == ("http", "ok", [BOARD], [True])
    assert [(a.method, a.block_class) for a in result.attempts] == [
        ("api", answer.block_class if answer.reason is None else "error"),
        ("http", "ok"),
    ]


def _admit(answer: bool, asked: list[bool]) -> Admit:
    async def admit_next(*, after: timedelta = timedelta(0)) -> bool:
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
    clock.now = T0 + DECLINE_FOR - timedelta(seconds=1)
    declined = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    clock.now = T0 + DECLINE_FOR + timedelta(seconds=1)
    retried = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))

    assert (declined, retried is not None, len(adapter.rung.calls)) == (None, True, 2)


def test_a_decline_is_read_back_from_what_the_site_row_stored() -> None:
    # D-1384: the window holds across registries, so across processes, through `site.adapter_declined`.
    adapter = StubAdapter("board", "board.example.test", Rung("api", status=404, reason=NOT_PLATFORM))
    clock = Clock()
    base = Registry([adapter], active={"board"}, clock=clock)
    first = base.for_host("board.example.test", {})
    asyncio.run(first.serve(BOARD, FetchPolicy(), _send))
    stored = first.declined_for("board.example.test")

    clock.now = T0 + timedelta(hours=1)
    within = base.for_host("board.example.test", stored).would_serve(BOARD)
    clock.now = T0 + DECLINE_FOR + timedelta(seconds=1)
    expired = base.for_host("board.example.test", stored)

    assert stored == {"board": (T0 + DECLINE_FOR).isoformat()}
    assert within is False
    assert expired.would_serve(BOARD) is True
    assert expired.declined_for("board.example.test") == {}  # a decline that ran out is not stored again
    assert base.would_serve(BOARD) is True  # the process's registry keeps none of a fetch's declines


def test_an_answer_the_platform_gives_for_another_page_declines_no_host() -> None:
    adapter = StubAdapter("board", "board.example.test", Rung("api", reason=NOT_SERVED))
    registry = Registry([adapter], active={"board"})

    asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))
    again = asyncio.run(registry.serve(BOARD, FetchPolicy(), _send))

    assert (again is not None, len(adapter.rung.calls)) == (True, 2)


SHOP_LIST = "https://shop.example.test/list"


@dataclass
class ListAdapter(StubAdapter):
    """Detects `SHOP_LIST` only, without a query: the adapter routes a query changes the meaning of."""

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="tenant", page_kind="listing") if url == SHOP_LIST else None


@dataclass
class PageRung:
    """Answers every URL over HTTP with `html`."""

    html: str
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        return fetch_result(
            url=url,
            method="http",
            policy=policy,
            engine_version="test",
            fetched_at=datetime.now(UTC),
            started=time.monotonic(),
            exchange=Exchange(
                url=url, status=200, request_headers=(), response_headers=(("Content-Type", "text/html"),)
            ),
            content=Content(body=self.html.encode()),
            block_class="ok",
            error=None,
        )


def _canonical(href: str, base: str = "") -> str:
    base_element = f'<base href="{base}">' if base else ""
    return f'<html><head>{base_element}<link rel="canonical" href="{href}"></head><body>Items</body></html>'


def _by_canonical(page: PageRung, adapter: StubAdapter, asked: list[bool], url: str) -> FetchResult:
    rungs = Rungs(http=page, browser=Rung("browser"), adapters=Registry([adapter], active={adapter.name}))
    return asyncio.run(acquire(url, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(True, asked)))


@pytest.mark.parametrize(
    "html", [_canonical(SHOP_LIST), _canonical("/list"), _canonical("list", base="https://shop.example.test/")]
)
def test_a_page_whose_canonical_drops_only_its_query_is_served_by_the_adapter_of_the_canonical(html: str) -> None:
    # RFC 6596, HTML Standard §4.6.7.3: the page names the URL without its query as its own; the parameters it drops
    # do not identify the page. The adapter's answer is recorded under that URL, on the page's next turn.
    adapter, page, asked = ListAdapter("list", ""), PageRung(html), list[bool]()

    result = _by_canonical(page, adapter, asked, f"{SHOP_LIST}?from=newsletter")

    assert (result.method, result.bundle.manifest.url, adapter.rung.calls, asked) == (
        "api",
        SHOP_LIST,
        [SHOP_LIST],
        [True],
    )
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "ok")]


@pytest.mark.parametrize(
    "html",
    [
        _canonical(f"{SHOP_LIST}?page=2"),  # the query identifies the page
        _canonical("https://other.example.test/list"),  # another origin
        _canonical("http://shop.example.test/list"),
        _canonical("https://shop.example.test/other"),
        "<html><body>No canonical</body></html>",
    ],
)
def test_a_page_whose_canonical_is_not_its_url_without_the_query_is_kept(html: str) -> None:
    adapter, page, asked = ListAdapter("list", ""), PageRung(html), list[bool]()
    url = f"{SHOP_LIST}?page=2"

    result = _by_canonical(page, adapter, asked, url)

    assert (result.method, result.bundle.manifest.url, adapter.rung.calls, asked) == ("http", url, [], [])


def test_a_canonical_the_adapter_does_not_serve_keeps_the_page_and_lists_both_attempts() -> None:
    adapter = ListAdapter("list", "", Rung("api", reason=NOT_SERVED))
    page, asked = PageRung(_canonical(SHOP_LIST)), list[bool]()
    url = f"{SHOP_LIST}?from=newsletter"

    result = _by_canonical(page, adapter, asked, url)

    assert (result.method, result.bundle.manifest.url, asked) == ("http", url, [True])
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "error")]


def test_a_canonical_request_the_site_rate_refuses_is_not_sent() -> None:
    adapter, page, asked = ListAdapter("list", ""), PageRung(_canonical(SHOP_LIST)), list[bool]()
    rungs = Rungs(http=page, browser=Rung("browser"), adapters=Registry([adapter], active={"list"}))
    url = f"{SHOP_LIST}?from=newsletter"

    result = asyncio.run(acquire(url, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(False, asked)))

    assert (result.method, adapter.rung.calls, asked) == ("http", [], [False])


def test_a_canonical_of_a_host_its_adapter_declined_takes_no_turn() -> None:
    # INV-40: the declined host is not asked again, so no turn at the site's rate is spent on it.
    adapter = ListAdapter("list", "", Rung("api", status=404, block_class="not_found", reason=NOT_PLATFORM))
    page, asked = PageRung(_canonical(SHOP_LIST)), list[bool]()
    rungs = Rungs(http=page, browser=Rung("browser"), adapters=Registry([adapter], active={"list"}))

    def fetch(url: str) -> FetchResult:
        return asyncio.run(acquire(url, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(True, asked)))

    first, second = fetch(f"{SHOP_LIST}?from=newsletter"), fetch(f"{SHOP_LIST}?from=footer")

    assert (first.method, second.method, adapter.rung.calls, asked) == ("http", "http", [SHOP_LIST], [True])


PLATFORM = "https://platform.example.test/tenant"
CAREERS = "https://careers.example.test/"


@dataclass
class ReferringAdapter(StubAdapter):
    """Detects the pages of `platform.example.test`; refers a page to the first of its links it detects, in the kind it
    asked for (`kinds` records what it was asked)."""

    kinds: list[PageKind | None] = field(default_factory=list)

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="tenant", page_kind="listing") if urlsplit(url).hostname == self.host else None

    def referred(self, refs: PageRefs, kind: PageKind | None, /) -> str | None:
        self.kinds.append(kind)
        return next((link for link in refs.links if self.detect(link) is not None), None)


def _linking(*hrefs: str) -> str:
    return "<html><body>" + "".join(f'<a href="{href}">x</a>' for href in hrefs) + "</body></html>"


def _referred(
    page: PageRung, adapter: StubAdapter, asked: list[bool], kind: PageKind | None = "listing"
) -> FetchResult:
    rungs = Rungs(http=page, browser=Rung("browser"), adapters=Registry([adapter], active={adapter.name}))
    return asyncio.run(
        acquire(CAREERS, FetchPolicy(page_kind=kind), "http", rungs, send=_send, admit_next=_admit(True, asked))
    )


def test_a_page_on_its_own_host_that_an_adapter_refers_to_a_platform_page_is_served_by_it() -> None:
    # SPEC-15 §4.2: the page's own links say which platform page it stands for; the adapter's answer is recorded under
    # that platform page, on the page's next turn.
    adapter, page = ReferringAdapter("platform", "platform.example.test"), PageRung(_linking(PLATFORM))
    asked: list[bool] = []

    result = _referred(page, adapter, asked)

    assert (result.method, result.bundle.manifest.url, adapter.rung.calls, asked) == (
        "api",
        PLATFORM,
        [PLATFORM],
        [True],
    )
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "ok")]
    assert adapter.kinds == ["listing"]


def test_a_page_the_adapter_does_not_refer_stays_the_page() -> None:
    adapter, page = ReferringAdapter("platform", "platform.example.test"), PageRung(_linking("/about"))
    asked: list[bool] = []

    result = _referred(page, adapter, asked)

    assert (result.method, adapter.rung.calls, asked) == ("http", [], [])


def test_an_adapter_without_a_referral_is_never_asked_for_the_pages_references() -> None:
    adapter, page = StubAdapter("platform", "platform.example.test"), PageRung(_linking(PLATFORM))
    asked: list[bool] = []

    result = _referred(page, adapter, asked)

    assert (result.method, adapter.rung.calls, asked) == ("http", [], [])


def test_a_referred_page_the_sites_rate_does_not_admit_stays_the_page() -> None:
    adapter, page = ReferringAdapter("platform", "platform.example.test"), PageRung(_linking(PLATFORM))
    rungs = Rungs(http=page, browser=Rung("browser"), adapters=Registry([adapter], active={"platform"}))

    result = asyncio.run(acquire(CAREERS, FetchPolicy(), "http", rungs, send=_send, admit_next=_admit(False, [])))

    assert (result.method, adapter.rung.calls) == ("http", [])


def test_a_referred_answer_that_is_not_ok_leaves_the_page_with_both_attempts() -> None:
    answer = Rung("api", status=404, block_class="not_found")
    adapter = ReferringAdapter("platform", "platform.example.test", answer)
    page, asked = PageRung(_linking(PLATFORM)), list[bool]()

    result = _referred(page, adapter, asked)

    assert result.method == "http"
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "not_found")]


async def _lacks_rows(result: FetchResult) -> bool:
    """A `needs_render` check: the HTTP page lacks what the caller reads, the render holds it (owner #54)."""
    return result.method == "http"


def _rendered_or_referred(adapter: ReferringAdapter, browser: Rung) -> FetchResult:
    page = PageRung(_linking(PLATFORM))
    rungs = Rungs(http=page, browser=browser, adapters=Registry([adapter], active={adapter.name}))
    policy = FetchPolicy(page_kind="listing")
    fetch = acquire(CAREERS, policy, "http", rungs, send=_send, admit_next=_admit(True, []), needs_render=_lacks_rows)
    return asyncio.run(fetch)


def test_a_page_lacking_rows_is_referred_before_it_is_rendered() -> None:
    # D-1388: the referral serves the page, so the render it would have needed is never paid for.
    adapter, browser = ReferringAdapter("platform", "platform.example.test"), Rung("browser")

    result = _rendered_or_referred(adapter, browser)

    assert (result.method, result.bundle.manifest.url, browser.calls) == ("api", PLATFORM, [])
    assert [(a.method, a.block_class) for a in result.attempts] == [("http", "ok"), ("api", "ok")]


def test_a_referral_that_does_not_serve_leaves_the_render_and_is_not_asked_again() -> None:
    answer = Rung("api", status=404, block_class="not_found")
    adapter, browser = ReferringAdapter("platform", "platform.example.test", answer), Rung("browser")

    result = _rendered_or_referred(adapter, browser)

    assert (result.method, adapter.rung.calls, browser.calls) == ("browser", [PLATFORM], [CAREERS])
    assert [a.method for a in result.attempts] == ["http", "api", "browser"]


def test_a_host_the_adapter_declined_is_not_referred_to() -> None:
    adapter = ReferringAdapter("platform", "platform.example.test", Rung("api", status=404, reason=NOT_PLATFORM))
    registry = Registry([adapter], active={"platform"})
    asyncio.run(registry.serve(PLATFORM, FetchPolicy(), _send))

    assert registry.referred(lambda: PageRefs(own=(), links=(PLATFORM,)), "listing") is None
