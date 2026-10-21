"""The browser rung runs Patchright's documented setup (INV-42, INV-43, INV-44; owner #50): the full Chromium build in
headless mode, in a persistent profile with a fixed 1280x720 viewport and no launch argument, the WebRTC policy the
guard needs in the profile's preferences, the browser's own user agent with only its headless token renamed (owner #71
as amended), and no client hints or headers. A fake Playwright records what `open_browser` and `fetch_browser` ask
for; no browser runs.
"""

import asyncio
import json
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
        self.probe: dict[str, Any] = {}
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
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/153.0.0.0 Safari/537.36"
)


class _CdpSession:
    async def send(self, method: str) -> dict[str, str]:
        assert method == "Browser.getVersion"
        return {"userAgent": _OWN_UA}


class _Browser:
    async def new_browser_cdp_session(self) -> _CdpSession:
        return _CdpSession()

    async def close(self) -> None:
        return None


class _Chromium:
    def __init__(self, recorder: _Recorder) -> None:
        self._recorder = recorder

    async def launch(self, **options: Any) -> _Browser:
        self._recorder.probe = options
        return _Browser()

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


def test_inv42_inv43_full_chromium_headless_in_a_profile_with_the_guards_webrtc_policy(recorder: _Recorder) -> None:
    fetching = _fetch_once()
    with pytest.raises(_Stop):
        asyncio.run(fetching)

    # `chromium` is Patchright's full Chromium build (`patchright install --no-shell chromium`), not the headless
    # shell; no launch argument; WebRTC's proxy policy, which the SSRF guard needs (INV-16), is a profile preference.
    assert {k: v for k, v in recorder.launch.items() if k != "proxy"} == {
        "channel": "chromium",
        "headless": True,
        "viewport": {"width": 1280, "height": 720},
        "user_agent": _OWN_UA.replace("HeadlessChrome/", "Chrome/"),
        "accept_downloads": False,
    }
    # The browser started to read its user agent is the same build, and sends nothing around the guard.
    assert recorder.probe == {"channel": "chromium", "headless": True, "proxy": {"server": "socks5://127.0.0.1:9"}}
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

    assert offenders == ["acquire/browser.py:" + str(_line_of("user_agent=session.agent,"))]


def _line_of(text: str) -> int:
    lines = (_SRC / "acquire" / "browser.py").read_text(encoding="utf-8").splitlines()
    return next(number for number, line in enumerate(lines, 1) if line.strip() == text)


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

    assert {path for path, _ in calls} == {"acquire/browser.py"}
    assert evaluated == ["return cast(str, await page.evaluate(DOCUMENT_HTML_JS, isolated_context=True)).encode()"]


def test_inv44_a_profile_sets_only_the_proxy_downloads_viewport_user_agent_and_the_request_locale(
    recorder: _Recorder,
) -> None:
    fetching = _fetch_once("de-DE")
    with pytest.raises(_Stop):
        asyncio.run(fetching)

    # The guard's proxy, no downloads, the fixed viewport, and the request's locale with its region's zone (owner P8);
    # the browser's own user agent, renamed; no client hints or headers.
    assert {k: v for k, v in recorder.launch.items() if k in ("locale", "timezone_id")} == {
        "locale": "de-DE",
        "timezone_id": "Europe/Berlin",
    }
    assert set(recorder.launch) == {
        "channel",
        "headless",
        "viewport",
        "user_agent",
        "proxy",
        "accept_downloads",
        "locale",
        "timezone_id",
    }
