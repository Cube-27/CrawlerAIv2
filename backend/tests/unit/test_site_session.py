"""Site sessions (INV-29's one exception, owner #58): the cookies of a browser solve go with later HTTP and JSON fetches
of the same site, registrable domain and proxy pool, in memory, for a bounded time and number of fetches, and never
into a capture; a `blocked` answer ends the session.

The HTTP and JSON rungs run against a local server on 127.0.0.1 under `.test` hosts; the rung selection runs with stub
rungs. No live network.
"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.session import (
    SESSION_FETCHES,
    SESSION_TTL,
    CookieExport,
    SessionCookie,
    SiteSessions,
    browser_cookies,
)
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.adapters.challenges import SIGNATURES
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
_REFUSAL = b"<html><body><script>location.reload()</script></body></html>"


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


@pytest.mark.parametrize(
    ("cookies", "sent"),
    [((), IDENTITY), ((cookie("tracker", "other.test"),), IDENTITY), ((cookie("c", "example.test"),), IDENTITY[1:])],
    ids=["no_cookie", "no_cookie_of_the_domain", "no_user_agent"],
)
def test_no_session_opens_without_a_cookie_of_the_domain_or_a_user_agent(
    cookies: tuple[SessionCookie, ...], sent: tuple[tuple[str, str], ...]
) -> None:
    sessions = SiteSessions()

    assert sessions.open(f"https://{SITE}/", None, CookieExport(cookies), sent) is None
    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is None


def test_inv29_a_session_serves_only_its_own_site_and_proxy_pool() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),), pool="dc")

    # Another site of the same registrable domain, the same site without the pool or through another, and the site.
    assert sessions.take("https://www.example.test/", "https://www.example.test/", "dc") is None
    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is None
    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", "eu") is None
    assert sessions.take(f"https://{SITE}/p", f"https://{SITE}/p", "dc") is not None


def test_inv29_a_request_outside_the_registrable_domain_gets_no_session() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))

    assert sessions.take(f"https://{SITE}/", "https://api.other.test/v1", None) is None
    assert sessions.take(f"https://{SITE}/", "https://api.example.test/v1", None) is not None


def test_a_session_ends_after_its_time() -> None:
    clock = Clock()
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),), clock=clock)

    clock.now += SESSION_TTL.total_seconds() - 1
    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is not None
    clock.now += 1
    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is None


def test_a_session_serves_a_bounded_number_of_fetches() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))

    served = [sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) for _ in range(SESSION_FETCHES + 1)]

    assert sum(session is not None for session in served) == SESSION_FETCHES
    assert served[-1] is None


@pytest.mark.parametrize(("block_class", "kept"), [("blocked", False), ("shell", True), ("ok", True), ("error", True)])
def test_a_blocked_fetch_ends_a_session_that_has_carried_the_site(block_class: BlockClass, kept: bool) -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))
    sessions.settle(sessions.take(f"https://{SITE}/", f"https://{SITE}/", None), outcome("ok"))
    session = sessions.take(f"https://{SITE}/", f"https://{SITE}/", None)

    sessions.settle(session, outcome(block_class, status=403 if block_class == "blocked" else 200))

    assert (sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is not None) is kept
    # Its cookies lapsed: the next solve opens a new session.
    assert sessions.open(f"https://{SITE}/", None, CookieExport((cookie("c", "example.test"),)), IDENTITY) is not None


@pytest.mark.parametrize("refusal", ["blocked", "shell"])
def test_a_session_refused_before_it_carried_the_site_opens_no_other_for_a_while(refusal: BlockClass) -> None:
    clock = Clock()
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),), clock=clock)
    export = CookieExport((cookie("c", "example.test"),))

    sessions.settle(sessions.take(f"https://{SITE}/", f"https://{SITE}/", None), outcome(refusal, status=403))

    assert sessions.take(f"https://{SITE}/", f"https://{SITE}/", None) is None
    assert sessions.open(f"https://{SITE}/", None, export, IDENTITY) is None
    assert sessions.open("https://www.example.test/", None, export, IDENTITY) is not None  # another site
    clock.now += SESSION_TTL.total_seconds()
    assert sessions.open(f"https://{SITE}/", None, export, IDENTITY) is not None


def test_a_session_that_serves_an_ok_after_a_concurrent_refusal_lifts_the_refusal() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))
    first = sessions.take(f"https://{SITE}/", f"https://{SITE}/", None)
    second = sessions.take(f"https://{SITE}/", f"https://{SITE}/", None)  # two fetches in flight on one session

    sessions.settle(first, outcome("shell"))
    sessions.settle(second, outcome("ok"))

    assert sessions.open(f"https://{SITE}/", None, CookieExport((cookie("c", "example.test"),)), IDENTITY) is not None


def test_inv29_no_repr_shows_a_cookie_value() -> None:
    sessions = sessions_with(f"https://{SITE}/", (cookie("c", "example.test"),))
    session = sessions.take(f"https://{SITE}/", f"https://{SITE}/", None)

    assert COOKIE_VALUE not in repr(session)
    assert COOKIE_VALUE not in repr(sessions)
    assert COOKIE_VALUE not in repr(CookieExport((cookie("c", "example.test"),)))


def test_a_browser_contexts_cookies_keep_their_scope() -> None:
    cookies = browser_cookies(
        [
            {"name": "d", "value": "1", "domain": ".example.test", "path": "/", "expires": -1, "secure": True},
            {"name": "h", "value": "2", "domain": SITE, "path": "/p", "expires": 1900000000.5, "secure": False},
        ]
    )

    assert [(c.name, c.domain, c.host_only, c.path, c.secure, c.expires) for c in cookies] == [
        ("d", "example.test", False, "/", True, None),
        ("h", SITE, True, "/p", False, 1900000000.5),
    ]


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


def json_call(server: Server, page: str, endpoint: str, sessions: SiteSessions) -> FetchResult:
    return asyncio.run(
        fetch_json(
            JsonRequest(endpoint, page),
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


def test_inv29_another_site_of_the_domain_and_a_fetch_without_sessions_send_no_session_cookie(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))

    other = http(server, server.url("/p", host="www.example.test"), sessions)
    plain = http(server, server.url("/p"), None)

    assert (other.block_class, plain.block_class) == ("ok", "ok")
    assert [sent(server, i, "cookie") for i in range(2)] == [None, None]
    assert sent(server, 1, "user-agent") != UA


def test_inv29_a_redirect_out_of_the_domain_carries_no_session_cookie(server: Server) -> None:
    server.route("/go", Reply(302, (("Location", server.url("/p", host="shop.other.test")),)))
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))

    http(server, server.url("/go"), sessions)

    assert [sent(server, i, "cookie") for i in range(2)] == [f"clearance={COOKIE_VALUE}", None]


def test_a_blocked_answer_ends_the_session(server: Server) -> None:
    server.route("/p", Reply(403, (("Content-Type", "text/html"),), _REFUSAL))
    sessions = sessions_with(server.url("/"), (cookie("clearance", "example.test"),))

    first, second = http(server, server.url("/p"), sessions), http(server, server.url("/p"), sessions)

    assert (first.block_class, second.block_class) == ("blocked", "blocked")
    assert [sent(server, i, "cookie") for i in range(2)] == [f"clearance={COOKIE_VALUE}", None]


def test_a_json_call_of_the_sites_page_carries_the_session_within_its_registrable_domain(server: Server) -> None:
    server.route("/v1", Reply(200, (("Content-Type", "application/json"),), b"{}"))
    page = server.url("/item/1")
    sessions = sessions_with(page, (cookie("clearance", "example.test"),))

    inside = json_call(server, page, server.url("/v1", host="api.example.test"), sessions)
    outside = json_call(server, page, server.url("/v1", host="api.other.test"), sessions)

    assert (inside.block_class, outside.block_class) == ("ok", "ok")
    assert [sent(server, i, "cookie") for i in range(2)] == [f"clearance={COOKIE_VALUE}", None]
    assert [sent(server, i, "user-agent") == UA for i in range(2)] == [True, False]


# --- the browser retry opens it -------------------------------------------------------------------------------------

URL = f"https://{SITE}/item/1"


@dataclass
class Stub:
    """A rung answering `block_class`, its attempt labelled `challenge`; with `export`, it hands over `cookies` as the
    browser's exporting form does, and its request carries the solve's identity."""

    method: CaptureMethod
    block_class: BlockClass
    challenge: str | None = None
    cookies: tuple[SessionCookie, ...] = ()
    calls: list[str] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy, *, export: CookieExport | None = None) -> FetchResult:
        self.calls.append("exporting" if export is not None else "plain")
        if export is not None:
            export.cookies = self.cookies
        status = {"ok": 200, "blocked": 403}.get(self.block_class, 200)
        result = fetch_result(
            url=url,
            method=self.method,
            policy=policy,
            engine_version="test",
            fetched_at=datetime.now(UTC),
            started=0.0,
            exchange=Exchange(url, status, IDENTITY, ()),
            content=Content(body=_PAGE if self.block_class == "ok" else _REFUSAL),
            block_class=self.block_class,
            error=None,
            challenge=self.challenge,
        )
        return result


def retried(http_rung: Stub, browser: Stub, sessions: SiteSessions | None) -> FetchResult:
    rungs = Rungs(http=http_rung, browser=browser, sessions=sessions, exporting=None if sessions is None else browser)
    return asyncio.run(acquire(URL, FetchPolicy(), "http", rungs))


def _attempts(result: FetchResult) -> list[tuple[CaptureMethod, BlockClass, bool]]:
    return [(a.method, a.block_class, a.site_session) for a in result.attempts]


@pytest.mark.parametrize("refusal", ["blocked", "shell"])
def test_a_browser_solve_after_an_http_refusal_opens_the_sites_session(refusal: BlockClass) -> None:
    sessions = SiteSessions()
    browser = Stub("browser", "ok", cookies=(cookie("clearance", "example.test"),))

    result = retried(Stub("http", refusal, challenge="structural"), browser, sessions)

    assert _attempts(result) == [("http", refusal, False), ("browser", "ok", True)]
    assert browser.calls == ["exporting"]
    session = sessions.take(URL, URL, None)
    assert session is not None
    assert (session.identity, [c.name for c in session.cookies]) == (IDENTITY, ["clearance"])
    # In memory only: the attempt's flag is not serialized into the manifest or the `capture` row.
    assert "site_session" not in result.attempts[-1].model_dump(mode="json")


def test_a_challenge_whose_cookies_do_not_serve_plain_http_opens_no_session() -> None:
    unportable = next(signature.vendor for signature in SIGNATURES if not signature.portable)
    sessions = SiteSessions()
    browser = Stub("browser", "ok", cookies=(cookie("clearance", "example.test"),))

    result = retried(Stub("http", "blocked", challenge=unportable), browser, sessions)

    assert _attempts(result) == [("http", "blocked", False), ("browser", "ok", False)]
    assert browser.calls == ["plain"]
    assert sessions.take(URL, URL, None) is None


@pytest.mark.parametrize("browser_outcome", ["blocked", "shell", "error"])
def test_a_browser_attempt_that_is_not_ok_opens_no_session(browser_outcome: BlockClass) -> None:
    sessions = SiteSessions()
    browser = Stub("browser", browser_outcome, cookies=(cookie("clearance", "example.test"),))

    result = retried(Stub("http", "blocked"), browser, sessions)

    assert not any(a.site_session for a in result.attempts)
    assert sessions.take(URL, URL, None) is None


def test_without_site_sessions_the_browser_retry_exports_nothing() -> None:
    browser = Stub("browser", "ok", cookies=(cookie("clearance", "example.test"),))

    result = retried(Stub("http", "blocked"), browser, None)

    assert _attempts(result) == [("http", "blocked", False), ("browser", "ok", False)]
    assert browser.calls == ["plain"]
