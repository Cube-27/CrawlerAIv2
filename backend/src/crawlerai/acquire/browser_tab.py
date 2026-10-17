"""A listing's browser actions on the browser rung (owner #52, ARCHITECTURE §7.1): the rendered page as a `Tab` that a
paging driver reads and acts on, and the document states it keeps, each a fetch result of its own.

The page is opened, navigated and settled exactly as `fetch_browser` does it (`browser.rendered`), so the launch, the
context and the identity the page sees are the same (INV-42 to INV-44). Everything the tab reads or does runs in
Patchright's isolated world, which shares the document but not the page's globals, and it writes nothing into the
page's DOM: elements are named by element-index XPath paths into the serialized document (`/*[1]/*[2]`), which the
driver computes from its own parse. Nothing is typed and no form is filled; a click is a pointer click on an element
the driver chose, and one an overlay intercepts is reported, not worked around.

What to do is the driver's (`crawl.paging`, above `acquire` in the layering): `fetch_listing` hands it the tab.
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Request
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.browser import (
    DATA_REQUESTS,
    BrowserSession,
    Failed,
    Rendered,
    challenge_of,
    classified,
    context_cookies,
    json_bodies,
    read_state,
    rendered,
)
from crawlerai.acquire.challenge import count
from crawlerai.acquire.outcome import Content, Exchange, Traffic, fetch_result, report_proxy
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import ActionsReport, BlockClass, FetchPolicy, FetchResult, PagedFetch
from crawlerai.core.proxy import ProxyEndpoint, ProxyPool, UnknownProxyPool, pool_endpoint, proxy_pool
from crawlerai.storage.capture_bundle import NetworkBody

__all__ = ["Click", "Drive", "ListingRung", "Ref", "Tab", "fetch_listing"]

# An element of the serialized document: its element-index XPath path (`/*[1]/*[2]`) and its tag.
Ref = tuple[str, str]

# What a click came to: done, refused by something over the element (an overlay) or by the element not becoming
# clickable in time, or the element is no longer in the document.
Click = Literal["clicked", "intercepted", "gone"]

# Playwright's actionability wait for a click (visible, stable, receiving events) ends after this long.
_CLICK_TIMEOUT_MS: Final = 4_000
# A browser action's navigation (to a next page, or back) waits this long for its document.
_NAVIGATION_TIMEOUT_MS: Final = 15_000
# HTML Standard §8.1.6 (navigation), RFC 9110 §15.5: a document answered 4xx or 5xx is no next page.
_ERROR_STATUS: Final = 400
# The element an element-index XPath path names (DOM Standard `document.evaluate`, XPath 1.0), when it has the tag the
# driver read there, else null: libxml2 may build a serialized document's tree differently from the browser.
_ELEMENT_JS: Final = """([path, tag]) => {
  const node = document.evaluate(path, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  return node !== null && node.nodeType === Node.ELEMENT_NODE && node.localName === tag ? node : null;
}"""
# The rendered area of each named element in CSS pixels (CSSOM View `getBoundingClientRect`); 0 when the path names no
# element of that tag or the element is not rendered visible (CSS 2.1 §11.2 `visibility`, `display: none` has no box).
_AREAS_JS: Final = """(elements) => Array.from(elements, ([path, tag]) => {
  const node = document.evaluate(path, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  if (node === null || node.nodeType !== Node.ELEMENT_NODE || node.localName !== tag) return 0;
  if (getComputedStyle(node).visibility !== 'visible') return 0;
  const box = node.getBoundingClientRect();
  return box.width * box.height;
})"""
# How many changes to the document's structure and text there have been (DOM Standard §4.3, a MutationObserver on
# `childList` and `characterData`), counted from the first call in each document.
_MUTATIONS_JS: Final = """() => {
  if (globalThis.__mutations === undefined) {
    globalThis.__mutations = 0;
    new MutationObserver((records) => { globalThis.__mutations += records.length; })
      .observe(document, {subtree: true, childList: true, characterData: true});
  }
  return globalThis.__mutations;
}"""
# CSSOM View `scrollTo`: first to a viewport and a half above the end, then to the end, so that content which loads
# when a sentinel near the end enters the viewport sees it enter.
_NEAR_END_JS: Final = (
    "() => window.scrollTo(0, Math.max(0, document.scrollingElement.scrollHeight - 1.5 * innerHeight))"
)
_END_JS: Final = "() => window.scrollTo(0, document.scrollingElement.scrollHeight)"
_SCROLL_STEP_S: Final = 0.2


class Tab(Protocol):
    """The rendered page as the paging driver sees it."""

    @property
    def url(self) -> str:
        """The URL of the document the page shows now."""
        ...

    async def html(self) -> str | None:
        """The document serialized as it is now; None while it is being replaced."""
        ...

    async def mutations(self) -> int | None:
        """The changes to the document's structure and text so far (another document counts afresh); None while the
        document is being replaced."""
        ...

    async def areas(self, elements: Sequence[Ref]) -> list[float]:
        """The rendered area of each element; 0 for one not found or not rendered visible."""
        ...

    async def click(self, element: Ref) -> Click: ...

    async def scroll(self) -> None:
        """Scroll the document to its end."""
        ...

    async def goto(self, url: str, timeout_s: float) -> bool:
        """Navigate to `url`, waiting at most `timeout_s` (and the tab's own navigation cap); whether a document other
        than an error arrived."""
        ...

    async def back(self) -> None:
        """Go back to the previous document, after a click that left it."""
        ...

    def data_requests(self) -> int:
        """How many fetch, XMLHttpRequest and document requests the page has sent so far."""
        ...

    async def keep(self) -> bool:
        """Keep the document as it is now as a capture of its own; False when it could not be read within the caps."""
        ...

    async def discard(self) -> None:
        """Drop the state kept last, which a later one holds whole: its data responses go to the next state kept."""
        ...

    async def calls(self) -> tuple[tuple[NetworkBody, bytes], ...]:
        """The JSON bodies of the data responses since the state kept last, as a kept state would hold them."""
        ...


# The driver: what to do with the tab, answering what it did. The caller binds the request's settings to it.
Drive = Callable[[Tab], Awaitable[ActionsReport]]
# `fetch_listing` bound to a process's browser, guard and proxy pools: a listing's URL, its policy and the driver.
ListingRung = Callable[[str, FetchPolicy, Drive], Awaitable[PagedFetch]]


class _PatchrightTab:
    def __init__(self, page: Rendered, *, url: str, engine_version: str, started: float) -> None:
        self._page = page
        self._url = url  # the URL the shown document was asked for; `_at` is where that navigation ended
        self._at = page.page.url
        self._engine_version = engine_version
        self._since = started  # the time the next kept state's attempt is counted from
        self._calls_from = 0
        self._requests = 0
        self.kept: list[FetchResult] = []
        # Each kept state's start: the time its attempt is counted from and its first data response, for `discard`.
        self._starts: list[tuple[float, int]] = []
        self._bodies: dict[int, tuple[NetworkBody, bytes] | None] = {}  # the data responses read so far, by index
        page.page.on("request", self._on_request)

    def _on_request(self, request: Request) -> None:
        # Images and fonts are not counted (`DATA_REQUESTS`): items shown from the DOM still load theirs.
        if request.resource_type in DATA_REQUESTS:
            self._requests += 1

    @property
    def url(self) -> str:
        return self._page.page.url

    async def html(self) -> str | None:
        try:
            return await self._page.page.content()
        except PlaywrightError:
            return None

    async def mutations(self) -> int | None:
        try:
            return cast(int, await self._page.page.evaluate(_MUTATIONS_JS))
        except PlaywrightError:
            return None

    async def areas(self, elements: Sequence[Ref]) -> list[float]:
        try:
            return cast(list[float], await self._page.page.evaluate(_AREAS_JS, [list(e) for e in elements]))
        except PlaywrightError:
            return [0.0] * len(elements)

    def _act(self) -> None:
        """Count a browser action: the data responses that arrive from now on followed it (`NetworkBody.action`)."""
        self._page.calls.actions += 1

    async def click(self, element: Ref) -> Click:
        self._act()
        try:
            handle = await self._page.page.evaluate_handle(_ELEMENT_JS, list(element))
        except PlaywrightError:
            return "gone"
        found = handle.as_element()
        try:
            if found is None:
                return "gone"
            await found.click(timeout=_CLICK_TIMEOUT_MS)
            return "clicked"
        except PlaywrightTimeout:
            return "intercepted"
        except PlaywrightError:
            return "gone"
        finally:
            with contextlib.suppress(PlaywrightError):
                await handle.dispose()

    async def scroll(self) -> None:
        self._act()
        with contextlib.suppress(PlaywrightError):
            await self._page.page.evaluate(_NEAR_END_JS)
            await asyncio.sleep(_SCROLL_STEP_S)
            await self._page.page.evaluate(_END_JS)

    async def goto(self, url: str, timeout_s: float) -> bool:
        timeout_ms = max(1.0, min(_NAVIGATION_TIMEOUT_MS, 1000 * timeout_s))  # 0 would mean no timeout
        self._act()
        try:
            response = await self._page.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightError:
            return False
        finally:
            self._url, self._at = url, self._page.page.url
        return response is not None and response.status < _ERROR_STATUS

    async def back(self) -> None:
        self._act()
        with contextlib.suppress(PlaywrightError):
            await self._page.page.go_back(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)

    def data_requests(self) -> int:
        return self._requests

    async def keep(self) -> bool:
        fetched_at = datetime.now(UTC)
        # The data responses up to now belong to this state; one arriving while it is read goes to the next.
        calls_to = len(self._page.calls.responses)
        try:
            exchange, content = await read_state(self._page, url=self.url, calls=(self._calls_from, calls_to))
        except (Failed, PlaywrightError):
            return False
        block_class = await classified(exchange, content)
        self.kept.append(self._result(fetched_at, exchange, content, block_class))
        self._starts.append((self._since, self._calls_from))
        self._since = time.monotonic()
        self._calls_from = calls_to
        return True

    async def discard(self) -> None:
        if self.kept:
            self.kept.pop()
            self._since, self._calls_from = self._starts.pop()

    async def calls(self) -> tuple[tuple[NetworkBody, bytes], ...]:
        responses = self._page.calls.responses
        # A body before the start of the state kept last is never asked for again (`discard` goes back one state).
        floor = self._starts[-1][1] if self._starts else 0
        for index in [index for index in self._bodies if index < floor]:
            del self._bodies[index]
        for index in range(self._calls_from, len(responses)):
            if index not in self._bodies:
                self._bodies[index] = next(iter(await json_bodies([responses[index]])), None)
        found = (self._bodies[index] for index in range(self._calls_from, len(responses)))
        return tuple(body for body in found if body is not None)

    def _result(
        self, fetched_at: datetime, exchange: Exchange, content: Content, block_class: BlockClass
    ) -> FetchResult:
        # A document a click or a script navigated to was asked for under its own URL.
        return fetch_result(
            url=self._url if self.url == self._at else self.url,
            method="browser",
            policy=self._page.policy,
            engine_version=self._engine_version,
            fetched_at=fetched_at,
            started=self._since,
            exchange=exchange,
            content=content,
            block_class=block_class,
            error=None,
        )


async def fetch_listing(
    url: str,
    policy: FetchPolicy,
    drive: Drive,
    *,
    session: BrowserSession,
    engine_version: str,
    connector: SafeConnector | None = None,
    pools: Mapping[str, ProxyPool] | None = None,
) -> PagedFetch:
    """Render the listing at `url` as `fetch_browser` does and, when it is reached (`ok`), let `drive` act on it; the
    answer holds the document states the driver kept (at least one) and its report. A page not reached is the one
    page, with no report, labelled with the challenge it presents. The navigation is bounded by
    `policy.browser_timeout_s`; the driver bounds its own actions. The pool endpoint is told how the navigation went,
    and the navigation's attempt (the first page's) carries the bytes the whole run moved (`Traffic`)."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    try:
        pool = proxy_pool(policy.proxy_pool, pools)
    except UnknownProxyPool as unknown:
        return _failed(url, policy, engine_version, fetched_at, started, str(unknown), None)
    proxy = pool_endpoint(pool, url)
    traffic = Traffic()
    paged = await _listing(url, policy, drive, session, engine_version, connector or SafeConnector(), proxy, traffic)
    first = paged.pages[0]
    navigation = first.attempts[0].model_copy(update={"transferred": traffic.bytes})
    carried = first.model_copy(update={"attempts": (navigation, *first.attempts[1:])})
    report_proxy(pool, proxy, carried)
    return paged.model_copy(update={"pages": (carried, *paged.pages[1:])})


async def _listing(
    url: str,
    policy: FetchPolicy,
    drive: Drive,
    session: BrowserSession,
    engine_version: str,
    connector: SafeConnector,
    proxy: ProxyEndpoint | None,
    traffic: Traffic,
) -> PagedFetch:
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    exchange: Exchange | None = None
    try:
        async with AsyncExitStack() as stack:
            async with asyncio.timeout(policy.browser_timeout_s):
                page = await stack.enter_async_context(
                    rendered(url, policy, session, connector, proxy, started, {}, traffic)
                )
                exchange, content = await read_state(page)
                block_class = await classified(exchange, content)
            if block_class != "ok":
                cookies = await context_cookies(page.page.context)
                challenge = await challenge_of(block_class, exchange, content, url, cookies)
                count(challenge, "browser")
                one = _Outcome(exchange, content, block_class, None, challenge)
                return _one(url, policy, engine_version, fetched_at, started, one)
            tab = _PatchrightTab(page, url=url, engine_version=engine_version, started=started)
            report = await _driven(drive, tab)
            if not tab.kept and not await tab.keep():
                return _one(url, policy, engine_version, fetched_at, started, _Outcome(exchange, content, block_class))
            return PagedFetch(pages=tuple(tab.kept), report=report.model_copy(update={"pages": len(tab.kept)}))
    except Failed as failed:
        return _failed(url, policy, engine_version, fetched_at, started, failed.error, failed.exchange)
    except TimeoutError:
        return _failed(url, policy, engine_version, fetched_at, started, "timeout", exchange)


async def _driven(drive: Drive, tab: _PatchrightTab) -> ActionsReport:
    """The driver's report; a browser failure the tab did not absorb (the page crashed) ends it with `error`, keeping
    what was kept."""
    try:
        return await drive(tab)
    except PlaywrightError:
        return ActionsReport(mechanism=None, stop="error", actions=0, pages=len(tab.kept), items=0)


@dataclass(frozen=True)
class _Outcome:
    exchange: Exchange
    content: Content
    block_class: BlockClass
    error: str | None = None
    challenge: str | None = None


def _one(
    url: str, policy: FetchPolicy, engine_version: str, fetched_at: datetime, started: float, outcome: _Outcome
) -> PagedFetch:
    result = fetch_result(
        url=url,
        method="browser",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=outcome.exchange,
        content=outcome.content,
        block_class=outcome.block_class,
        error=outcome.error,
        challenge=outcome.challenge,
    )
    return PagedFetch(pages=(result,), report=None)


def _failed(
    url: str,
    policy: FetchPolicy,
    engine_version: str,
    fetched_at: datetime,
    started: float,
    error: str,
    exchange: Exchange | None,
) -> PagedFetch:
    empty = exchange or Exchange(url=url, status=0, request_headers=(), response_headers=())
    return _one(url, policy, engine_version, fetched_at, started, _Outcome(empty, Content(body=b""), "error", error))
