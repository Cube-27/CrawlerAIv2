"""The worker's shared browser (acquisition spec, INV-31): launched once and shared, and restarted at most once per task
when it crashes. The browser is a stub whose fetches can kill the session they run in; no Chromium."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast

import pytest

from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.shared_browser import SharedBrowser
from crawlerai.acquire.types import FetchPolicy, FetchResult

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/p/1"
OTHER = "https://shop.example.test/p/2"


@dataclass
class Session:
    number: int
    connected: bool = True
    closed: bool = False


@dataclass
class Chromium:
    """Launches numbered sessions. A fetch of a URL in `kills` disconnects its session, each of the first
    `kills[url]` times. Each fetch returns a result of its own (`origin`)."""

    kills: dict[str, int] = field(default_factory=dict)
    sessions: list[Session] = field(default_factory=list)
    fetched: list[tuple[int, str]] = field(default_factory=list)
    made: list[tuple[FetchResult, tuple[int, str]]] = field(default_factory=list)
    raises: bool = False  # a fetch that kills its session raises instead of returning

    @asynccontextmanager
    async def launch(self) -> AsyncIterator[Session]:
        session = Session(len(self.sessions) + 1)
        self.sessions.append(session)
        try:
            yield session
        finally:
            session.closed = True

    async def fetch(self, session: Session, url: str, policy: FetchPolicy, export: CookieExport | None) -> FetchResult:
        self.fetched.append((session.number, url))
        if self.kills.get(url, 0) > 0:
            self.kills[url] -= 1
            session.connected = False
            if self.raises:
                raise RuntimeError("Target closed")
        result = cast(FetchResult, object())
        self.made.append((result, (session.number, url)))
        return result

    def origin(self, result: FetchResult) -> tuple[int, str]:
        """The session and URL of the fetch that returned `result`."""
        (found,) = (origin for made, origin in self.made if made is result)
        return found

    def browser(self) -> SharedBrowser[Session]:
        return SharedBrowser(self.launch, self.fetch, lambda session: session.connected)


async def test_one_browser_is_launched_on_first_use_and_shared() -> None:
    chromium = Chromium()
    browser = chromium.browser()
    assert chromium.sessions == []

    for url in (URL, OTHER, URL):
        await browser.fetch(url, FetchPolicy())

    assert chromium.fetched == [(1, URL), (1, OTHER), (1, URL)]
    await browser.aclose()
    assert [session.closed for session in chromium.sessions] == [True]


async def test_a_crashed_browser_is_restarted_once_and_the_page_fetched_again() -> None:
    chromium = Chromium(kills={URL: 1})
    browser = chromium.browser()

    result = await browser.fetch(URL, FetchPolicy())
    await browser.fetch(OTHER, FetchPolicy())

    assert chromium.origin(result) == (2, URL)
    assert chromium.fetched == [(1, URL), (2, URL), (2, OTHER)]
    assert [(s.closed, s.connected) for s in chromium.sessions] == [(True, False), (False, True)]


async def test_a_fetch_that_raises_with_the_browser_gone_is_fetched_again_in_a_new_one() -> None:
    chromium = Chromium(kills={URL: 1}, raises=True)
    browser = chromium.browser()

    result = await browser.fetch(URL, FetchPolicy())

    assert chromium.origin(result) == (2, URL)
    assert chromium.fetched == [(1, URL), (2, URL)]
    assert chromium.sessions[0].closed
    await browser.aclose()
