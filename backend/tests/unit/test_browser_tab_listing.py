"""A listing's browser fetch (`fetch_listing`) when reading its first state fails after its page steps ran: the
failure's attempt still says how each step ended."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from crawlerai.acquire import browser_tab
from crawlerai.acquire.browser import Failed
from crawlerai.acquire.types import FetchPolicy, StepOutcome

URL = "https://shop.example.test/c/1"


def test_a_failed_first_read_keeps_the_outcomes_of_the_steps_that_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    clicked = (StepOutcome(action="click", outcome="done"),)

    @asynccontextmanager
    async def rendered(*_: Any) -> AsyncIterator[Any]:
        yield SimpleNamespace(page=SimpleNamespace(url="https://shop.example.test/list"))

    async def stepped(_page: Any) -> tuple[StepOutcome, ...]:
        return clicked

    async def read_state(_page: Any) -> Any:
        raise Failed("body_too_large", None)

    async def drive(_tab: Any) -> Any:
        raise AssertionError("a page not read is not driven")

    monkeypatch.setattr(browser_tab, "rendered", rendered)
    monkeypatch.setattr(browser_tab, "stepped", stepped)
    monkeypatch.setattr(browser_tab, "read_state", read_state)
    session: Any = SimpleNamespace()

    paged = asyncio.run(browser_tab.fetch_listing(URL, FetchPolicy(), drive, session=session, engine_version="test"))

    (page,) = paged.pages
    assert (page.block_class, page.attempts[0].error) == ("error", "body_too_large")
    assert page.attempts[0].steps == clicked
