"""The worker's browser (SPEC-02 §4.8, INV-31): one per worker process, launched when a task first needs it and shared
by the tasks after it.

A fetch that leaves the browser disconnected (Chromium crashed, or was killed) restarts it once and fetches again. If
the restarted browser dies too, that second fetch's result stands, so the crash ends only the task that was using the
browser, and the next task that needs one launches a new one: at most one restart per task.
"""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack

from crawlerai.acquire.types import FetchPolicy, FetchResult


class SharedBrowser[S]:
    """`launch` opens a browser session, `fetch` fetches a page in one, and `alive` says whether a session's browser
    is still connected."""

    def __init__(
        self,
        launch: Callable[[], AbstractAsyncContextManager[S]],
        fetch: Callable[[S, str, FetchPolicy], Awaitable[FetchResult]],
        alive: Callable[[S], bool],
    ) -> None:
        self._launch = launch
        self._fetch = fetch
        self._alive = alive
        self._open: tuple[AsyncExitStack, S] | None = None

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        """The browser rung (`crawlerai.acquire.rungs.Rungs.browser`)."""
        session = await self._session()
        result = await self._fetch(session, url, policy)
        if self._alive(session):
            return result
        await self.aclose()
        session = await self._session()
        result = await self._fetch(session, url, policy)
        if not self._alive(session):
            await self.aclose()
        return result

    async def aclose(self) -> None:
        """End the browser, if one is running."""
        if self._open is not None:
            stack, _ = self._open
            self._open = None
            await stack.aclose()

    async def _session(self) -> S:
        if self._open is None:
            stack = AsyncExitStack()
            session = await stack.enter_async_context(self._launch())
            self._open = stack, session
        return self._open[1]
