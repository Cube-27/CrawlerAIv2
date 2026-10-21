"""A process's browser session (acquisition spec, INV-31): one per process, launched when a fetch first needs it and
shared by the fetches after it, at most `BROWSER_CONTEXTS` of them at once (each renders in a site profile of its own,
`acquire.browser`).

A fetch that leaves the browser disconnected (Chromium crashed, or was killed), whether it returns or raises, restarts
it once and fetches again. If the restarted browser dies too, that second fetch's result (or error) stands, so the
crash ends only the fetch that was using the browser, and the next fetch that needs one launches a new one: at most one
restart per fetch. Fetches running at once
share one restart: a fetch restarts the browser only while the dead session it used is still the current one.

A browser is recycled once worn (owner plan 2026-10-19, P1): after `RECYCLE_CONTEXTS` pages, or `RECYCLE_AGE` after its
launch, the next fetch that finds no other page rendering closes it and launches a fresh one. Chromium's memory grows
with the pages a long-lived browser has rendered; a new process gives it back. A browser in use is never closed for it.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Final

from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.types import FetchPolicy, FetchResult

# Pages one session renders at once: each site profile is a browser of a few hundred MB, and a page's scripts compete
# for the same cores.
BROWSER_CONTEXTS: Final = 2
# When a browser is worn (module docstring): unmeasured starting points.
RECYCLE_CONTEXTS: Final = 200
RECYCLE_AGE: Final = timedelta(minutes=30)

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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._launch = launch
        self._fetch = fetch
        self._alive = alive
        self._clock = clock
        self._open: tuple[AsyncExitStack, S] | None = None
        self._lock = asyncio.Lock()  # one launch or close at a time
        self._contexts = asyncio.Semaphore(contexts)
        self._using = 0  # fetches using the open browser
        self._served = 0  # pages the open browser was given
        self._launched = 0.0  # when it launched, on `clock`

    async def fetch(self, url: str, policy: FetchPolicy, *, export: CookieExport | None = None) -> FetchResult:
        """The browser rung (`crawlerai.acquire.rungs.Rungs.browser`), and with `export` its exporting form
        (`Rungs.exporting`)."""
        async with self._contexts:
            async with self._use() as session:
                try:
                    result = await self._fetch(session, url, policy, export)
                except Exception:
                    if self._alive(session):
                        raise
                else:
                    if self._alive(session):
                        return result
                await self._close(session)
            async with self._use() as session:
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

    @asynccontextmanager
    async def _use(self) -> AsyncIterator[S]:
        """The open browser's session, counted in use while the block runs; a worn browser no fetch uses is replaced
        first, and none is launched until a fetch needs one."""
        async with self._lock:
            if self._open is not None and self._using == 0 and self._worn():
                await self._end()
            if self._open is None:
                stack = AsyncExitStack()
                session = await stack.enter_async_context(self._launch())
                self._open, self._served, self._launched = (stack, session), 0, self._clock()
            self._using += 1
            self._served += 1
            session = self._open[1]
        try:
            yield session
        finally:
            self._using -= 1

    def _worn(self) -> bool:
        return self._served >= RECYCLE_CONTEXTS or self._clock() - self._launched >= RECYCLE_AGE.total_seconds()
