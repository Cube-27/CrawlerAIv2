"""A process's browser (acquisition spec, INV-31): one per process, launched when a fetch first needs it and shared by
the fetches after it, at most `BROWSER_CONTEXTS` of them at once (each renders in a context of its own).

A fetch that leaves the browser disconnected (Chromium crashed, or was killed), whether it returns or raises, restarts
it once and fetches again. If the restarted browser dies too, that second fetch's result (or error) stands, so the
crash ends only the fetch that was using the browser, and the next fetch that needs one launches a new one: at most one
restart per fetch. Fetches running at once
share one restart: a fetch restarts the browser only while the dead session it used is still the current one.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from typing import Final

from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.types import FetchPolicy, FetchResult

# Pages one browser renders at once: each context is a renderer process of a few hundred MB, and a page's scripts
# compete for the same cores.
BROWSER_CONTEXTS: Final = 2

# Fetches a page in a session, filling the cookie export when one is given (`acquire.browser.fetch_browser`).
type Fetch[S] = Callable[[S, str, FetchPolicy, CookieExport | None], Awaitable[FetchResult]]


class SharedBrowser[S]:
    """`launch` opens a browser session, `fetch` fetches a page in one, and `alive` says whether a session's browser
    is still connected."""

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
        async with self._contexts:
            session = await self._session()
            try:
                result = await self._fetch(session, url, policy, export)
            except Exception:
                if self._alive(session):
                    raise
            else:
                if self._alive(session):
                    return result
            await self._close(session)
            session = await self._session()
            try:
                return await self._fetch(session, url, policy, export)
            finally:
                if not self._alive(session):
                    await self._close(session)

    async def aclose(self) -> None:
        """End the browser, if one is running."""
        async with self._lock:
            await self._end()

    async def _close(self, session: S) -> None:
        """End the browser if `session` is still the one running (another fetch may have restarted it already)."""
        async with self._lock:
            if self._open is not None and self._open[1] is session:
                await self._end()

    async def _end(self) -> None:
        if self._open is not None:
            stack, _ = self._open
            self._open = None
            await stack.aclose()

    async def _session(self) -> S:
        async with self._lock:
            if self._open is None:
                stack = AsyncExitStack()
                session = await stack.enter_async_context(self._launch())
                self._open = stack, session
            return self._open[1]
