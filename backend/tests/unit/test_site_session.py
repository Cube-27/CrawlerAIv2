"""Site sessions: the cookies of a browser solve go with later HTTP and JSON fetches
of the same site, registrable domain and proxy pool, in memory, for a bounded time and number of fetches, and never
into a capture; a `blocked` answer ends the session.

The HTTP and JSON rungs run against a local server on 127.0.0.1 under `.test` hosts; the rung selection runs with stub
rungs. No live network.
"""

import asyncio
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from snowcrawl.acquire.browser_session import context_key
from snowcrawl.acquire.http import fetch_http
from snowcrawl.acquire.memory import Remembered
from snowcrawl.acquire.outcome import Content, Exchange, fetch_result
from snowcrawl.acquire.rungs import Rungs, acquire
from snowcrawl.acquire.session import (
    ENGINE,
    CookieExport,
    SessionCookie,
    SiteSessions,
)
from snowcrawl.acquire.types import BlockClass, FetchPolicy, FetchResult, RequestContext
from snowcrawl.core.capture import CaptureMethod
from snowcrawl.core.proxy import SESSION_FETCHES
from snowcrawl.db.models import BrowserEngine
from snowcrawl.storage.capture_bundle import encode
from tests.local_server import LoopbackConnector, Reply, Server, serving
from tests.stand_in import IMPERSONATE

SITE = "shop.example.test"
COOKIE_VALUE = "c1earance-value"
_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_PAGE = f"<html><body><h1>Catalogue</h1>{_LINKS}</body></html>".encode()


def cookie(name: str, domain: str, *, host_only: bool = False, value: str = COOKIE_VALUE) -> SessionCookie:
    return SessionCookie(name, value, domain, "/", secure=False, host_only=host_only, expires=None)


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


def sessions_with(
    url: str, cookies: tuple[SessionCookie, ...], pool: str | None = None, clock: Clock | None = None
) -> SiteSessions:
    sessions = SiteSessions(clock=clock or Clock())
    assert sessions.open(url, pool, CookieExport(cookies)) is not None
    return sessions


def outcome(block_class: BlockClass, *, status: int = 200, method: CaptureMethod = "http") -> FetchResult:
    return fetch_result(
        url=f"https://{SITE}/",
        method=method,
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=0.0,
        exchange=Exchange(f"https://{SITE}/", status, (), ()),
        content=Content(body=b""),
        block_class=block_class,
        error=None,
    )


# --- the store ------------------------------------------------------------------------------------------------------


def test_a_session_keeps_the_cookies_of_the_sites_registrable_domain_clearance_cookies_too() -> None:
    sessions = SiteSessions()
    export = CookieExport(
        (
            cookie("clearance", "example.test"),
            cookie("cf_clearance", "example.test"),
            cookie("seen", SITE, host_only=True),
            cookie("tracker", "vendor.other.test"),
            cookie("lookalike", "notexample.test"),
        )
    )

    session = sessions.open(f"https://{SITE}/p", None, export)

    assert session is not None
    assert session.registrable_domain == "example.test"
    assert [c.name for c in session.cookies] == ["clearance", "cf_clearance", "seen"]


def test_inv29_no_repr_shows_a_cookie_value() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))
    session = sessions.take(f"https://{SITE}/", f"https://{SITE}/", None)

    assert COOKIE_VALUE not in repr(session)
    assert COOKIE_VALUE not in repr(sessions)
    assert COOKIE_VALUE not in repr(CookieExport((cookie("c", "example.test"),)))


# --- the HTTP and JSON rungs ----------------------------------------------------------------------------------------


@pytest.fixture
def server() -> Iterator[Server]:
    yield from serving()


def http(server: Server, url: str, sessions: SiteSessions | None, policy: FetchPolicy | None = None) -> FetchResult:
    policy = policy or FetchPolicy()
    return asyncio.run(
        fetch_http(
            url,
            policy,
            engine_version="test",
            impersonate=IMPERSONATE,
            connector=LoopbackConnector(server.port, {}),
            scope=None if sessions is None else sessions.scope_for(policy),
        )
    )


def sent(server: Server, index: int, name: str) -> str | None:
    return next((value for key, value in server.requests[index][1] if key.lower() == name), None)


def test_inv29_a_site_sessions_cookies_go_with_the_sites_fetches_and_never_into_a_capture(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))

    result = http(server, server.url("/p"), sessions)

    assert sent(server, 0, "cookie") == f"clearance={COOKIE_VALUE}"
    manifest = result.bundle.manifest
    assert all(name.lower() != "cookie" for name, _ in manifest.headers.request)
    assert COOKIE_VALUE.encode() not in encode(result.bundle)


def test_a_callers_context_isolates_the_fetch_from_the_sites_state(server: Server) -> None:
    """A fetch with the caller's own context (RFC 6265 §5.4: a request carries its own store's cookies) sends only the
    caller's cookie, spends no site session, opens none from a browser retry and gets no kept profile."""
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))
    callers = FetchPolicy(context=RequestContext(cookies=(("own", SecretStr("caller-value")),)))
    plain: list[str] = []
    exported: list[str] = []

    async def browser(url: str, policy: FetchPolicy) -> FetchResult:
        plain.append(url)
        return outcome("ok", method="browser")

    async def exporting(url: str, policy: FetchPolicy, *, export: CookieExport | None = None) -> FetchResult:
        exported.append(url)
        return outcome("ok", method="browser")

    async def refused(url: str, policy: FetchPolicy) -> FetchResult:
        return outcome("blocked")

    http(server, server.url("/p"), sessions, callers)
    rungs = Rungs(http=refused, browser=browser, sessions=sessions, exporting=exporting)
    retried = asyncio.run(acquire(server.url("/p"), callers, Remembered(), rungs))

    assert sent(server, 0, "cookie") == "own=caller-value"
    assert not any(attempt.site_session for attempt in retried.attempts)
    assert context_key(server.url("/p"), sessions.scope_for(callers), None) is None
    # The site's own fetch still finds its session whole: the caller's fetches spent none of it.
    site = sessions.scope_for(FetchPolicy())
    assert site is not None
    taken = site.take(server.url("/"), server.url("/p"))
    assert taken is not None
    assert taken.fetches_left == SESSION_FETCHES - 1
    assert (plain, exported) == ([server.url("/p")], [])  # the plain browser rung, never asked to export


# --- the browser retry opens it -------------------------------------------------------------------------------------


# --- the stored cookie state ----------------------------------------------------------------------------------------


@dataclass
class Stored:
    """A stored cookie state in memory (`acquire.cookie_store.CookieStore`'s interface)."""

    states: dict[tuple[str, str], tuple[SessionCookie, ...]] = field(default_factory=dict)

    async def load(self, domain: str, engine: BrowserEngine) -> tuple[SessionCookie, ...]:
        return self.states.get((domain, engine), ())

    async def save(self, domain: str, engine: BrowserEngine, cookies: Iterable[SessionCookie]) -> bool:
        self.states[domain, engine] = tuple(cookies)
        return True

    async def clear(self, domain: str, engine: BrowserEngine) -> None:
        self.states.pop((domain, engine), None)


def test_only_a_temporary_profile_reads_and_writes_the_stored_state_and_http_never_does(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    store = Stored()
    sessions = SiteSessions(store=store)
    held = (
        cookie("session", "example.test", value="s1"),
        cookie("datadome", "example.test"),
        cookie("x", "other.test"),
    )

    def browser(block_class: BlockClass, pool: str | None = None, *, temporary: bool = True) -> None:
        result = outcome(block_class, method="browser")
        asyncio.run(sessions.after_browser(server.url("/p"), pool, held, result, temporary=temporary))

    browser("shell")
    browser("ok", "dc")
    browser("ok", temporary=False)
    assert store.states == {}
    browser("ok")
    assert [c.name for c in store.states["example.test", ENGINE]] == ["session", "datadome"]
    other_host = server.url("/q", host="www.example.test")
    assert [c.name for c in asyncio.run(sessions.for_browser(other_host, None))] == ["session", "datadome"]
    assert asyncio.run(sessions.for_browser(other_host, "dc")) == ()

    http(server, server.url("/p"), sessions)
    assert sent(server, 0, "cookie") is None

    browser("blocked", temporary=False)
    assert store.states == {}
