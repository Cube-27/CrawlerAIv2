"""A tab's data responses (`_PatchrightTab.calls`): responses keep arriving while their bodies are read, and a read
covers the responses there were when it started; a later one is read by the next call."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from crawlerai.acquire import browser_tab
from crawlerai.acquire.browser import JSON_PAGE_MAX_BYTES


class _Page:
    url = "https://shop.example.test/c/1"

    def on(self, _event: str, _handler: Any) -> None:
        return None


def _tab(responses: list[Any]) -> Any:
    rendered = SimpleNamespace(page=_Page(), calls=SimpleNamespace(responses=responses, actions=0))
    return browser_tab._PatchrightTab(rendered, url=_Page.url, engine_version="test", started=0.0, steps=())  # type: ignore[arg-type]


def test_a_response_arriving_while_bodies_are_read_waits_for_the_next_call(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[Any] = ["r0", "r1"]

    async def bodies(read: list[Any]) -> tuple[Any, ...]:
        if read == ["r0"]:
            responses.append("r2")  # the page answers another call meanwhile
        await asyncio.sleep(0)
        return ((f"body-{read[0]}", b"{}"),)

    monkeypatch.setattr(browser_tab, "json_bodies", bodies)
    tab = _tab(responses)

    first = asyncio.run(tab.calls())
    second = asyncio.run(tab.calls())

    assert [body for body, _ in first] == ["body-r0", "body-r1"]
    assert [body for body, _ in second] == ["body-r0", "body-r1", "body-r2"]


def test_the_bodies_read_stop_at_the_page_cap_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    # INV-30: at most `JSON_PAGE_MAX_BYTES` of JSON bodies per page in all, though each response is read on its own.
    size = JSON_PAGE_MAX_BYTES // 5
    responses: list[Any] = [f"r{i}" for i in range(6)]

    async def bodies(read: list[Any]) -> tuple[Any, ...]:
        return ((f"body-{read[0]}", b"x" * size),)

    monkeypatch.setattr(browser_tab, "json_bodies", bodies)
    tab = _tab(responses)

    read = asyncio.run(tab.calls())

    assert [body for body, _ in read] == [f"body-r{i}" for i in range(5)]
    held = [entry for entry in tab._bodies.values() if entry is not None]
    assert sum(len(data) for _, data in held) <= JSON_PAGE_MAX_BYTES
