"""The caller's page steps on the browser rung: run in order on the rendered page after its settle and
before it is read, each within its own timeout.

An element is named by an XPath 1.0 expression (the caller's vocabulary in `config_ir` translates a CSS selector into
one, as an IR `css` step is), or for a click by its visible text. Locators and `evaluate` run in Patchright's isolated
world, which shares the document but not the page's globals. A click is a pointer click on the first matching
element that becomes actionable; one an overlay intercepts times out and is reported, not worked around. Nothing is
typed into a password field or a field whose autofill names a credential: no step logs in or enters a
credential.

The first step that does not complete ends the run: the steps after it are `skipped`, and the page is read as it is.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Final, cast

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Locator, Page
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.types import PageStep, StepOutcome, StepResult

__all__ = ["Settle", "run_steps", "steps_budget_s"]

# Waits up to the given seconds after a step that changes the page for the data calls it started to end (the browser
# rung's ready wait); returns early once they have.
Settle = Callable[[float], Awaitable[None]]
# How many fetch and XMLHttpRequest calls are in flight now.
InFlight = Callable[[], int]

# A step that changes the page is followed by a settle of at most this long, within its own timeout.
_SETTLE_MAX_S: Final = 3.0
# Network idle as Playwright defines it for `networkidle`: no request for 500 ms; here no data call (Fetch Standard
# §2.2.5 destinations fetch and XMLHttpRequest).
_IDLE_S: Final = 0.5
_POLL_S: Final = 0.1
# Scrolling until the document stops growing ends after this many rounds whatever the timeout.
_SCROLL_ROUNDS: Final = 20
# CSSOM View: the scrolling element's height, and scrolling to its end or by a number of CSS pixels.
_HEIGHT_JS: Final = "() => document.scrollingElement.scrollHeight"
_END_JS: Final = "() => window.scrollTo(0, document.scrollingElement.scrollHeight)"
_BY_JS: Final = "(px) => window.scrollBy(0, px)"
# HTML Standard §4.10.18.7.1: the autofill field names that hold a credential.
_CREDENTIAL_AUTOFILL: Final = frozenset({"current-password", "new-password", "one-time-code"})
# HTML Standard §4.10.5.1.20: an input whose type is `password` holds a credential.
_CREDENTIAL_JS: Final = """(node) => {
  const tokens = (node.getAttribute('autocomplete') || '').toLowerCase().split(/\\s+/);
  return [(node.getAttribute('type') || '').toLowerCase(), tokens];
}"""


def steps_budget_s(steps: Sequence[PageStep]) -> float:
    """The most time the steps may take: each step's timeout and the settle after it."""
    return sum(step.timeout_ms / 1000 + _SETTLE_MAX_S for step in steps)


async def run_steps(
    page: Page, steps: Sequence[PageStep], settle: Settle, in_flight: InFlight
) -> tuple[StepOutcome, ...]:
    """Run `steps` in order on `page`; how each ended."""
    outcomes: list[StepOutcome] = []
    for index, step in enumerate(steps):
        outcome = await _bounded(page, step, settle, in_flight)
        outcomes.append(StepOutcome(action=step.action, outcome=outcome))
        if outcome != "done":
            outcomes.extend(StepOutcome(action=later.action, outcome="skipped") for later in steps[index + 1 :])
            break
    return tuple(outcomes)


async def _bounded(page: Page, step: PageStep, settle: Settle, in_flight: InFlight) -> StepResult:
    deadline = time.monotonic() + step.timeout_ms / 1000
    try:
        outcome = await _run(page, step, deadline, in_flight)
    except PlaywrightTimeout:
        outcome = await _missing(page, step)
    except PlaywrightError:
        outcome = "error"
    if outcome == "done" and step.action != "wait":
        await settle(_SETTLE_MAX_S)
    return outcome


async def _run(page: Page, step: PageStep, deadline: float, in_flight: InFlight) -> StepResult:
    timeout_ms = _ms_until(deadline)
    match step.action:
        case "wait":
            return await _wait(page, step, deadline, in_flight)
        case "click":
            await _target(page, step).click(timeout=timeout_ms)
            return "done"
        case "scroll":
            return await _scroll(page, step, deadline)
        case "press":
            await page.keyboard.press(step.key or "", delay=0)
            return "done"
        case "type":
            return await _type(page, step, timeout_ms)


async def _wait(page: Page, step: PageStep, deadline: float, in_flight: InFlight) -> StepResult:
    if step.ms is not None:
        await asyncio.sleep(step.ms / 1000)
        return "done"
    if step.network_idle:
        return await _network_idle(deadline, in_flight)
    await _target(page, step).wait_for(state="visible", timeout=_ms_until(deadline))
    return "done"


async def _network_idle(deadline: float, in_flight: InFlight) -> StepResult:
    idle_since: float | None = None
    while (now := time.monotonic()) < deadline:
        if in_flight():
            idle_since = None
        elif idle_since is None:
            idle_since = now
        elif now - idle_since >= _IDLE_S:
            return "done"
        await asyncio.sleep(_POLL_S)
    return "timeout"


async def _scroll(page: Page, step: PageStep, deadline: float) -> StepResult:
    if step.scroll == "by":
        await page.evaluate(_BY_JS, step.px or 0)
        return "done"
    if step.scroll == "end":
        await page.evaluate(_END_JS)
        return "done"
    for _ in range(_SCROLL_ROUNDS):
        before = cast(int, await page.evaluate(_HEIGHT_JS))
        await page.evaluate(_END_JS)
        grew = await _grew(page, before, deadline)
        if not grew:
            return "done"
        if time.monotonic() >= deadline:
            return "timeout"
    return "done"


async def _grew(page: Page, before: int, deadline: float) -> bool:
    """Whether the document grows past `before` within a settle's time (content loaded when its end came into view)."""
    until = min(deadline, time.monotonic() + _SETTLE_MAX_S)
    while time.monotonic() < until:
        await asyncio.sleep(_POLL_S * 2)
        if cast(int, await page.evaluate(_HEIGHT_JS)) > before:
            return True
    return False


async def _type(page: Page, step: PageStep, timeout_ms: float) -> StepResult:
    target = _target(page, step)
    await target.wait_for(state="visible", timeout=timeout_ms)
    kind, autofill = cast(tuple[str, list[str]], await target.evaluate(_CREDENTIAL_JS))
    if kind == "password" or _CREDENTIAL_AUTOFILL.intersection(autofill):
        return "refused"
    await target.fill(step.text or "", timeout=timeout_ms)
    return "done"


def _target(page: Page, step: PageStep) -> Locator:
    """The first visible element the step names: by its XPath, or for a click by its text (Playwright's text engine, a
    case-insensitive substring of the element's rendered text)."""
    return _matches(page, step).filter(visible=True).first


def _matches(page: Page, step: PageStep) -> Locator:
    return page.locator(f"xpath={step.xpath}") if step.xpath is not None else page.get_by_text(step.text or "")


async def _missing(page: Page, step: PageStep) -> StepResult:
    """A step that timed out: `not_found` when its element never appeared, else `timeout` (present, not actionable)."""
    if step.xpath is None and step.text is None:
        return "timeout"
    try:
        found = await _matches(page, step).count()
    except PlaywrightError:
        return "error"
    return "timeout" if found else "not_found"


def _ms_until(deadline: float) -> float:
    # 0 would mean no timeout in Playwright.
    return max(1.0, 1000 * (deadline - time.monotonic()))
