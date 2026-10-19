"""The browser rung runs Patchright's documented setup (INV-42, INV-43, INV-44; owner #50): the full Chromium build in
headless mode, launch arguments limited to the guard's own, and contexts with no custom user agent, client hints or
headers. A fake Playwright records what `open_browser` and `fetch_browser` ask for; no browser runs.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

import pytest

import crawlerai
from crawlerai.acquire import browser as browser_module
from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy
from crawlerai.core.engine_version import ENGINE_VERSION

_SRC = Path(crawlerai.__file__).parent


class _Recorder:
    def __init__(self) -> None:
        self.launch: dict[str, Any] = {}
        self.context: dict[str, Any] = {}


class _Stop(Exception):
    """Raised where the fake stops: only the launch and context options are under test."""


class _Context:
    async def route(self, _pattern: str, _handler: object) -> None:
        return None  # the media filter: it aborts requests by resource type and sets no header (INV-44)

    async def new_page(self) -> object:
        raise _Stop

    async def close(self) -> None:
        return None


class _Browser:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def new_context(self, **options: Any) -> _Context:
        self._recorder.context = options
        return _Context()

    async def close(self) -> None:
        return None


class _Chromium:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def launch(self, **options: Any) -> _Browser:
        self._recorder.launch = options
        return _Browser(self._recorder)


class _Playwright:
    def __init__(self, recorder: _Recorder) -> None:
        self.chromium = _Chromium(recorder)


class _Connector(SafeConnector):
    async def check(self, url: str) -> Target:
        return Target(url=url, host="shop.example.test", port=80, ip=IPv4Address("192.0.2.1"))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorded = _Recorder()

    @asynccontextmanager
    async def fake_playwright() -> Any:
        yield _Playwright(recorded)

    monkeypatch.setattr(browser_module, "async_playwright", fake_playwright)
    return recorded


async def _fetch_once(locale: str | None = None) -> None:
    async with open_browser() as session:
        assert isinstance(session, BrowserSession)
        await fetch_browser(
            "http://shop.example.test/item",
            FetchPolicy(browser_timeout_s=5, locale_hint=locale),
            session=session,
            engine_version=ENGINE_VERSION,
            connector=_Connector(),
        )


def test_inv42_inv43_full_chromium_headless_with_only_the_guard_launch_argument(recorder: _Recorder) -> None:
    fetching = _fetch_once()
    with pytest.raises(_Stop):
        asyncio.run(fetching)

    # `chromium` is Patchright's full Chromium build (`patchright install --no-shell chromium`), not the headless
    # shell; the one argument is the WebRTC proxy policy the SSRF guard needs (INV-16).
    assert recorder.launch == {
        "channel": "chromium",
        "headless": True,
        "args": ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
    }


# Calls that change the browser's identity or run code in the page's main world (Patchright README: no custom
# user agent or headers; evaluate runs in an isolated world). Matched in source, so a new call site fails here.
_IDENTITY_CALLS = re.compile(
    r"user_agent|extra_http_headers|setUserAgentOverride|add_init_script"
    r"|new_cdp_session|isolated_context=False|--enable-automation|--disable-blink-features"
)


def test_inv44_no_source_file_changes_the_browser_identity() -> None:
    offenders = [
        f"{path.relative_to(_SRC)}:{number}"
        for path in sorted(_SRC.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _IDENTITY_CALLS.search(line)
    ]

    assert offenders == []


def test_inv44_a_context_sets_only_the_proxy_downloads_and_the_request_locale(recorder: _Recorder) -> None:
    with pytest.raises(_Stop):
        asyncio.run(_fetch_once("de-DE"))

    # The guard's proxy, no downloads, and the request's locale with its region's zone (owner P8); no user agent,
    # client hints or headers.
    assert {k: v for k, v in recorder.context.items() if k in ("locale", "timezone_id")} == {
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
    }
    assert set(recorder.context) == {"proxy", "accept_downloads", "locale", "timezone_id"}
