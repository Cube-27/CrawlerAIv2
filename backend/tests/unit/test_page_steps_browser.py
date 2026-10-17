"""The caller's page steps and cookies on the browser rung (D-1433, D-1436 to D-1438) in a real browser: synthetic local
pages whose content appears only after a click, a wait, typing or scrolling, a cookie-gated page, and a password field.

A local server on 127.0.0.1 serves the pages under a `.test` host; nothing leaves the machine. The pages' words are
arbitrary: the steps name elements by selector or text the test writes, never by anything read from a site (C9).
"""

import asyncio
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from typing import Any
from urllib.parse import urlsplit

import pytest
from patchright.async_api import Error as PlaywrightError
from pydantic import SecretStr, TypeAdapter

from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult, RequestContext
from crawlerai.config_ir.page_actions import Action, WaitFor, to_steps
from crawlerai.core.engine_version import ENGINE_VERSION

pytestmark = pytest.mark.browser


def _page(body: str) -> bytes:
    return f"<!doctype html><html><head><title>t</title></head><body><main>{body}</main></body></html>".encode()


_ROUTES = {
    # The details appear only once the control is clicked.
    "/reveal": _page(
        '<a href="/x">home</a><button class="more" onclick="'
        "document.getElementById('d').innerHTML='<p id=shown>hidden details</p>'\">Show details</button>"
        '<div id="d"></div>'
    ),
    # The list is written by a script after 1.5 s.
    "/late": _page(
        '<a href="/x">home</a><ul id="list"></ul><script>setTimeout(() => {'
        "document.getElementById('list').innerHTML = '<li class=item>one</li><li class=item>two</li>';"
        "}, 1500);</script>"
    ),
    # A search box whose text, once Enter is pressed, is echoed into the page.
    "/search": _page(
        '<a href="/x">home</a><input id="q" type="search"><div id="out"></div><script>'
        "document.getElementById('q').addEventListener('keydown', (e) => { if (e.key === 'Enter') "
        "document.getElementById('out').textContent = 'results for ' + e.target.value; });</script>"
    ),
    "/login": _page(
        '<a href="/x">home</a><form><input id="user" type="text"><input id="pw" type="password"></form>'
        '<div id="after"></div>'
    ),
    # Scrolling to the end adds a block, twice.
    "/grow": _page(
        '<a href="/x">home</a><div id="feed" style="height: 3000px">start</div><script>let n = 0;'
        "addEventListener('scroll', () => { if (n < 2 && innerHeight + scrollY >= document.body.scrollHeight - 10) {"
        "n += 1; const d = document.createElement('div'); d.className = 'added'; d.style.height = '3000px';"
        "d.textContent = 'block ' + n; document.body.appendChild(d); } });</script>"
    ),
}


@dataclass
class Server:
    port: int
    cookies: list[str | None] = field(default_factory=list)

    def url(self, path: str) -> str:
        return f"http://shop.example.test:{self.port}{path}"


@pytest.fixture(scope="module")
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            cookie = self.headers.get("Cookie")
            state[0].cookies.append(cookie)
            status, body = 200, _ROUTES.get(path, b"")
            if path == "/members":
                # Gated: the content only with the session cookie.
                gated = cookie is not None and "sid=s3cret" in cookie
                status = 200 if gated else 403
                body = _page('<a href="/x">home</a><p id="inside">members only</p>' if gated else "refused")
            elif not body:
                status, body = 404, b"<html><body>not here</body></html>"
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    state.append(Server(port=httpd.server_address[1]))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield state[0]
    httpd.shutdown()
    httpd.server_close()


class _Local(SafeConnector):
    """Admits `.test` hosts at the server's port, pinned to 127.0.0.1; every other name resolves to nothing."""

    def __init__(self, port: int) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            raise OSError("no such host")

        super().__init__(resolve)
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if (parts.hostname or "").endswith(".test") and parts.port == self._port:
            return Target(url=url, host=parts.hostname or "", port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


_ACTIONS = TypeAdapter(list[Action])


@dataclass
class Browser:
    runner: asyncio.Runner
    session: BrowserSession
    server: Server

    def fetch(
        self,
        path: str,
        actions: list[dict[str, Any]] | None = None,
        *,
        wait_for: WaitFor | None = None,
        cookies: dict[str, str] | None = None,
    ) -> FetchResult:
        context = None
        if cookies:
            context = RequestContext(cookies=tuple((k, SecretStr(v)) for k, v in cookies.items()))
        steps = to_steps(_ACTIONS.validate_python(actions or []), wait_for)
        policy = FetchPolicy(method_hint="browser", browser_timeout_s=20, steps=steps, context=context)
        return self.runner.run(
            fetch_browser(
                self.server.url(path),
                policy,
                session=self.session,
                engine_version=ENGINE_VERSION,
                connector=_Local(self.server.port),
            )
        )


@pytest.fixture(scope="module")
def browser(server: Server) -> Iterator[Browser]:
    with pytest.MonkeyPatch.context() as env, asyncio.Runner() as runner:
        env.setenv("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")
        opened = open_browser()
        try:
            session = runner.run(opened.__aenter__())
        except PlaywrightError as e:
            if os.environ.get("CI") or "Executable doesn't exist" not in e.message:
                raise
            pytest.skip("Chromium is not installed: run `uv run patchright install --no-shell chromium`")
        try:
            yield Browser(runner, session, server)
            assert session.browser.contexts == []
        finally:
            runner.run(opened.__aexit__(None, None, None))


def _outcomes(result: FetchResult) -> list[tuple[str, str]]:
    return [(step.action, step.outcome) for step in result.attempts[-1].steps]


def test_a_click_reveals_content_before_the_page_is_read(browser: Browser) -> None:
    plain = browser.fetch("/reveal")
    clicked = browser.fetch("/reveal", [{"type": "click", "selector": "button.more"}])

    assert b'<p id="shown">' not in plain.bundle.body
    assert b'<p id="shown">hidden details</p>' in clicked.bundle.body
    assert _outcomes(clicked) == [("click", "done")]
    # The steps are recorded with the policy, in the capture's manifest.
    assert FetchPolicy.model_validate(clicked.bundle.manifest.fetch_policy).steps[0].action == "click"


def test_a_click_by_visible_text(browser: Browser) -> None:
    clicked = browser.fetch("/reveal", [{"type": "click", "text": "Show details"}])

    assert b'<p id="shown">hidden details</p>' in clicked.bundle.body


def test_wait_for_a_selector_reads_the_page_once_the_script_wrote_it(browser: Browser) -> None:
    waited = browser.fetch("/late", wait_for="li.item")

    assert waited.bundle.body.count(b'class="item"') == 2
    assert _outcomes(waited) == [("wait", "done")]


def test_typing_and_a_key_press_run_in_order(browser: Browser) -> None:
    result = browser.fetch(
        "/search",
        [{"type": "type", "selector": "#q", "text": "blue lamp"}, {"type": "press", "key": "Enter"}],
    )

    assert b"results for blue lamp" in result.bundle.body
    assert _outcomes(result) == [("type", "done"), ("press", "done")]


def test_typing_into_a_password_field_is_refused_and_ends_the_steps(browser: Browser) -> None:
    result = browser.fetch(
        "/login",
        [
            {"type": "type", "selector": "#pw", "text": "hunter2"},
            {"type": "click", "selector": "#after"},
        ],
    )

    assert _outcomes(result) == [("type", "refused"), ("click", "skipped")]
    assert b"after" in result.bundle.body  # the page is still read, as it is


def test_a_missing_element_is_not_found_within_its_timeout(browser: Browser) -> None:
    result = browser.fetch("/reveal", [{"type": "click", "selector": "#nowhere", "timeout_ms": 500}])

    assert _outcomes(result) == [("click", "not_found")]
    assert b"Show details" in result.bundle.body


def test_scrolling_until_stable_loads_every_block(browser: Browser) -> None:
    result = browser.fetch("/grow", [{"type": "scroll", "until": "stable", "timeout_ms": 15_000}])

    assert result.bundle.body.count(b'class="added"') == 2
    assert _outcomes(result) == [("scroll", "done")]


def test_the_callers_cookie_reaches_a_gated_page_and_no_capture_holds_its_value(browser: Browser) -> None:
    refused = browser.fetch("/members")
    admitted = browser.fetch("/members", cookies={"sid": "s3cret"})

    assert refused.bundle.manifest.status_code == 403
    assert admitted.bundle.manifest.status_code == 200
    assert b"members only" in admitted.bundle.body
    assert "s3cret" not in admitted.bundle.manifest.model_dump_json()
