"""The paging driver's stop and keep rules over a simulated tab (owner #52): whatever the list's length, its batch size,
the row target and the action cap, the run stops for a stated reason, overshoots the target by less than one batch,
never passes its cap, and keeps the grown document once.

The simulated tab serves a listing that shows `batch` more items each time the control after them is clicked, as
markup the driver parses like any page; nothing runs a browser.
"""

import asyncio
import time
from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st

from crawlerai.acquire.browser_tab import Click, Ref
from crawlerai.acquire.types import BrowserActions
from crawlerai.crawl.paging import Caps, collect

_URL = "https://shop.example.test/list"
_WAIT_S, _POLL_S = 0.02, 0.001  # fast waits: the simulated tab changes at once


class _LoadMoreTab:
    def __init__(self, total: int, batch: int) -> None:
        self.total, self.batch = total, batch
        self.shown = min(total, batch)
        self.changes = 0
        self.requests = 0
        self.kept: list[int] = []  # the items each kept state showed

    @property
    def url(self) -> str:
        return _URL

    async def html(self) -> str:
        cards = "".join(f'<li class="card"><a href="/item/{i}">{i}</a></li>' for i in range(self.shown))
        control = "<button>+</button>" if self.shown < self.total else ""
        return f"<html><body><main><ul>{cards}</ul>{control}</main></body></html>"

    async def mutations(self) -> int:
        return self.changes

    async def areas(self, elements: Sequence[Ref]) -> list[float]:
        return [1.0] * len(elements)

    async def click(self, element: Ref) -> Click:
        if element[1] != "button" or self.shown >= self.total:
            return "gone"
        self.shown = min(self.total, self.shown + self.batch)
        self.changes += 1
        self.requests += 1
        return "clicked"

    async def scroll(self) -> None:
        return None

    async def goto(self, url: str) -> bool:
        return False

    async def back(self) -> None:
        return None

    def data_requests(self) -> int:
        return self.requests

    async def keep(self) -> bool:
        self.kept.append(self.shown)
        return True


async def _open(url: str | None) -> bool:
    return True


@settings(deadline=None, max_examples=60)
@given(
    total=st.integers(3, 120),
    batch=st.integers(3, 30),
    records=st.integers(1, 150),
    cap=st.integers(1, 50),
)
def test_a_load_more_run_stops_for_its_reason_within_one_batch_and_its_cap(
    total: int, batch: int, records: int, cap: int
) -> None:
    tab = _LoadMoreTab(total, batch)
    caps = Caps(actions=cap, wait_s=_WAIT_S, poll_s=_POLL_S)

    report = asyncio.run(collect(tab, BrowserActions(records=records), _open, time.monotonic() + 60, caps))

    assert report.actions <= cap
    assert report.items == tab.shown
    assert tab.kept == [tab.shown]
    assert report.pages == 1
    match report.stop:
        case "records":
            assert records <= report.items < records + batch
        case "end":
            assert report.items == total
        case "action_cap":
            assert report.actions == cap
        case "no_mechanism":  # the first batch was the whole list: there is no control to click
            assert report.items == total <= batch
        case other:
            raise AssertionError(other)
    if report.stop != "records" or report.items > batch:
        assert report.mechanism in (None, "load_more")


@settings(deadline=None, max_examples=30)
@given(total=st.integers(3, 60), records=st.integers(1, 100))
def test_a_list_with_nothing_to_page_keeps_one_state_and_names_no_mechanism(total: int, records: int) -> None:
    tab = _LoadMoreTab(total, total)  # everything shows; there is no control

    report = asyncio.run(
        collect(
            tab, BrowserActions(records=records), _open, time.monotonic() + 60, Caps(wait_s=_WAIT_S, poll_s=_POLL_S)
        )
    )

    assert report.items == total
    assert tab.kept == [total]
    expected = "records" if records <= total else "no_mechanism"
    assert (report.stop, report.mechanism, report.actions > 0) == (expected, None, expected == "no_mechanism")
