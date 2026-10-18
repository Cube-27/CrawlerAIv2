"""Site sessions (INV-29's one exception, owner #58): the cookies of a browser solve go with later HTTP and JSON fetches
of the same site, registrable domain and proxy pool, in memory, for a bounded time and number of fetches, and never
into a capture; a `blocked` answer ends the session.

The HTTP and JSON rungs run against a local server on 127.0.0.1 under `.test` hosts; the rung selection runs with stub
rungs. No live network.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.session import (
    CookieExport,
    SessionCookie,
    SiteSessions,
)
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.settings import IMPERSONATE_DEFAULT
from crawlerai.storage.capture_bundle import encode
from tests.local_server import LoopbackConnector, Reply, Server, serving

SITE = "shop.example.test"
UA = "Mozilla/5.0 (X11; Linux x86_64) Solver/153.0"
IDENTITY = (("User-Agent", UA), ("sec-ch-ua", '"Chromium";v="153"'))
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
    assert sessions.open(url, pool, CookieExport(cookies), IDENTITY) is not None
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


def test_a_session_keeps_only_the_cookies_of_the_sites_registrable_domain() -> None:
    sessions = SiteSessions()
    export = CookieExport(
        (
            cookie("clearance", "example.test"),
            cookie("seen", SITE, host_only=True),
            cookie("tracker", "vendor.other.test"),
            cookie("lookalike", "notexample.test"),
        )
    )

    session = sessions.open(f"https://{SITE}/p", None, export, IDENTITY)

    assert session is not None
    assert (session.site, session.registrable_domain) == (SITE, "example.test")
    assert [c.name for c in session.cookies] == ["clearance", "seen"]


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


def http(server: Server, url: str, sessions: SiteSessions | None) -> FetchResult:
    return asyncio.run(
        fetch_http(
            url,
            FetchPolicy(),
            engine_version="test",
            impersonate=IMPERSONATE_DEFAULT,
            connector=LoopbackConnector(server.port, {}),
            sessions=sessions,
        )
    )


def sent(server: Server, index: int, name: str) -> str | None:
    return next((value for key, value in server.requests[index][1] if key.lower() == name), None)


def test_inv29_a_site_sessions_cookies_and_identity_go_with_the_sites_fetches_and_never_into_a_capture(
    server: Server,
) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))

    result = http(server, server.url("/p"), sessions)

    assert (sent(server, 0, "cookie"), sent(server, 0, "user-agent")) == (f"clearance={COOKIE_VALUE}", UA)
    assert sent(server, 0, "sec-ch-ua") == '"Chromium";v="153"'
    manifest = result.bundle.manifest
    assert ("User-Agent", UA) in manifest.headers.request
    assert all(name.lower() != "cookie" for name, _ in manifest.headers.request)
    assert COOKIE_VALUE.encode() not in encode(result.bundle)


# --- the browser retry opens it -------------------------------------------------------------------------------------
