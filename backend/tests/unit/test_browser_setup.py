"""The browser rung runs Patchright's documented setup (INV-42, INV-43, INV-44; owner #50 as amended 2026-10-23):
Google Chrome stable in headless mode, in a persistent profile with a fixed 1280x720 viewport and no launch argument,
the WebRTC policy the guard needs in the profile's preferences, its own user agent with only its headless token renamed
(owner #71 as amended), and no client hints or headers. The context's zone is the egress country's, else the request
locale's region's. A fake Playwright records what `open_browser` and `fetch_browser` ask for; no browser runs.
"""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, cast

import pytest
from patchright.async_api import Playwright

import crawlerai
from crawlerai.acquire import browser_session
from crawlerai.acquire.browser import fetch_browser
from crawlerai.acquire.browser_session import BrowserSession, browser_headers, open_browser
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy
from crawlerai.core.engine_version import ENGINE_VERSION

_SRC = Path(crawlerai.__file__).parent


class _Recorder:
    def __init__(self) -> None:
        self.launch: dict[str, Any] = {}
        self.probe: dict[str, Any] = {}
        self.probes = 0
        self.navigated: list[str] = []
        self.preferences: dict[str, Any] = {}


class _Stop(Exception):
    """Raised where the fake stops: only the launch and context options are under test."""


class _Context:
    def on(self, _event: str, _handler: object) -> None:
        return None

    async def new_page(self) -> object:
        raise _Stop

    async def close(self) -> None:
        return None


_OWN_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/156.0.0.0 Safari/537.36"
)
# What the browser's navigation carries as Playwright's routing reads it (synthetic values); `priority` names nothing.
_SENT = {
    "user-agent": _OWN_UA,
    "sec-ch-ua": '"Chromium";v="156", "Google Chrome";v="156", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Linux"',
    "accept": "text/html,*/*;q=0.8",
    "upgrade-insecure-requests": "1",
    "priority": "u=0, i",
}


class _Request:
    async def all_headers(self) -> dict[str, str]:
        return _SENT


class _Route:
    request = _Request()

    async def fulfill(self, **_options: Any) -> None:
        return None


class _Page:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder
        self._handlers: dict[str, Any] = {}

    async def route(self, url: str, handler: Any) -> None:
        self._handlers[url] = handler

    async def goto(self, url: str) -> None:
        self._recorder.navigated.append(url)
        await self._handlers[url](_Route())


class _Browser:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def new_page(self) -> _Page:
        return _Page(self._recorder)

    async def close(self) -> None:
        return None


class _Chromium:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def launch(self, **options: Any) -> _Browser:
        self._recorder.probe = options
        self._recorder.probes += 1
        return _Browser(self._recorder)

    async def launch_persistent_context(self, user_data_dir: Path, **options: Any) -> _Context:
        self._recorder.launch = options
        self._recorder.preferences = json.loads((user_data_dir / "Default" / "Preferences").read_text())
        return _Context()


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

    monkeypatch.setattr(browser_session, "async_playwright", fake_playwright)
    monkeypatch.setattr(browser_session, "_HEADERS", {})  # the headers are read once per process
    return recorded


async def _fetch_once(locale: str | None = None, country: str | None = None) -> None:
    async with open_browser(country=country) as session:
        assert isinstance(session, BrowserSession)
        await fetch_browser(
            "http://shop.example.test/item",
            FetchPolicy(browser_timeout_s=5, locale_hint=locale),
            session=session,
            engine_version=ENGINE_VERSION,
            connector=_Connector(),
        )


def test_inv42_inv43_chrome_headless_in_a_profile_with_the_guards_webrtc_policy(recorder: _Recorder) -> None:
    fetching = _fetch_once()
    with pytest.raises(_Stop):
        asyncio.run(fetching)

    # `chrome` is Google Chrome stable (`patchright install chrome`), Patchright's recommended build; no launch
    # argument; WebRTC's proxy policy, which the SSRF guard needs (INV-16), is a profile preference.
    assert {k: v for k, v in recorder.launch.items() if k != "proxy"} == {
        "channel": "chrome",
        "headless": True,
        "viewport": {"width": 1280, "height": 720},
        "user_agent": _OWN_UA.replace("HeadlessChrome/", "Chrome/"),
        "accept_downloads": False,
    }
    # The browser started to read its headers is the same build, loads no site and sends nothing around the guard.
    assert recorder.probe == {"channel": "chrome", "headless": True, "proxy": {"server": "socks5://127.0.0.1:9"}}
    assert recorder.navigated == ["https://browser.invalid/"]
    # Read once per process: a session opened again (a restart) starts no second browser.
    with pytest.raises(_Stop):
        asyncio.run(_fetch_once())
    assert recorder.probes == 1
    assert recorder.preferences["webrtc"] == {
        "ip_handling_policy": "disable_non_proxied_udp",
        "multiple_routes_enabled": False,
        "nonproxied_udp_enabled": False,
    }


# Calls that change the browser's identity or run code in the page's main world (Patchright README: no custom
# user agent or headers; evaluate runs in an isolated world). Matched in source, so a new call site fails here; the one
# allowed is the profile's own user agent with its headless token renamed (owner #71 as amended).
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

    assert offenders == ["acquire/browser_session.py:" + str(_line_of("user_agent=session.agent,"))]


def _line_of(text: str) -> int:
    lines = (_SRC / "acquire" / "browser_session.py").read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, 1) if line.strip() == text)


def test_the_http_rungs_read_the_naming_headers_with_the_user_agent_renamed(recorder: _Recorder) -> None:
    headers = asyncio.run(browser_headers(cast(Playwright, _Playwright(recorder))))

    # What the profiles send, so the HTTP and JSON rungs name the same browser (`acquire.impersonate`).
    named = {name: value for name, value in _SENT.items() if name != "priority"}
    assert headers == tuple({**named, "user-agent": _OWN_UA.replace("HeadlessChrome/", "Chrome/")}.items())


def test_open_shadow_roots_are_serialized_by_get_html_in_the_isolated_world_only() -> None:
    """Acquisition spec, "Rendered HTML": the render serializes open shadow roots with `getHTML`, called through
    `evaluate` in Patchright's isolated world, and nowhere else (no init script, user agent or extra headers)."""
    calls = [
        (path.relative_to(_SRC).as_posix(), line.strip())
        for path in sorted(_SRC.rglob("*.py"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if "getHTML" in line or "DOCUMENT_HTML_JS" in line
    ]
    evaluated = [line for _, line in calls if "evaluate(" in line]

    assert {path for path, _ in calls} == {"acquire/browser_capture.py"}
    assert evaluated == ["return cast(str, await page.evaluate(DOCUMENT_HTML_JS, isolated_context=True))"]


@pytest.mark.parametrize(
    ("country", "zone"),
    [(None, "Europe/Berlin"), ("JP", "Asia/Tokyo"), ("US", None)],
    ids=["locale-region", "egress-country", "egress-country-of-many-zones"],
)
def test_inv44_a_profile_sets_only_the_proxy_downloads_viewport_and_the_locality(
    recorder: _Recorder, country: str | None, zone: str | None
) -> None:
    fetching = _fetch_once("de-DE", country)
    with pytest.raises(_Stop):
        asyncio.run(fetching)

    # The guard's proxy, no downloads, the fixed viewport, the request's locale, and the zone of the machine's declared
    # egress country, else of the locale's region (owner P8); a country of several zones sets none (the machine's).
    # The browser's own user agent, renamed; no client hints or headers.
    zoned = {} if zone is None else {"timezone_id": zone}
    assert {k: v for k, v in recorder.launch.items() if k in ("locale", "timezone_id")} == {"locale": "de-DE", **zoned}
    assert set(recorder.launch) == {
        "channel",
        "headless",
        "viewport",
        "user_agent",
        "proxy",
        "accept_downloads",
        "locale",
        *zoned,
    }
