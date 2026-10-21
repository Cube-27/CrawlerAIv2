"""A process's browser session (acquisition spec, INV-31): one per process, launched when a render first needs it and
shared by the renders after it, the page rung's and the listing rung's alike, at most `BROWSER_CONTEXTS` of them at
once (each renders in a site profile of its own, `acquire.browser_session`).

A render that raises with the session disconnected (its Playwright driver died, or was killed) restarts it once and
renders again. If the restarted session dies too, that second render's error stands, so the crash ends only the render
that was using the session, and the next render that needs one launches a new one: at most one restart per render. A
render that returns has done its work (its requests were sent, a listing's actions taken): its result stands even when
the session died after it, and the dead session is closed for the next render to launch a new one. Renders running at
once share one restart: a render restarts the session only while the dead session it used is still the current one.
A site profile's browser that crashes ends only its own page (`browser_session._Profiles`): the session stays connected.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Final

from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.types import FetchPolicy, FetchResult

# Pages one session renders at once: each site profile is a browser of a few hundred MB, and a page's scripts compete
# for the same cores.
BROWSER_CONTEXTS: Final = 2

# Fetches a page in a session, filling the cookie export when one is given (`acquire.browser.fetch_browser`).
type Fetch[S] = Callable[[S, str, FetchPolicy, CookieExport | None], Awaitable[FetchResult]]


class SharedBrowser[S]:
    """`launch` opens a browser session, `fetch` fetches a page in one, and `alive` says whether a session is still
    connected."""

    def __init__(
        self,
        launch: Callable[[], AbstractAsyncContextManager[S]],
        fetch: Fetch[S],
        alive: Callable[[S], bool],
        *,
        contexts: int = BROWSER_CONTEXTS,
    ) -> None:
        self._launch = launch
        self._fetch = fetch
        self._alive = alive
        self._open: tuple[AsyncExitStack, S] | None = None
        self._lock = asyncio.Lock()  # one launch or close at a time
        self._contexts = asyncio.Semaphore(contexts)

    async def fetch(self, url: str, policy: FetchPolicy, *, export: CookieExport | None = None) -> FetchResult:
        """The browser rung (`crawlerai.acquire.rungs.Rungs.browser`), and with `export` its exporting form
        (`Rungs.exporting`)."""
        return await self.render(lambda session: self._fetch(session, url, policy, export))

    async def render[T](self, work: Callable[[S], Awaitable[T]]) -> T:
        """`work` in the shared session, holding one of its `BROWSER_CONTEXTS` slots: a page's fetch (`fetch`), or a
        listing with browser actions (`acquire.browser_tab.fetch_listing`)."""
        async with self._contexts:
            session = await self._session()
            try:
                return await work(session)
            except Exception:
                if self._alive(session):
                    raise
            finally:
                if not self._alive(session):
                    await self._close(session)
            session = await self._session()
            try:
                return await work(session)
            finally:
                if not self._alive(session):
                    await self._close(session)

    async def aclose(self) -> None:
        """End the browser, if one is running."""
        async with self._lock:
            await self._end()

    async def _close(self, session: S) -> None:
        """End the session if `session` is still the one running (another render may have restarted it already)."""
        async with self._lock:
            if self._open is not None and self._open[1] is session:
                await self._end()

    async def _end(self) -> None:
        if self._open is not None:
            stack, _ = self._open
            self._open = None
            await stack.aclose()

    async def _session(self) -> S:
        """The open session, launched first when none is: none is launched until a render needs one."""
        async with self._lock:
            if self._open is None:
                stack = AsyncExitStack()
                self._open = (stack, await stack.enter_async_context(self._launch()))
            return self._open[1]
