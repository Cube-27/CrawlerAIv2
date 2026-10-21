"""Site sessions (INV-29's one exception, owner #58, D-1350; one cookie rule, owner #76): the cookies a browser fetch of
a site held, handed to the later HTTP and JSON fetches of the same site (browser to HTTP only: nothing an HTTP response
sets is ever handed on).

A live session is the cookies a browser fetch earned past a refusal that plain HTTP met, in this process's memory
only, for the same proxy endpoint. The HTTP and JSON rungs send them with their own identity (the impersonation's
user agent and client hints), never the browser's: a header copied from the browser would pair a browser's user agent
with curl's TLS and HTTP/2 fingerprint. Challenge and clearance cookies go with the rest (owner #76: a clearance a
browser earned may be reused). No cookie is logged or captured (`headers.recorded` keeps cookies out of every capture,
and no repr shows a cookie value).

The browser's own cookie state is its site profile (`acquire.browser_profiles`). Behind it is the stored cookie state
(`acquire.cookie_store`, encrypted), which only a temporary profile uses, on a direct route (no proxy pool): one is
opened when no profile directory is configured or another process holds the site's profile, it starts with the live
session's cookies, else the stored state (`for_browser`, read once, when it opens), and its `ok` writes the stored
state (`after_browser`). A kept profile neither reads nor writes it: it holds its own cookies.

Sessions and the stored state hold the cookies of the site's registrable domain (RFC 6265 §5.1.3 domain matching, the
Public Suffix List's registrable domain), are keyed by it, and serve requests in that domain. A live session lasts at
most `SESSION_TTL` and `SESSION_FETCHES` fetches, and is dropped when a fetch it served is `blocked`; a `blocked`
browser fetch on a direct route drops the stored state too. Sessions are keyed by the registrable domain and the
fetch's proxy pool; a live session keeps the endpoint its cookies were earned through, and serves only requests sent
through it.
"""

import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Protocol
from urllib.parse import urlsplit

from crawlerai.acquire.public_suffix import PublicSuffixes, default_suffixes
from crawlerai.acquire.types import FetchResult
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

    async def load(self, domain: str, engine: BrowserEngine) -> tuple[SessionCookie, ...]: ...

    async def save(self, domain: str, engine: BrowserEngine, cookies: Iterable[SessionCookie]) -> bool: ...

    async def clear(self, domain: str, engine: BrowserEngine) -> None: ...


@dataclass
class SiteSession:
    registrable_domain: str
    pool: str | None
    proxy: ProxyEndpoint | None
    cookies: tuple[SessionCookie, ...] = field(repr=False)
    expires_at: float  # on the store's clock
    fetches_left: int
    passed: bool = False  # it has served an `ok` fetch


@dataclass
class SiteSessions:
    """The site sessions of one process, and the stored cookie state behind its temporary profiles (none without
    `store`)."""

    clock: Callable[[], float] = time.monotonic
    suffixes: Callable[[], PublicSuffixes] = default_suffixes
    store: StoredState | None = None
    _by_domain: dict[tuple[str, str | None], SiteSession] = field(default_factory=dict, repr=False)

    def open(self, url: str, pool: str | None, export: CookieExport) -> SiteSession | None:
        """A session for the site of `url` through `pool`, from the cookies of `export` that belong to its registrable
        domain; it replaces the domain's earlier one. None, and no session, when no cookie is left. A site whose
        sessions keep being refused starts its pages in the browser for a while (`acquire.memory`, block history),
        which opens none."""
        domain = self._domain(url)
        cookies = _in_domain(export.cookies, domain)
        if not cookies:
            return None
        session = SiteSession(
            registrable_domain=domain,
            pool=pool,
            proxy=export.proxy,
            cookies=cookies,
            expires_at=self.clock() + SESSION_TTL.total_seconds(),
            fetches_left=SESSION_FETCHES,
        )
        self._by_domain[domain, pool] = session
        return session

    def take(self, page_url: str, url: str, pool: str | None) -> SiteSession | None:
        """The live session of the site of `page_url` through `pool` for a request to `url` in its registrable domain,
        one of its fetches spent; None otherwise. The stored state never goes with an HTTP or JSON fetch."""
        domain = self._domain(page_url)
        if self._domain(url) != domain:
            return None
        session = self._live((domain, pool))
        if session is not None:
            session.fetches_left -= 1
        return session

    async def for_browser(self, url: str, pool: str | None) -> tuple[SessionCookie, ...]:
        """The cookies a temporary profile for `url` through `pool` starts with, read once as it opens: on a direct
        route, the site's live session's (one of its fetches spent), else its stored state's; none through a pool,
        whose endpoint the browser picks for itself, so a session's cookies could leave through another one."""
        if pool is not None:
            return ()
        domain = self._domain(url)
        if (session := self._live((domain, pool))) is not None:
            session.fetches_left -= 1
            return session.cookies
        if self.store is None:
            return ()
        return _in_domain(await self.store.load(domain, ENGINE), domain)

    async def after_browser(
        self, url: str, pool: str | None, cookies: Sequence[SessionCookie], result: FetchResult, *, temporary: bool
    ) -> None:
        """Record how a browser fetch of `url` through `pool` went, its context having held `cookies`: `blocked`
        drops the site's live session and, on a direct route, its stored state (as the site's profile is discarded);
        on a direct route an `ok` makes the cookies of the site's registrable domain its live session's (if it has
        one), and, from a `temporary` profile, its stored state. Any other outcome (a `shell`, an error) writes
        nothing."""
        domain = self._domain(url)
        session = self._by_domain.get((domain, pool))
        if result.block_class == "blocked":
            if session is not None:
                self.drop(session)
            if pool is None and self.store is not None:
                await self.store.clear(domain, ENGINE)
        elif result.block_class == "ok" and pool is None:
            held = _in_domain(cookies, domain)
            if session is not None and held:
                session.cookies = held
            if temporary and self.store is not None:
                await self.store.save(domain, ENGINE, held)

    def settle(self, session: SiteSession | None, result: FetchResult) -> None:
        """Record how the fetch `session` served went. `blocked` drops it: its cookies no longer pass. A session that
        is refused (`shell`) before it served an `ok` never carried the site, so it is dropped too."""
        if session is None:
            return
        if result.block_class == "ok":
            session.passed = True
        elif result.block_class == "blocked" or (result.block_class == "shell" and not session.passed):
            self.drop(session)

    def drop(self, session: SiteSession) -> None:
        key = (session.registrable_domain, session.pool)
        if self._by_domain.get(key) is session:
            del self._by_domain[key]

    def _domain(self, url: str) -> str:
        return self.suffixes().site(_host(url))

    def _live(self, key: tuple[str, str | None]) -> SiteSession | None:
        """The domain's live session; a spent or expired one is dropped."""
        session = self._by_domain.get(key)
        if session is not None and (session.fetches_left <= 0 or self.clock() >= session.expires_at):
            del self._by_domain[key]
            return None
        return session


def _in_domain(cookies: Iterable[SessionCookie], domain: str) -> tuple[SessionCookie, ...]:
    """The cookies of the registrable `domain` (RFC 6265 §5.1.3)."""
    return tuple(cookie for cookie in cookies if _domain_match(cookie.domain, domain))


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _domain_match(cookie_domain: str, domain: str) -> bool:
    """RFC 6265 §5.1.3: the cookie's domain is the registrable domain or a subdomain of it."""
    return cookie_domain == domain or cookie_domain.endswith("." + domain)
