"""Site sessions (INV-29's one exception, owner #58, D-1350): the cookies a browser fetch of a site held, handed to
the later fetches of the same site (browser to HTTP only: nothing an HTTP response sets is ever handed on).

A live session is the cookies a browser fetch earned past a refusal that plain HTTP met, in this process's memory
only, for the same proxy endpoint. The HTTP and JSON rungs send them with their own identity (the impersonation's
user agent and client hints), never the browser's: a header copied from the browser would pair a browser's user agent
with curl's TLS and HTTP/2 fingerprint. Behind it is the site's stored cookie state
(`acquire.cookie_store`), kept across jobs and processes, which serves direct fetches only (no proxy pool): a fetch
takes the live session first, then the stored state. Challenge and clearance cookies
(`adapters.challenges.challenge_cookie`) are in neither: they are never kept nor replayed. No cookie is logged or
captured (`headers.recorded` keeps cookies out of every capture, and no repr shows a cookie value).

Both hold the cookies of the site's registrable domain (RFC 6265 §5.1.3 domain matching, the Public Suffix List's
registrable domain) and serve fetches whose page is on the site and whose request is in that domain. A live session
lasts at most `SESSION_TTL` and `SESSION_FETCHES` fetches, and is dropped when a fetch it served is `blocked`; a
`blocked` fetch on a direct route drops the stored state too. Sessions are keyed by the site (`site.host`, the page
URL's host) and the fetch's proxy pool; a live session keeps the endpoint its cookies were earned through, and serves
only requests sent through it. The stored state is written after a browser `ok` with no challenge
(`after_browser`), and a browser context starts with the session's cookies, else the stored state (`for_browser`).
"""

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Protocol
from urllib.parse import urlsplit

from crawlerai.acquire.public_suffix import PublicSuffixes, default_suffixes
from crawlerai.acquire.types import FetchResult
from crawlerai.adapters.challenges import challenge_cookie
from crawlerai.core.proxy import ProxyEndpoint
from crawlerai.db.models import BrowserEngine

__all__ = [
    "ENGINE",
    "SESSION_FETCHES",
    "SESSION_TTL",
    "CookieExport",
    "SessionCookie",
    "SiteSession",
    "SiteSessions",
    "StoredState",
    "browser_cookies",
]

SESSION_TTL: Final = timedelta(minutes=30)
SESSION_FETCHES: Final = 200
# The engine of the browser rung (`acquire.browser`), whose state the stored cookie state keeps.
ENGINE: Final[BrowserEngine] = "patchright"


@dataclass(frozen=True)
class SessionCookie:
    """One cookie as a browser context holds it (RFC 6265 §5.3 storage model). `host_only` cookies go to `domain`
    alone; `expires` is a Unix time, None for a cookie that ends with the browsing session."""

    name: str
    value: str = field(repr=False)
    domain: str
    path: str
    secure: bool
    host_only: bool
    expires: float | None


def browser_cookies(cookies: Sequence[Mapping[str, object]]) -> tuple[SessionCookie, ...]:
    """A browser context's cookies (Playwright's `BrowserContext.cookies()` shape) as session cookies. A domain with a
    leading dot is a `Domain` cookie (RFC 6265 §5.2.3), any other host-only; a negative `expires` is a session
    cookie."""
    kept: list[SessionCookie] = []
    for cookie in cookies:
        domain = str(cookie.get("domain") or "")
        expires = cookie.get("expires")
        kept.append(
            SessionCookie(
                name=str(cookie.get("name") or ""),
                value=str(cookie.get("value") or ""),
                domain=domain.lstrip(".").lower(),
                path=str(cookie.get("path") or "/"),
                secure=bool(cookie.get("secure")),
                host_only=not domain.startswith("."),
                expires=float(expires) if isinstance(expires, int | float) and expires >= 0 else None,
            )
        )
    return tuple(kept)


@dataclass
class CookieExport:
    """Filled by the browser rung when asked to export (`acquire.rungs.ExportingRung`): the context's cookies, read
    without changing them, and the proxy endpoint its connections went through. Nothing else reads it."""

    cookies: tuple[SessionCookie, ...] = field(default=(), repr=False)
    proxy: ProxyEndpoint | None = None


class StoredState(Protocol):
    """The stored cookie state (`acquire.cookie_store.CookieStore`)."""

    async def load(self, host: str, engine: BrowserEngine) -> tuple[SessionCookie, ...]: ...

    async def save(self, host: str, engine: BrowserEngine, cookies: Iterable[SessionCookie]) -> bool: ...

    async def clear(self, host: str, engine: BrowserEngine) -> None: ...


@dataclass
class SiteSession:
    site: str
    registrable_domain: str
    pool: str | None
    proxy: ProxyEndpoint | None
    cookies: tuple[SessionCookie, ...] = field(repr=False)
    expires_at: float  # on the store's clock
    fetches_left: int
    passed: bool = False  # it has served an `ok` fetch
    stored: bool = False  # the site's stored state, for one fetch


@dataclass
class SiteSessions:
    """The site sessions of one process, and the stored cookie state behind them (none without `store`)."""

    clock: Callable[[], float] = time.monotonic
    suffixes: Callable[[], PublicSuffixes] = default_suffixes
    store: StoredState | None = None
    _by_site: dict[tuple[str, str | None], SiteSession] = field(default_factory=dict, repr=False)

    def open(self, url: str, pool: str | None, export: CookieExport) -> SiteSession | None:
        """A session for the site of `url` through `pool`, from the cookies of `export` that belong to its registrable
        domain, challenge cookies left out; it replaces the site's earlier one. None, and no session, when no cookie is
        left. A site whose sessions keep being refused
        starts its pages in the browser for a while (`acquire.memory`, block history), which opens none."""
        site = _host(url)
        domain = self.suffixes().site(site)
        cookies = _replayable(export.cookies, domain)
        if not cookies:
            return None
        session = SiteSession(
            site=site,
            registrable_domain=domain,
            pool=pool,
            proxy=export.proxy,
            cookies=cookies,
            expires_at=self.clock() + SESSION_TTL.total_seconds(),
            fetches_left=SESSION_FETCHES,
        )
        self._by_site[site, pool] = session
        return session

    async def take(self, page_url: str, url: str, pool: str | None) -> SiteSession | None:
        """The live session of the site of `page_url` through `pool` for a request to `url` in its registrable domain,
        one of its fetches spent; else, on a direct route, the site's stored state as a session for this fetch
        (`stored`); None otherwise."""
        site = _host(page_url)
        session = self._live((site, pool))
        domain = session.registrable_domain if session is not None else self.suffixes().site(site)
        if self.suffixes().site(_host(url)) != domain:
            return None
        if session is not None:
            session.fetches_left -= 1
            return session
        if pool is not None or self.store is None:
            return None
        cookies = _replayable(await self.store.load(site, ENGINE), domain)
        if not cookies:
            return None
        return SiteSession(site, domain, None, None, cookies, self.clock(), 0, stored=True)

    async def for_browser(self, url: str, pool: str | None) -> tuple[SessionCookie, ...]:
        """The cookies a browser context for `url` through `pool` starts with: on a direct route, the site's live
        session's (one of its fetches spent), else its stored state's; none through a pool, whose endpoint the browser
        picks for itself, so a session's cookies could leave through another one."""
        if pool is not None:
            return ()
        site = _host(url)
        if (session := self._live((site, pool))) is not None:
            session.fetches_left -= 1
            return session.cookies
        if self.store is None:
            return ()
        return _replayable(await self.store.load(site, ENGINE), self.suffixes().site(site))

    async def after_browser(
        self, url: str, pool: str | None, cookies: Sequence[SessionCookie], result: FetchResult
    ) -> None:
        """Record how a browser fetch of `url` through `pool` went, its context having held `cookies`: `blocked`
        drops the site's live session and, on a direct route, its stored state; on a direct route, an `ok` with no
        challenge makes the cookies of the site's registrable domain its live session's (if it has one) and its stored
        state. Any other outcome (a `shell`, an error) writes nothing."""
        site = _host(url)
        session = self._by_site.get((site, pool))
        if result.block_class == "blocked":
            if session is not None:
                self.drop(session)
            await self._clear(site, pool)
        elif result.block_class == "ok" and result.attempts[-1].challenge is None and pool is None:
            replayable = _replayable(cookies, self.suffixes().site(site))
            if session is not None and replayable:
                session.cookies = replayable
            if self.store is not None:
                await self.store.save(site, ENGINE, replayable)

    async def settle(self, session: SiteSession | None, result: FetchResult) -> None:
        """Record how the fetch `session` served went. `blocked` drops it, and on a direct route the site's stored
        state: its cookies no longer pass. A live session that is refused (`blocked` or `shell`) before it served an
        `ok` never carried the site, so it is dropped too."""
        if session is None:
            return
        if result.block_class == "blocked":
            await self._clear(session.site, session.pool)
        if session.stored:
            return
        if result.block_class == "ok":
            session.passed = True
        elif result.block_class == "blocked" or (result.block_class == "shell" and not session.passed):
            self.drop(session)

    def drop(self, session: SiteSession) -> None:
        key = (session.site, session.pool)
        if self._by_site.get(key) is session:
            del self._by_site[key]

    def _live(self, key: tuple[str, str | None]) -> SiteSession | None:
        """The site's live session; a spent or expired one is dropped."""
        session = self._by_site.get(key)
        if session is not None and (session.fetches_left <= 0 or self.clock() >= session.expires_at):
            del self._by_site[key]
            return None
        return session

    async def _clear(self, site: str, pool: str | None) -> None:
        if pool is None and self.store is not None:
            await self.store.clear(site, ENGINE)


def _replayable(cookies: Iterable[SessionCookie], domain: str) -> tuple[SessionCookie, ...]:
    """The cookies of the registrable `domain` that may go with a later fetch: no challenge or clearance cookie."""
    return tuple(
        cookie
        for cookie in cookies
        if _domain_match(cookie.domain, domain) and not challenge_cookie(cookie.name, cookie.value)
    )


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _domain_match(cookie_domain: str, domain: str) -> bool:
    """RFC 6265 §5.1.3: the cookie's domain is the registrable domain or a subdomain of it."""
    return cookie_domain == domain or cookie_domain.endswith("." + domain)
