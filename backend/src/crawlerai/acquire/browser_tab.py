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
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Request
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.browser import BrowserSession, Failed, Rendered, classified, read_state, rendered
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import ActionsReport, BlockClass, FetchPolicy, FetchResult, PagedFetch
from crawlerai.core.proxy import ProxyEndpoint, UnknownProxyPool, pool_endpoint

__all__ = ["Click", "Drive", "Ref", "Tab", "fetch_listing"]

# An element of the serialized document: its element-index XPath path (`/*[1]/*[2]`) and its tag.
Ref = tuple[str, str]

# What a click came to: done, refused by something over the element (an overlay) or by the element not becoming
# clickable in time, or the element is no longer in the document.
Click = Literal["clicked", "intercepted", "gone"]

# Playwright's actionability wait for a click (visible, stable, receiving events) ends after this long.
_CLICK_TIMEOUT_MS: Final = 4_000
# A browser action's navigation (to a next page, or back) waits this long for its document.
_NAVIGATION_TIMEOUT_MS: Final = 15_000
# Fetch Standard §2.2.5: requests whose destination is the empty string (fetch() and XMLHttpRequest) or `document`
# carry data or a new document; Playwright names them `fetch`, `xhr` and `document`. Images and fonts are not counted:
# items shown from the DOM still load theirs.
_DATA_REQUESTS: Final = frozenset({"fetch", "xhr", "document"})
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
_AREAS_JS: Final = """(elements) => elements.map(([path, tag]) => {
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

    async def goto(self, url: str) -> bool:
        """Navigate to `url`; whether a document other than an error arrived."""
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


# The driver: what to do with the tab, answering what it did. The caller binds the request's settings to it.
Drive = Callable[[Tab], Awaitable[ActionsReport]]


class _PatchrightTab:
    def __init__(self, page: Rendered, *, url: str, engine_version: str, started: float) -> None:
        self._page = page
        self._url = url
        self._engine_version = engine_version
        self._since = started  # the time the next kept state's attempt is counted from
        self._json_from = 0
        self._requests = 0
        self.kept: list[FetchResult] = []
        page.page.on("request", self._on_request)

    def _on_request(self, request: Request) -> None:
        if request.resource_type in _DATA_REQUESTS:
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

    async def click(self, element: Ref) -> Click:
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
        with contextlib.suppress(PlaywrightError):
            await self._page.page.evaluate(_NEAR_END_JS)
            await asyncio.sleep(_SCROLL_STEP_S)
            await self._page.page.evaluate(_END_JS)

    async def goto(self, url: str) -> bool:
        try:
            response = await self._page.page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)
        except PlaywrightError:
            return False
        return response is not None and response.status < _ERROR_STATUS

    async def back(self) -> None:
        with contextlib.suppress(PlaywrightError):
            await self._page.page.go_back(wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)

    def data_requests(self) -> int:
        return self._requests

    async def keep(self) -> bool:
        fetched_at = datetime.now(UTC)
        try:
            exchange, content = await read_state(self._page, url=self.url, json_from=self._json_from)
        except (Failed, PlaywrightError):
            return False
        block_class = await classified(exchange, content)
        self.kept.append(self._result(fetched_at, exchange, content, block_class))
        self._since = time.monotonic()
        self._json_from = len(self._page.json_responses)
        return True

    def _result(
        self, fetched_at: datetime, exchange: Exchange, content: Content, block_class: BlockClass
    ) -> FetchResult:
        return fetch_result(
            url=self._url,
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
    pools: Mapping[str, ProxyEndpoint] | None = None,
) -> PagedFetch:
    """Render the listing at `url` as `fetch_browser` does and, when it is reached (`ok`), let `drive` act on it; the
    answer holds the document states the driver kept (at least one) and its report. A page not reached is the one
    page, with no report. The navigation is bounded by `policy.browser_timeout_s`; the driver bounds its own actions."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    exchange: Exchange | None = None
    try:
        proxy = pool_endpoint(policy.proxy_pool, pools)
        async with AsyncExitStack() as stack:
            async with asyncio.timeout(policy.browser_timeout_s):
                page = await stack.enter_async_context(
                    rendered(url, policy, session, connector or SafeConnector(), proxy, started, {})
                )
                exchange, content = await read_state(page)
                block_class = await classified(exchange, content)
            if block_class != "ok":
                return _one(url, policy, engine_version, fetched_at, started, exchange, content, block_class, None)
            tab = _PatchrightTab(page, url=url, engine_version=engine_version, started=started)
            report = await _driven(drive, tab)
            if not tab.kept and not await tab.keep():
                return _one(url, policy, engine_version, fetched_at, started, exchange, content, block_class, None)
            return PagedFetch(pages=tuple(tab.kept), report=report.model_copy(update={"pages": len(tab.kept)}))
    except Failed as failed:
        return _failed(url, policy, engine_version, fetched_at, started, failed.error, failed.exchange)
    except UnknownProxyPool as unknown:
        return _failed(url, policy, engine_version, fetched_at, started, str(unknown), None)
    except TimeoutError:
        return _failed(url, policy, engine_version, fetched_at, started, "timeout", exchange)


async def _driven(drive: Drive, tab: _PatchrightTab) -> ActionsReport:
    """The driver's report; a browser failure the tab did not absorb (the page crashed) ends it with `error`, keeping
    what was kept."""
    try:
        return await drive(tab)
    except PlaywrightError:
        return ActionsReport(mechanism=None, stop="error", actions=0, pages=len(tab.kept), items=0)


def _one(
    url: str,
    policy: FetchPolicy,
    engine_version: str,
    fetched_at: datetime,
    started: float,
    exchange: Exchange,
    content: Content,
    block_class: BlockClass,
    error: str | None,
) -> PagedFetch:
    result = fetch_result(
        url=url,
        method="browser",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=exchange,
        content=content,
        block_class=block_class,
        error=error,
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
    return _one(url, policy, engine_version, fetched_at, started, empty, Content(body=b""), "error", error)
