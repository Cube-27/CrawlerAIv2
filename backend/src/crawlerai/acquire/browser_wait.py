"""The browser rung's one wait: a page is read once it is ready
(`settle`) and shows the text its scripts carry (`_rendered`), its main frame's document navigations followed
(`MainFrame`), an interstitial given its own bounded wait to navigate on.
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from functools import partial
from inspect import isawaitable
from typing import Final

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Frame, Page, Request, Response
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.browser_capture import DataCalls, document_html
from crawlerai.acquire.classify import carries_unrendered, interstitial
from crawlerai.acquire.types import CallEndpoint, FetchPolicy

__all__ = ["READY_MAX_S", "STEP_QUIET_S", "MainFrame", "called", "ms_until", "settle", "until"]

# The wait for the page to be ready ends at this share of `browser_timeout_s` whatever navigations the page makes; the
# rest is for reading the DOM and the bodies.
_SETTLE_SHARE = 0.9
# The one wait (`settle`): from `DOMContentLoaded` (HTML Standard
# §8.4.6), a document is read as soon as it is ready (`_ready`), and at most this long after it fired `load`, ready or
# not: what is there then is read. Before `load`, only the wait's deadline bounds it. An unmeasured starting point
# within 3 to 4 s.
READY_MAX_S: Final = 3.5
_POLL_S = 0.25
# A document, or a page step that starts no data call, has settled once no data call has been in flight this long:
# Playwright's `networkidle` quiet period (500 ms).
STEP_QUIET_S: Final = 0.5
# RFC 9110 §15.4: a 3xx document answer is a redirect hop (or a validator's 304), never the document the frame shows.
_REDIRECTION = range(300, 400)
# for a ready document `interstitial` judges to stand in for the page, the wait for the main frame to
# navigate on ends this share of `browser_timeout_s` after the fetch began, and at most `_INTERSTITIAL_MAX_S` after,
# whatever rule judged it (a refusal's status, or a rendered 2xx document's structure), and as soon as a navigation
# commits. Nothing is clicked or typed. The bound is an unmeasured starting point: a challenge that does not clear
# headless held each fetch for the whole share (backlog, #244).
_INTERSTITIAL_SHARE = 0.4
_INTERSTITIAL_MAX_S = 10.0


class MainFrame:
    """The main frame's document navigations: the latest request (one per redirect hop), whether one is in
    flight, the response of the latest document, which the frame shows once the navigation commits, how many
    navigations have committed, and when the latest document fired `DOMContentLoaded` and `load` (HTML Standard
    §8.4.6)."""

    def __init__(self, page: Page, first_url: str) -> None:
        self._page = page
        self.last_hop = first_url
        self.pending = False
        self.latest: Response | None = None
        self.commits = 0
        self.loaded = False
        self.loaded_at = 0.0  # on `time.monotonic`: when the latest document fired `load`
        self.parsed = False
        self.parsed_at = 0.0  # on `time.monotonic`: when the latest document fired `DOMContentLoaded`
        self._committed = asyncio.Event()

    def on_load(self) -> None:
        self.loaded, self.loaded_at = True, time.monotonic()

    def on_parsed(self) -> None:
        self.parsed, self.parsed_at = True, time.monotonic()

    def _ours(self, request: Request) -> bool:
        return request.is_navigation_request() and request.frame == self._page.main_frame

    def on_request(self, request: Request) -> None:
        if self._ours(request):
            self.last_hop, self.pending = request.url, True

    def on_response(self, response: Response) -> None:
        if self._ours(response.request) and response.status not in _REDIRECTION:
            self.latest, self.pending, self.loaded, self.parsed = response, False, False, False

    def on_failed(self, request: Request) -> None:
        if self._ours(request):
            self.pending = False

    def on_navigated(self, frame: Frame) -> None:
        if frame == self._page.main_frame:
            self.commits += 1
            self._committed.set()

    async def next_commit(self, seen: int) -> None:
        """Returns once the main frame has committed more navigations than `seen` (a count read from `commits`)."""
        self._committed.clear()  # no callback runs before the check: the event loop is not yielded to in between
        while self.commits == seen:
            await self._committed.wait()
            self._committed.clear()


async def settle(page: Page, frame: MainFrame, calls: DataCalls, policy: FetchPolicy, started: float) -> None:
    """Wait until the document is ready to read (`_rendered`), at most `READY_MAX_S` after it fired `load`, a document
    the main frame navigates to meanwhile starting that wait over (`until`); then, while the ready document is an
    interstitial, wait for the next one (within its own share of the budget) and for it to be ready. All within
    `_SETTLE_SHARE` of the budget that began at `started` (on `time.monotonic`). Judged once ready, a page that renders
    itself by script is judged as rendered, so only a document that stays no page waits for a navigation."""
    budget_s = policy.browser_timeout_s
    interstitial_deadline = started + min(_INTERSTITIAL_SHARE * budget_s, _INTERSTITIAL_MAX_S)
    deadline = started + _SETTLE_SHARE * budget_s
    ready = partial(_rendered, page, partial(_ready, frame, calls, policy))
    await until(frame, ready, READY_MAX_S, deadline, after_load=True)
    while time.monotonic() < interstitial_deadline:
        # Counted before the document is judged: a commit while it is read or classified is the one waited for.
        seen = frame.commits
        if (judged := await _interstitial(page, frame)) is False:
            return
        # None: the document was replaced while it was read, so the next one is waited for as any navigation is.
        if judged and not await _next_document(page, frame, seen, interstitial_deadline):
            return
        await until(frame, ready, READY_MAX_S, deadline, after_load=True)


async def _rendered(page: Page, ready: Callable[[], bool]) -> bool:
    """Whether the document is `ready` and no longer carries its text unrendered (`classify.carries_unrendered`:
    near-empty rendered text beside large script or concealed text): a page that hydrates from its inline state makes
    no data call, so the quiet network says nothing of whether its script has written the DOM. A document replaced
    while it was read is not."""
    if not ready():
        return False
    try:
        text = await document_html(page)
    except PlaywrightError:
        return False
    return not await asyncio.to_thread(carries_unrendered, text)


async def until(
    frame: MainFrame,
    ready: Callable[[], bool | Awaitable[bool]],
    within_s: float,
    deadline: float,
    *,
    after_load: bool = False,
) -> None:
    """Returns once `ready` holds (awaited, when it reads the page) with no navigation in flight, or `within_s` after
    the wait began, or after the last document the main frame navigated to meanwhile (a script's `location.replace`, a
    refresh: what was shown was an interim document; a same-document navigation, `history.pushState`, is none), at
    most at `deadline`. With `after_load`, the wait ends `within_s` after the document fired `load`, and before that
    only at `deadline`."""
    shown, begun = frame.latest, time.monotonic()
    while time.monotonic() < _wait_end(frame, begun, within_s, deadline, after_load=after_load):
        if frame.latest is not shown:
            shown, begun = frame.latest, time.monotonic()
        elif not frame.pending and await _holds(ready):
            return
        await asyncio.sleep(_POLL_S)


async def _holds(ready: Callable[[], bool | Awaitable[bool]]) -> bool:
    held = ready()
    return await held if isawaitable(held) else held


def _wait_end(frame: MainFrame, begun: float, within_s: float, deadline: float, *, after_load: bool) -> float:
    if not after_load:
        return min(deadline, begun + within_s)
    return min(deadline, frame.loaded_at + within_s) if frame.loaded else deadline


def called(calls: DataCalls, answered: int) -> bool:
    """Whether a data call has ended since `answered` had, and none is in flight."""
    return calls.answered > answered and not calls.in_flight


def _ready(frame: MainFrame, calls: DataCalls, policy: FetchPolicy) -> bool:
    """Whether the document is ready to read, a fixed condition: it has
    fired `DOMContentLoaded` (HTML Standard §8.4.6), and (a) every endpoint the site's located `call` field sources
    name (`policy.ready_calls`) has answered, else (b) no data call has been in flight since, for `STEP_QUIET_S`. A
    listing is read when the wait ends: its item area (`item_areas`) may still be filling in."""
    if policy.page_kind == "listing" or not frame.parsed:
        return False
    if policy.ready_calls:
        return all(_answered(endpoint, calls) for endpoint in policy.ready_calls)
    if calls.in_flight:
        return False
    return time.monotonic() - max(frame.parsed_at, calls.idle_since) >= STEP_QUIET_S


def _answered(endpoint: CallEndpoint, calls: DataCalls) -> bool:
    """Whether a call of `endpoint` has answered with a body the capture reads (`DataCalls.responses`) in full."""
    return any(
        endpoint.matches(response.request.method, response.url) and calls.finished(response)
        for response, _ in calls.responses
    )


async def _interstitial(page: Page, frame: MainFrame) -> bool | None:
    """Whether the document shown is an interstitial (`classify.interstitial`, judged as rendered: read as the capture
    reads it, open shadow roots included); None when it was replaced while it was read."""
    shown = frame.latest
    if shown is None:
        return False
    try:
        text = await document_html(page)
    except PlaywrightError:
        return None
    # classify's rules parse HTML synchronously; a thread keeps the event loop free.
    headers = tuple(shown.headers.items())
    return await asyncio.to_thread(partial(interstitial, rendered=True), shown.status, headers, text, shown.url)


async def _next_document(page: Page, frame: MainFrame, seen: int, deadline: float) -> bool:
    """Whether the main frame committed a navigation past the `seen` count and its document was parsed
    (`DOMContentLoaded`) before `deadline`. The commit, not the response: until then the frame still shows the
    interstitial."""
    try:
        async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
            await frame.next_commit(seen)
    except TimeoutError:
        return False
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("domcontentloaded", timeout=ms_until(deadline))
    return True


def ms_until(deadline: float) -> float:
    # Playwright reads a timeout of 0 as "no timeout": a spent budget becomes the smallest positive one instead.
    return max(1.0, (deadline - time.monotonic()) * 1000)
