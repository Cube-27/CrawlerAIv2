"""The browser rung's session (acquisition spec, "HTTP and browser rungs"): one Playwright driver per worker process
(`open_browser`) and one browser per open site profile (`_Profiles`, `acquire.browser_profiles`: a persistent context of
the site's own, not an incognito one). Every connection a profile's browser opens goes through its `SocksGuard`, which
applies the SSRF guard to every redirect hop, frame and worker (§4.5). The caller's cookies (`RequestContext`) are added
to the context before the navigation, as host-only cookies of the URL's host; the caller's headers are never set in the
browser (INV-44).
"""

import asyncio
import contextlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

from patchright._impl._api_structures import SetCookieParam, ViewportSize
from patchright.async_api import BrowserContext, Playwright, async_playwright
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.browser_profiles import Profile, discard_profile, open_profile, profile_name
from crawlerai.acquire.locality import Locality, locality
from crawlerai.acquire.outcome import Exchange, Traffic
from crawlerai.acquire.public_suffix import default_suffixes
from crawlerai.acquire.session import SessionCookie, SiteSessions, browser_cookies
from crawlerai.acquire.shared_browser import BROWSER_CONTEXTS
from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, RequestContext
from crawlerai.core.proxy import ProxyEndpoint

__all__ = ["BrowserSession", "Failed", "context_cookies", "context_key", "open_browser", "open_context"]

# Patchright's documented setup (D-1204, D-1205): the full Chromium build (`chromium`), not the headless shell
# Playwright picks for `headless=True` by default, run in Chromium's own headless mode, with its own client hints and
# no custom headers. Each browser runs in a persistent profile with Playwright's fixed 1280x720 viewport (owner #50 as
# amended 2026-10-21: not the README's `no_viewport`, whose headless window is 800x600), and no launch argument:
# WebRTC's proxy policy is a profile preference (`acquire.browser_profiles`).
_CHANNEL = "chromium"
_VIEWPORT: Final = ViewportSize(width=1280, height=720)
# The one change to the browser's identity (owner #71 as amended 2026-10-21, INV-44): its own user agent, read from the
# browser, with the token headless mode adds (`HeadlessChrome/`) named as a headed browser names it. Set as the
# context's user agent, never the `--user-agent` launch switch.
_HEADLESS_PRODUCT: Final = "HeadlessChrome/"
_HEADED_PRODUCT: Final = "Chrome/"
# The browser started only to read its user agent loads no page; anything it requests in the background goes to this
# closed loopback port and fails, rather than around the guard (INV-16).
_NOWHERE: Final = "socks5://127.0.0.1:9"
# Chromium's implicit proxy-bypass rules (`ProxyBypassRules`, net/proxy_resolution) send `localhost`, 127.0.0.0/8,
# [::1], 169.254.0.0/16 and fe80::/10 around any proxy; 169.254.169.254 is the cloud metadata address. The bypass rule
# `<-loopback>` removes those implicit rules, so they too go through the guard (INV-16). Playwright adds it itself
# unless told not to; it is named here so the guard does not rest on a library default.
_PROXY_ALL_LOOPBACK = "<-loopback>"
# Site profiles a process keeps open (`_Profiles`), rendering or idle: as many as it renders at once, each a browser
# process of its own. An idle one closes after `_PROFILE_IDLE_S`, an unmeasured starting point: the next page of a site
# in a job usually comes within seconds.
_OPEN_PROFILES: Final = BROWSER_CONTEXTS
_PROFILE_IDLE_S = 60.0
# The browser's own user agent, its headless token renamed (`_headed_agent`), read once per process: the installed
# Chromium build does not change while the process runs.
_AGENT: dict[str, str] = {}


class Failed(Exception):
    """A browser fetch that ends as an `error` outcome: the short reason, and the exchange when a response arrived."""

    def __init__(self, error: str, exchange: Exchange | None) -> None:
        super().__init__(error)
        self.error = error
        self.exchange = exchange


@dataclass
class _Context:
    """A site profile's browser (a persistent context), the guard every connection it opens goes through and the
    connector that guard checks with, the bytes the guard has relayed, the locale it was opened with, and what closes
    them and releases the profile. `gone` once its browser closed unasked (it crashed or was killed)."""

    context: BrowserContext
    guard: SocksGuard
    connector: SafeConnector
    traffic: Traffic
    stack: AsyncExitStack
    locale: Locality
    profile: Profile
    closing: bool = False
    gone: bool = False

    async def close(self) -> None:
        self.closing = True
        with contextlib.suppress(PlaywrightError):
            await self.stack.aclose()


# What a profile is (`context_key`): the site, the proxy pool and endpoint.
type ContextKey = tuple[str, str | None, ProxyEndpoint | None]


@dataclass
class _Profiles:
    """The site profiles open in this process (owner #50 as amended 2026-10-21): a site's next page, in any job, opens
    in the profile its earlier pages left, so its cookies, storage and passed challenges carry on, as in one user's
    browser. A profile is taken while a page renders in it, so no two pages share one at once (a second page of the
    site gets a temporary profile, `acquire.browser_profiles`); at most `_OPEN_PROFILES` are open, the least recently
    used idle one closed first, an idle one closes after `_PROFILE_IDLE_S`, and all close with the session. A profile
    whose browser closed unasked is dropped alone (`forget`): the other profiles' renders go on."""

    root: Path | None = None
    idle: OrderedDict[ContextKey, _Context] = field(default_factory=OrderedDict)
    busy: int = 0
    _timers: dict[ContextKey, asyncio.TimerHandle] = field(default_factory=dict)
    _closing: set[asyncio.Task[None]] = field(default_factory=set)

    async def take(self, key: ContextKey, locale: Locality, connector: SafeConnector) -> _Context | None:
        """The idle profile of `key`, now rendering; None when there is none, or it has another locale or guard
        connector (then it is closed)."""
        self._stop_timer(key)
        held = self.idle.pop(key, None)
        if held is not None and (held.locale != locale or held.connector is not connector):
            await held.close()
            held = None
        if held is not None:
            self.busy += 1
        return held

    async def room(self) -> None:
        """Make room for a profile about to open: idle ones are closed, least recently used first, down to the cap."""
        while self.idle and len(self.idle) + self.busy >= _OPEN_PROFILES:
            key, oldest = self.idle.popitem(last=False)
            self._stop_timer(key)
            await oldest.close()
        self.busy += 1

    async def keep(self, key: ContextKey, context: _Context) -> None:
        """`context` stops rendering and is kept idle for the site's next page; a temporary profile opened because the
        site's own was held, or one whose browser is gone, is closed instead, so it never stands in for the site's
        profile."""
        if context.gone or (self.root is not None and context.profile.lock is None):
            await self.release(context)
            return
        self.busy -= 1
        previous = self.idle.pop(key, None)
        if previous is not None:  # two pages of a site rendered at once: the one kept first is closed, never dropped
            self._stop_timer(key)
            await previous.close()
        self.idle[key] = context
        loop = asyncio.get_running_loop()
        self._timers[key] = loop.call_later(_PROFILE_IDLE_S, self._expire, key, context)

    async def discard(self, key: ContextKey) -> None:
        """Delete the profile of `key` (`acquire.browser_profiles.discard_profile`), closing it first when it is idle
        here; one rendering a page stays."""
        self._stop_timer(key)
        held = self.idle.pop(key, None)
        if held is None:
            discard_profile(self.root, profile_name(*key))
            return
        held.profile.discarded = True
        await held.close()

    async def release(self, context: _Context) -> None:
        """`context` stops rendering and closes."""
        self.busy -= 1
        await context.close()

    async def aclose(self) -> None:
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        while self.idle:
            _, context = self.idle.popitem()
            await context.close()
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    def _expire(self, key: ContextKey, context: _Context) -> None:
        self._timers.pop(key, None)
        if self.idle.get(key) is context:
            del self.idle[key]
            self._close_soon(context)

    def forget(self, context: _Context) -> None:
        """`context`'s browser closed unasked: no page may take it again. An idle one is closed now, so its guard
        stops and its profile is released; a rendering one is released when its page ends (`keep`)."""
        context.gone = True
        for key, idle in tuple(self.idle.items()):
            if idle is context:
                del self.idle[key]
                self._stop_timer(key)
                self._close_soon(context)

    def _close_soon(self, context: _Context) -> None:
        """Close `context` from a callback (no await there); `aclose` waits for it."""
        task = asyncio.get_running_loop().create_task(context.close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    def _stop_timer(self, key: ContextKey) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()


@dataclass(frozen=True)
class BrowserSession:
    """A Playwright driver, shared by the fetches of one worker process, the user agent its profiles send (the
    browser's own, its headless token renamed), and the site profiles it keeps open."""

    playwright: Playwright
    agent: str
    profiles: _Profiles = field(default_factory=_Profiles)

    @property
    def alive(self) -> bool:
        """Whether the Playwright driver is still connected (`SharedBrowser` restarts it if not). A profile's browser
        that crashed is dropped on its own (`_Profiles.forget`) and does not end the session."""
        return _driver_connected(self.playwright)


def _driver_connected(playwright: Playwright) -> bool:
    """Playwright has no public driver liveness: its pipe transport sets `on_error_future` once the driver process's
    pipe closes, which fails every call after it."""
    transport = getattr(getattr(playwright, "_impl_obj", None), "_connection", None)
    error = getattr(getattr(transport, "_transport", None), "on_error_future", None)
    return not isinstance(error, asyncio.Future) or not error.done()


@asynccontextmanager
async def open_browser(profiles: Path | None = None) -> AsyncIterator[BrowserSession]:
    """The driver runs until the block ends; leaving it closes its profiles' browsers and the driver process. Site
    profiles are kept under `profiles` (`CRAWLERAI_BROWSER_PROFILES`); without it, each lasts while it is open."""
    async with async_playwright() as playwright:
        session = BrowserSession(playwright, await _headed_agent(playwright), _Profiles(profiles))
        try:
            yield session
        finally:
            await session.profiles.aclose()


async def _headed_agent(playwright: Playwright) -> str:
    """The browser's own user agent (`Browser.getVersion`), its headless token replaced by the headed one; read from a
    browser started for it once per process (`_AGENT`)."""
    if (agent := _AGENT.get(_CHANNEL)) is not None:
        return agent
    browser = await playwright.chromium.launch(channel=_CHANNEL, headless=True, proxy={"server": _NOWHERE})
    try:
        version = await (await browser.new_browser_cdp_session()).send("Browser.getVersion")
    finally:
        await browser.close()
    agent = _AGENT[_CHANNEL] = str(version["userAgent"]).replace(_HEADLESS_PRODUCT, _HEADED_PRODUCT, 1)
    return agent


async def open_context(
    url: str,
    policy: FetchPolicy,
    session: BrowserSession,
    connector: SafeConnector,
    first: Target,
    proxy: ProxyEndpoint | None,
    sessions: SiteSessions | None,
    key: ContextKey | None,
) -> _Context:
    """The site profile of `key` (a temporary one without a key, `acquire.browser_profiles`), launched as a persistent
    context behind a guard of its own, holding the caller's cookies, or, in a temporary profile of the site, the cookies
    `sessions` give (`SiteSessions.for_browser`; a kept profile holds its own), with the request locale's
    `locale` and `timezone_id` (`acquire.locality`). Nothing intercepts its requests: Playwright's request routing
    turns the HTTP cache off, so every request carries `Cache-Control: no-cache` and `Pragma: no-cache`, which no
    user's browser sends on a first load (acquisition spec, "HTTP and browser rungs")."""
    stack = AsyncExitStack()
    traffic = Traffic()
    locale = locality(policy.locale_hint)
    try:
        profile = open_profile(session.profiles.root, None if key is None else profile_name(*key))
        stack.callback(profile.close)  # after the browser has closed, so its last writes are in the profile
        guard = await stack.enter_async_context(
            SocksGuard(connector, checked=(first,), upstream=proxy, traffic=traffic)
        )
        context = await session.playwright.chromium.launch_persistent_context(
            profile.directory,
            channel=_CHANNEL,
            headless=True,
            viewport=_VIEWPORT,
            user_agent=session.agent,
            proxy={"server": guard.url, "bypass": _PROXY_ALL_LOOPBACK},
            accept_downloads=False,
            **locale,
        )
        held = _Context(context, guard, connector, traffic, stack, locale, profile)
        stack.push_async_callback(context.close)
        context.on("close", lambda _: _closed(session, held))
        temporary = profile.lock is None and key is not None
        if temporary and sessions is not None and (seeded := await sessions.for_browser(url, policy.proxy_pool)):
            await context.add_cookies(seeded_cookies(seeded))
        if policy.context is not None and policy.context.cookies:
            await context.add_cookies(caller_cookies(url, policy.context))
    except BaseException as e:
        await stack.aclose()
        # A profile the browser could not open is this fetch's error, not a crashed browser.
        if isinstance(e, PlaywrightError | OSError):
            raise Failed("render_error", None) from e
        raise
    return held


def _closed(session: BrowserSession, held: _Context) -> None:
    """A profile's browser closed: unasked, it crashed or was killed, and only that profile is dropped."""
    if not held.closing:
        session.profiles.forget(held)


def context_key(url: str, policy: FetchPolicy, proxy: ProxyEndpoint | None) -> ContextKey | None:
    """The profile a page renders in (`acquire.browser_profiles`): the page's site (HTML Standard §7.1.1) and the
    proxy pool and endpoint its guard goes through. None for a fetch with the caller's own cookies, which are no
    site's state (acquisition spec, "Cookies stay inside one fetch"): it gets a temporary profile, never kept."""
    host = urlsplit(url).hostname
    if policy.context is not None or host is None:
        return None
    return (default_suffixes().site(host), policy.proxy_pool, proxy)


def caller_cookies(url: str, context: RequestContext) -> list[SetCookieParam]:
    """The caller's cookies as `BrowserContext.add_cookies` takes them: given with `url`, each is a host-only cookie
    of its host for every path (RFC 6265 §5.3 step 6, path `/` from the URL's root)."""
    parts = urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}/"
    return [SetCookieParam(name=name, value=value.get_secret_value(), url=root) for name, value in context.cookies]


def seeded_cookies(cookies: Sequence[SessionCookie]) -> list[SetCookieParam]:
    """Session cookies as `BrowserContext.add_cookies` takes them, each with its own path: a host-only cookie with its
    host as the domain (RFC 6265 §5.3 step 6; as Playwright sets a cookie given with a URL), a `Domain` cookie with its
    domain led by a dot (§5.2.3); a session cookie with no expiry."""
    params: list[SetCookieParam] = []
    for cookie in cookies:
        domain = cookie.domain if cookie.host_only else f".{cookie.domain}"
        param = SetCookieParam(
            name=cookie.name, value=cookie.value, domain=domain, path=cookie.path, secure=cookie.secure
        )
        if cookie.expires is not None:
            param["expires"] = cookie.expires
        params.append(param)
    return params


async def context_cookies(context: BrowserContext) -> tuple[SessionCookie, ...]:
    """Every cookie the context holds, read without changing any (INV-42: nothing is set in the browser); none when
    the context is gone."""
    try:
        return browser_cookies(cast(list[Mapping[str, object]], await context.cookies()))
    except PlaywrightError:
        return ()
