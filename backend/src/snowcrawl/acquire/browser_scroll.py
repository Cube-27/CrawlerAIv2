"""The browser rung's scroll pass: content a page renders only once it is scrolled into view (a lazy-loaded section,
a feed's next batch, a virtualized list or post stream) is rendered before the page is read.

After the ready wait and the caller's steps, the page's scroller is scrolled one viewport at a time, as crawl4ai's
`scan_full_page` does, each step followed by the wait for the data calls it started, until the scroller's end shows
and stops moving away (nothing more renders there), or the pass's bounds end it. Stepping, not jumping to the end,
lets every element a lazy loader observes (Intersection Observer) cross the viewport. The scroller is the document's
scrolling element, else, when the document does not scroll, the largest element that does (CSSOM View `scrollHeight`
past `clientHeight`, CSS Overflow `overflow-y` `auto` or `scroll`).

A virtualized list removes what it scrolls past (crawl4ai merges a named container's snapshots for that). Here a
MutationObserver keeps every node the page removes from above the scroller's viewport during the pass, and the
document is read with those the page did not render again put back where they left (`browser_capture.document_html`).
Only what was scrolled past is kept: a loading indicator removed in view, or below it, is not.
"""

import asyncio
import contextlib
import time
from typing import Final

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Page, Request

from snowcrawl.acquire.browser_capture import DataCalls
from snowcrawl.acquire.browser_wait import MainFrame

__all__ = ["SCROLL_MAX_S", "scroll_back", "scroll_through", "watch"]

# The pass ends this long after it began, and after this many steps, whatever still renders: an infinite feed never
# ends by itself. Unmeasured starting points.
SCROLL_MAX_S: Final = 10.0
_STEPS_MAX: Final = 40
# A step has settled once no data call it started has been in flight for this long (crawl4ai's scroll delay), and at
# most `_STEP_MAX_S` after it scrolled.
_STEP_QUIET_S: Final = 0.2
_STEP_MAX_S: Final = 3.0
_POLL_S: Final = 0.05
# The scroller (module docstring), as `__scroller`; null when nothing scrolls. The viewport's overflow is the root
# element's, else the body's (CSS Overflow 3 §3.3, propagation to the viewport).
_SCROLLER_JS: Final = """() => {
  const style = (element) => (element ? getComputedStyle(element).overflowY : 'visible');
  const scrolls = (element) => element.scrollHeight > element.clientHeight + 1;
  const doc = document.scrollingElement || document.documentElement;
  const root = style(document.documentElement);
  const viewport = root === 'visible' ? style(document.body) : root;
  if (scrolls(doc) && viewport !== 'hidden' && viewport !== 'clip') return (globalThis.__scroller = doc);
  let best = null, area = 0;
  for (const element of document.querySelectorAll('*')) {
    if (!scrolls(element) || !['auto', 'scroll'].includes(style(element))) continue;
    const size = element.clientWidth * element.clientHeight;
    if (size > area) [best, area] = [element, size];
  }
  return (globalThis.__scroller = best);
}"""
# Scroll the scroller by its viewport's height (CSSOM View `scrollBy`; on the scrolling element it scrolls the
# viewport); where it is then: null when nothing scrolls.
_STEP_JS: Final = f"""() => {{
  const scroller = ({_SCROLLER_JS})();
  if (scroller === null) return null;
  scroller.scrollBy(0, scroller.clientHeight);
  return {{ top: scroller.scrollTop, view: scroller.clientHeight, height: scroller.scrollHeight }};
}}"""
_AT_JS: Final = """() => {
  const scroller = globalThis.__scroller;
  if (!scroller || !scroller.isConnected) return null;
  return { top: scroller.scrollTop, view: scroller.clientHeight, height: scroller.scrollHeight };
}"""
# DOM Standard §4.3: a MutationObserver on `childList` sees each removal with the parent and the siblings the removed
# nodes sat between. Where each element ends (CSSOM View `getBoundingClientRect`) is kept in the scroller's content
# coordinates, where its viewport begins at `scrollTop`: every element's when the watch begins, and each added one's
# when it is added. A removed node whose end lay above the viewport was scrolled past; for one never measured, the
# place it left is judged instead (the next sibling's top, else the previous sibling's bottom, else the parent's
# bottom). Those that hold text are logged as `__scrolledPast`, which `browser_capture.document_html` reads. False
# when nothing scrolls.
_WATCH_JS: Final = (
    "() => {\n  if (("
    + _SCROLLER_JS
    + ")() === null) return false;\n"
    + """  if (globalThis.__scrolledPast !== undefined) return true;
  const past = (globalThis.__scrolledPast = []);
  const ends = new WeakMap();
  const origin = () => {
    const scroller = globalThis.__scroller;
    if (!scroller || !scroller.isConnected) return { top: 0, scrolled: 0 };
    const inner = scroller !== document.scrollingElement;
    return { top: inner ? scroller.getBoundingClientRect().top : 0, scrolled: scroller.scrollTop };
  };
  const measure = (root) => {
    const { top, scrolled } = origin();
    for (const element of [root, ...root.querySelectorAll('*')]) {
      const rect = element.getBoundingClientRect();
      if (rect.width || rect.height) ends.set(element, rect.bottom - top + scrolled);
    }
  };
  const box = (node) => {
    if (!node || !node.isConnected) return null;
    const rect = node.getBoundingClientRect();
    return rect.width || rect.height ? rect : null;
  };
  // The place removed nodes left (DOMRect `y` is the top of a box of non-negative height).
  const place = (prev, next, parent) => {
    const after = box(next && (next.nodeType === Node.ELEMENT_NODE ? next : next.nextElementSibling));
    if (after) return after.y;
    const before = box(prev && (prev.nodeType === Node.ELEMENT_NODE ? prev : prev.previousElementSibling));
    if (before) return before.bottom;
    const around = box(parent);
    return around ? around.bottom : Infinity;
  };
  globalThis.__scrollWatch = new MutationObserver((records) => {
    const { top, scrolled } = origin();
    for (const { removedNodes, addedNodes, target: parent, previousSibling: prev, nextSibling: next } of records) {
      const nodes = Array.from(removedNodes).filter((node) => {
        if (!/\\S/.test(node.textContent || '')) return false;
        const end = ends.get(node);
        return end === undefined ? place(prev, next, parent) <= top : end <= scrolled;
      });
      if (nodes.length > 0) past.push({ nodes, parent, prev, next });
      for (const node of addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && node.isConnected) measure(node);
      }
    }
  });
  measure(document.documentElement);
  globalThis.__scrollWatch.observe(document, { subtree: true, childList: true });
  return true;
}"""
)
_UNWATCH_JS: Final = "() => globalThis.__scrollWatch?.disconnect()"
# CSSOM View `scrollTo`: the scroller back at its start.
_BACK_JS: Final = "() => globalThis.__scroller?.scrollTo(0, 0)"


async def watch(page: Page) -> None:
    """Start logging what the page removes once scrolled past (`_WATCH_JS`), before anything scrolls it: the caller's
    steps may."""
    with contextlib.suppress(PlaywrightError):
        await page.evaluate(_WATCH_JS, isolated_context=True)


async def scroll_through(page: Page, frame: MainFrame, calls: DataCalls) -> None:
    """Scroll the page through (module docstring), within `SCROLL_MAX_S`, the removals logged since `watch` (started
    here when it was not); a document the main frame navigates to meanwhile, or one that can no longer be read, ends
    the pass."""
    deadline = time.monotonic() + SCROLL_MAX_S
    shown = frame.latest
    with contextlib.suppress(PlaywrightError):
        if not await page.evaluate(_WATCH_JS, isolated_context=True):
            return
        try:
            for _ in range(_STEPS_MAX):
                if time.monotonic() >= deadline or frame.latest is not shown or not await _step(page, calls, deadline):
                    break
        finally:
            await page.evaluate(_UNWATCH_JS, isolated_context=True)


async def scroll_back(page: Page) -> None:
    """Scroll the scroller back to its start, for a view of the page as it first showed."""
    with contextlib.suppress(PlaywrightError):
        await page.evaluate(_BACK_JS, isolated_context=True)


async def _step(page: Page, calls: DataCalls, deadline: float) -> bool:
    """Scroll one viewport and wait for what it loads; whether there is more to scroll: the end is not in view, or it
    moved away while the step settled."""
    # Calls in flight before the step (a long poll, a stream) are not the step's: they may never end.
    earlier = set(calls.in_flight)
    before = await page.evaluate(_STEP_JS, isolated_context=True)
    if before is None:
        return False
    await _settled(calls, earlier, deadline)
    after = await page.evaluate(_AT_JS, isolated_context=True)
    return after is not None and (not _at_end(after) or after["height"] > before["height"])


def _at_end(at: dict[str, float]) -> bool:
    return at["top"] + at["view"] >= at["height"] - 1


async def _settled(calls: DataCalls, earlier: set[Request], deadline: float) -> None:
    begun = time.monotonic()
    end = min(deadline, begun + _STEP_MAX_S)
    quiet_since = begun
    while (now := time.monotonic()) < end:
        if not calls.in_flight <= earlier:
            quiet_since = now
        elif now - quiet_since >= _STEP_QUIET_S:
            return
        await asyncio.sleep(_POLL_S)
