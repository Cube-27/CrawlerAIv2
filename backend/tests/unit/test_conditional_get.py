"""Conditional GET (SPEC-11 §4.2, §4.6): the HTTP rung sends the validators a URL last answered with, and a 304 is
`unchanged`, with no bundle.

A local server on 127.0.0.1 serves one synthetic page under a `.test` host and answers conditional requests as RFC
9110 §13.1 says; no live network.
"""

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from urllib.parse import urlsplit

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult, Validators
from crawlerai.core.settings import IMPERSONATE_DEFAULT
from crawlerai.db.models import FetchMethod
from crawlerai.recurring.conditional import Unchanged, fetch_unless_unchanged, received
from crawlerai.storage.capture_bundle import HeaderList

POLICY = FetchPolicy()
BODY = b"<html><body><h1>Item</h1>" + b"".join(b'<a href="/i/%d">i</a>' % i for i in range(8)) + b"</body></html>"
ETAG = '"v1"'
LAST_MODIFIED = "Tue, 13 Oct 2026 08:00:00 GMT"
VALIDATORS = Validators(etag=ETAG, last_modified=LAST_MODIFIED)


@dataclass
class Page:
    """One page at `/p` with an entity tag and a modification date, and `/moved`, which redirects to it; `sent` holds
    the request headers of each GET."""

    port: int = 0
    etag: str = ETAG
    last_modified: str = LAST_MODIFIED
    sent: list[dict[str, str]] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://shop.example.test:{self.port}/p"

    @property
    def moved(self) -> str:
        return f"http://shop.example.test:{self.port}/moved"

    def status(self, headers: dict[str, str]) -> int:
        # RFC 9110 §13.1.2, §13.1.3: If-None-Match decides when present (weak comparison); If-Modified-Since only
        # without it.
        if "if-none-match" in headers:
            tags = {tag.strip().removeprefix("W/") for tag in headers["if-none-match"].split(",")}
            return 304 if self.etag.removeprefix("W/") in tags else 200
        if "if-modified-since" in headers:
            return 304 if headers["if-modified-since"] == self.last_modified else 200
        return 200


@pytest.fixture
def page() -> Iterator[Page]:
    state = Page()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            headers = {name.lower(): value for name, value in self.headers.items()}
            state.sent.append(headers)
            if self.path == "/moved":
                self.send_response(301)
                self.send_header("Location", "/p")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = state.status(headers)
            body = BODY if status == 200 else b""
            self.send_response(status)
            self.send_header("ETag", state.etag)
            self.send_header("Last-Modified", state.last_modified)
            self.send_header("Content-Type", "text/html")
            if status == 200:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    state.port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield state
    httpd.shutdown()
    httpd.server_close()


class Loopback(SafeConnector):
    """Admits the `.test` page host, pinned to the local server; anything else goes through the real guard."""

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname == "shop.example.test" and parts.port is not None:
            return Target(url=url, host=parts.hostname, port=parts.port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


async def by_validators(page: Page, validators: Validators | None, url: str | None = None) -> FetchResult:
    return await fetch_http(
        url or page.url,
        POLICY,
        engine_version="test",
        impersonate=IMPERSONATE_DEFAULT,
        connector=Loopback(),
        validators=validators,
    )


def fetch(page: Page, validators: Validators | None = None, url: str | None = None) -> FetchResult:
    return asyncio.run(by_validators(page, validators, url))


def unless_unchanged(page: Page, sent: Validators | None, *, has_record: bool = True) -> FetchResult | Unchanged:
    return asyncio.run(fetch_unless_unchanged(partial(by_validators, page), sent, has_record=has_record))


def conditional(sent: dict[str, str]) -> dict[str, str]:
    return {name: value for name, value in sent.items() if name in {"if-none-match", "if-modified-since"}}


# --- the HTTP rung -----------------------------------------------------------------------------------------------


def test_the_validators_are_sent_as_if_none_match_and_if_modified_since(page: Page) -> None:
    plain = fetch(page)
    result = fetch(page, VALIDATORS)

    assert [conditional(sent) for sent in page.sent] == [
        {},
        {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED},
    ]
    assert plain.bundle.manifest.status_code == 200
    assert (result.bundle.manifest.status_code, result.block_class, result.bundle.body) == (304, "ok", b"")


def test_only_the_validators_known_are_sent(page: Page) -> None:
    fetch(page, Validators(etag=None, last_modified=LAST_MODIFIED))

    assert conditional(page.sent[0]) == {"if-modified-since": LAST_MODIFIED}


def test_the_validators_are_not_sent_past_a_redirect(page: Page) -> None:
    # They describe the URL asked for; another resource's 304 must not stand for it.
    result = fetch(page, VALIDATORS, page.moved)

    assert [conditional(sent) for sent in page.sent] == [
        {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED},
        {},
    ]
    assert (result.bundle.manifest.status_code, result.bundle.body) == (200, BODY)


# --- 304 means unchanged -----------------------------------------------------------------------------------------


def test_a_second_fetch_of_an_unchanged_page_is_unchanged_and_has_no_bundle(page: Page) -> None:
    first = unless_unchanged(page, None)
    assert isinstance(first, FetchResult)
    second = unless_unchanged(page, received(first))

    assert isinstance(second, Unchanged)
    assert [attempt.status for attempt in second.attempts] == [304]
    assert not hasattr(second, "bundle")
    sent_validators = {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED}
    assert [conditional(sent) for sent in page.sent] == [{}, sent_validators]


def test_a_changed_page_is_fetched_with_its_new_validators(page: Page) -> None:
    page.etag, page.last_modified = '"v2"', "Wed, 14 Oct 2026 08:00:00 GMT"
    result = unless_unchanged(page, VALIDATORS)

    assert isinstance(result, FetchResult)
    assert (result.bundle.manifest.status_code, result.bundle.body) == (200, BODY)
    assert received(result) == Validators(etag='"v2"', last_modified="Wed, 14 Oct 2026 08:00:00 GMT")


def test_a_304_with_no_stored_record_is_fetched_again_once_without_validators(page: Page) -> None:
    result = unless_unchanged(page, VALIDATORS, has_record=False)

    assert isinstance(result, FetchResult)
    assert (result.bundle.manifest.status_code, result.bundle.body) == (200, BODY)
    assert [conditional(sent) for sent in page.sent] == [
        {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED},
        {},
    ]


def test_a_failed_304_is_not_unchanged() -> None:
    failed = _result((), status=304, error="timeout")

    async def answer(_validators: Validators | None) -> FetchResult:
        return failed

    assert asyncio.run(fetch_unless_unchanged(answer, VALIDATORS, has_record=True)) is failed


# --- through rung selection --------------------------------------------------------------------------------------


@dataclass
class Browser:
    calls: list[str] = field(default_factory=list)
    result: FetchResult | None = None

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append(url)
        assert self.result is not None
        return self.result


def through_acquire(page: Page, remembered: FetchMethod, browser: Browser) -> FetchResult | Unchanged:
    http = partial(fetch_http, engine_version="test", impersonate=IMPERSONATE_DEFAULT, connector=Loopback())
    rungs = Rungs(http=http, browser=browser, conditional=http)

    async def by_validators(validators: Validators | None) -> FetchResult:
        return await acquire(page.url, POLICY, remembered, rungs, validators=validators)

    return asyncio.run(fetch_unless_unchanged(by_validators, VALIDATORS, has_record=True))


def test_acquire_sends_the_validators_on_the_http_rung(page: Page) -> None:
    result = through_acquire(page, "http", Browser())

    assert isinstance(result, Unchanged)
    assert conditional(page.sent[0]) == {"if-none-match": ETAG, "if-modified-since": LAST_MODIFIED}


def test_the_browser_rung_ignores_the_validators(page: Page) -> None:
    browser = Browser(result=fetch(page))
    page.sent.clear()
    result = through_acquire(page, "browser", browser)

    assert isinstance(result, FetchResult)
    assert (browser.calls, page.sent) == ([page.url], [])


# --- reading validators from a response --------------------------------------------------------------------------

_TOKEN = st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E), min_size=1, max_size=20)


@given(etags=st.lists(_TOKEN, max_size=3), dates=st.lists(_TOKEN, max_size=3), upper=st.booleans())
def test_the_last_etag_and_last_modified_received_are_the_validators(
    etags: list[str], dates: list[str], upper: bool
) -> None:
    def name(value: str) -> str:
        return value.upper() if upper else value

    headers: HeaderList = (
        *((name("ETag"), tag) for tag in etags),
        ("Content-Type", "text/html"),
        *((name("Last-Modified"), date) for date in dates),
    )
    expected = Validators(etag=etags[-1] if etags else None, last_modified=dates[-1] if dates else None)
    assert received(_result(headers)) == expected


def _result(headers: HeaderList, *, status: int = 200, error: str | None = None) -> FetchResult:
    return fetch_result(
        url="https://shop.example.test/p",
        method="http",
        policy=POLICY,
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=0.0,
        exchange=Exchange("https://shop.example.test/p", status, (), headers),
        content=Content(body=b""),
        block_class="ok" if error is None else "error",
        error=error,
    )
