"""Site sessions (INV-29's one exception, owner #58, D-1350): the cookies a browser fetch earned past a refusal that
plain HTTP met, handed to the later HTTP and JSON fetches of the same site through the same proxy endpoint, with the
user agent they were earned under.

A session lives in this process's memory only: it is never stored, logged or captured (`headers.recorded` keeps
cookies out of every capture, and no repr shows a cookie value). It holds the cookies of the site's registrable
domain (RFC 6265 §5.1.3 domain matching, the Public Suffix List's registrable domain), serves fetches whose page is on
the site and whose request is in that domain, for at most `SESSION_TTL` and `SESSION_FETCHES` fetches, and is dropped
when a fetch it served is `blocked`. Sessions are keyed by the site (`site.host`, the page URL's host) and the fetch's
proxy pool; a session keeps the endpoint its cookies were earned through, and serves only requests sent through it.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final
from urllib.parse import urlsplit

from crawlerai.acquire.public_suffix import PublicSuffixes, default_suffixes
from crawlerai.acquire.types import FetchResult
from crawlerai.core.proxy import ProxyEndpoint
from crawlerai.storage.capture_bundle import HeaderList

__all__ = [
    "IDENTITY_HEADERS",
    "SESSION_FETCHES",
    "SESSION_TTL",
    "CookieExport",
    "SessionCookie",
    "SiteSession",
    "SiteSessions",
    "browser_cookies",
    "identity",
]

SESSION_TTL: Final = timedelta(minutes=30)
SESSION_FETCHES: Final = 200
# The request headers that make up the identity a challenge's cookies are bound to: the user agent (RFC 9110 §10.1.5)
# and the low-entropy client hints a browser sends with every request (W3C User-Agent Client Hints §3.1).
IDENTITY_HEADERS: Final = ("user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")
_USER_AGENT = "user-agent"


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


def identity(result: FetchResult) -> HeaderList:
    """The identity headers the fetch's last request sent (`IDENTITY_HEADERS`), as its capture recorded them; empty
    without a user agent, which a session cannot do without."""
    request = result.bundle.manifest.headers.request
    sent = tuple((name, value) for name, value in request if name.lower() in IDENTITY_HEADERS)
    return sent if any(name.lower() == _USER_AGENT for name, _ in sent) else ()


@dataclass
class SiteSession:
    site: str
    registrable_domain: str
    pool: str | None
    proxy: ProxyEndpoint | None
    identity: HeaderList
    cookies: tuple[SessionCookie, ...] = field(repr=False)
    expires_at: float  # on the store's clock
    fetches_left: int


@dataclass
class SiteSessions:
    """The site sessions of one process."""

    clock: Callable[[], float] = time.monotonic
    suffixes: Callable[[], PublicSuffixes] = default_suffixes
    _by_site: dict[tuple[str, str | None], SiteSession] = field(default_factory=dict, repr=False)

    def open(self, url: str, pool: str | None, export: CookieExport, sent: HeaderList) -> SiteSession | None:
        """A session for the site of `url` through `pool`, from the cookies of `export` that belong to its registrable
        domain and the identity headers `sent`; it replaces the site's earlier one. None, and no session, when no
        cookie belongs to the domain or `sent` has no user agent."""
        site = _host(url)
        domain = self.suffixes().site(site)
        cookies = tuple(cookie for cookie in export.cookies if _domain_match(cookie.domain, domain))
        if not cookies or not any(name.lower() == _USER_AGENT for name, _ in sent):
            return None
        session = SiteSession(
            site=site,
            registrable_domain=domain,
            pool=pool,
            proxy=export.proxy,
            identity=sent,
            cookies=cookies,
            expires_at=self.clock() + SESSION_TTL.total_seconds(),
            fetches_left=SESSION_FETCHES,
        )
        self._by_site[site, pool] = session
        return session

    def take(self, page_url: str, url: str, pool: str | None) -> SiteSession | None:
        """The live session of the site of `page_url` through `pool` for a request to `url` in its registrable domain,
        one of its fetches spent; None otherwise. A spent or expired session is dropped."""
        key = (_host(page_url), pool)
        session = self._by_site.get(key)
        if session is None:
            return None
        if session.fetches_left <= 0 or self.clock() >= session.expires_at:
            del self._by_site[key]
            return None
        if self.suffixes().site(_host(url)) != session.registrable_domain:
            return None
        session.fetches_left -= 1
        return session

    def settle(self, session: SiteSession | None, result: FetchResult) -> None:
        """Drop `session` when the fetch it served was `blocked`: its cookies no longer pass."""
        if session is not None and result.block_class == "blocked":
            self.drop(session)

    def drop(self, session: SiteSession) -> None:
        key = (session.site, session.pool)
        if self._by_site.get(key) is session:
            del self._by_site[key]


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def _domain_match(cookie_domain: str, domain: str) -> bool:
    """RFC 6265 §5.1.3: the cookie's domain is the registrable domain or a subdomain of it."""
    return cookie_domain == domain or cookie_domain.endswith("." + domain)
