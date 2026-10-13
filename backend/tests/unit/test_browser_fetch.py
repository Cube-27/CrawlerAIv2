"""Browser fetch (SPEC-02 §4.8, §4.5): a JS-only page is rendered, the JSON it loads is captured within the caps, every
connection passes the SSRF guard, and the browser presents one consistent identity.

A local server on 127.0.0.1 serves synthetic pages under `.test` hosts; no live network. The connector admits only
those hosts (and the server's own address) at the server's port; every other name goes through the real guard with
a stub resolver. One browser serves the whole module, as one serves a worker process.

The browser runs with Playwright's own forced proxying of loopback turned off, so the loopback and link-local tests
prove that `fetch_browser` itself keeps those destinations behind the guard.
"""

import asyncio
import gzip
import json
import os
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlsplit

import pytest
from patchright.async_api import Error as PlaywrightError

from crawlerai.acquire.browser import BrowserSession, fetch_browser, open_browser
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.storage.capture_bundle import decode, encode

pytestmark = pytest.mark.browser

_HTML = "text/html; charset=utf-8"
_JSON = "application/json"
_APP = b"""<html><body><div id="root"></div><script>
fetch('/api/items').then(r => r.json()).then(items => {
  let html = '';
  for (const item of items) html += '<p>' + item['name'] + '</p>';
  document.getElementById('root').innerHTML = html;
  return Promise.all([fetch('/api/note'), fetch('/style.css')]);
});
</script></body></html>"""
# Enough rendered text that the page is not a shell (SPEC-02 §4.3: 200 visible characters).
_ITEMS = json.dumps([{"name": f"Catalogue item {i} with a short description"} for i in range(12)]).encode()
_MANY = b"""<html><body><p id="done"></p><script>
(async () => {
  await fetch('/api/big');
  for (let i = 0; i < 55; i++) await fetch('/api/n/' + i);
  document.getElementById('done').textContent = 'loaded';
})();
</script></body></html>"""
_BUSY = b"""<html><body><p>Polling page</p><script>
setInterval(() => fetch('/api/n/0'), 100);
</script></body></html>"""


@dataclass(frozen=True)
class Reply:
    status: int = 200
    content_type: str = _HTML
    body: bytes = b""
    headers: tuple[tuple[str, str], ...] = ()
    delay_s: float = 0.0  # before the status line


@dataclass
class Server:
    port: int
    routes: dict[str, Reply] = field(default_factory=dict)
    requests: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)  # (host, path, headers)

    def url(self, path: str, host: str = "shop.example.test") -> str:
        return f"http://{host}:{self.port}{path}"


def _reply_for(server: Server, path: str) -> Reply:
    if path in server.routes:
        return server.routes[path]
    if path.startswith("/api/n/"):
        return Reply(content_type=_JSON, body=json.dumps({"n": int(path.rsplit("/", 1)[1])}).encode())
    return Reply(404, body=b"<html><body>not here</body></html>")


@pytest.fixture(scope="module")
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            srv = state[0]
            srv.requests.append((self.headers.get("Host", ""), self.path, dict(self.headers.items())))
            reply = _reply_for(srv, self.path)
            time.sleep(reply.delay_s)
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            for name, value in reply.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.write(reply.body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    srv = Server(port=httpd.server_address[1])
    srv.routes.update(
        {
            "/app": Reply(body=_APP, headers=(("Set-Cookie", "session=s1"),)),
            "/api/items": Reply(content_type=_JSON, body=_ITEMS),
            "/api/note": Reply(content_type="text/plain", body=b"plain text"),
            "/style.css": Reply(content_type="text/css", body=b"p { color: black }"),
            "/api/big": Reply(content_type=_JSON, body=b"[" + b"0," * 1_100_000 + b"0]"),
            "/many": Reply(body=_MANY),
            "/busy": Reply(body=_BUSY),
            "/stall": Reply(body=b"<html></html>", delay_s=8),
            "/hop": Reply(302, headers=(("Location", "/app"),)),
            "/hop-private": Reply(302, headers=(("Location", "http://internal.example.com/"),)),
        }
    )
    state.append(srv)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv
    httpd.shutdown()
    httpd.server_close()


class LocalConnector(SafeConnector):
    """Admits `.test` hosts and 127.0.0.1 at the server's port, pinned to 127.0.0.1; everything else goes through
    the real guard, where `internal.example.com` resolves to a private address."""

    def __init__(self, port: int) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            if host != "internal.example.com":
                raise OSError("no such host")
            return [ip_address("10.0.0.1")]

        super().__init__(resolve)
        self._port = port

        self.refused: list[tuple[str, int | None]] = []  # (host, port) of every URL the guard refused

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (host.endswith(".test") or host == "127.0.0.1") and parts.port == self._port:
            return Target(url=url, host=host, port=self._port, ip=IPv4Address("127.0.0.1"))
        try:
            return await super().check(url)
        except SsrfRejected:
            self.refused.append((host, parts.port))
            raise


@dataclass
class Browser:
    runner: asyncio.Runner
    session: BrowserSession
    port: int

    connector: LocalConnector | None = None  # the last fetch's

    def fetch(self, url: str, policy: FetchPolicy | None = None) -> FetchResult:
        self.connector = LocalConnector(self.port)
        return self.runner.run(
            fetch_browser(
                url,
                policy or FetchPolicy(browser_timeout_s=10),
                session=self.session,
                engine_version=ENGINE_VERSION,
                connector=self.connector,
            )
        )


@pytest.fixture(scope="module")
def browser(server: Server) -> Iterator[Browser]:
    with pytest.MonkeyPatch.context() as env, asyncio.Runner() as runner:
        # Read by the Playwright driver when it starts (crBrowser `shouldProxyLoopback`).
        env.setenv("PLAYWRIGHT_DISABLE_FORCED_CHROMIUM_PROXIED_LOOPBACK", "1")
        opened = open_browser()
        try:
            session = runner.run(opened.__aenter__())
        except PlaywrightError as e:
            if os.environ.get("CI") or "Executable doesn't exist" not in e.message:
                raise
            pytest.skip("Chromium is not installed: run `uv run patchright install chromium`")
        try:
            yield Browser(runner, session, server.port)
            # Each fetch closes its own context, so none is left open between tests.
            assert session.browser.contexts == []
        finally:
            runner.run(opened.__aexit__(None, None, None))
        assert not session.browser.is_connected()


def test_js_only_page_is_rendered_and_its_json_captured(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/app"))

    assert (result.method, result.block_class, result.bundle.manifest.status_code) == ("browser", "ok", 200)
    assert b"<p>Catalogue item 0 with a short description</p><p>Catalogue item 1 with" in result.bundle.body
    assert result.bundle.raw_body == _APP
    entries = result.bundle.manifest.network_bodies
    assert [(e.url, e.status, e.content_type, e.file) for e in entries] == [
        (server.url("/api/items"), 200, _JSON, "network/0001.json")
    ]
    assert result.bundle.network == (_ITEMS,)
    assert decode(encode(result.bundle)) == result.bundle


def test_attempt_and_manifest_record_the_outcome(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/app"))

    (attempt,) = result.attempts
    assert (attempt.method, attempt.status, attempt.block_class, attempt.error) == ("browser", 200, "ok", None)
    manifest = result.bundle.manifest
    assert manifest.final_url == server.url("/app")
    assert manifest.timings_ms["total"] == result.duration_ms
    assert 0 < manifest.timings_ms["context"] <= result.duration_ms
    assert ("Content-Type", _HTML) in manifest.headers.response
    # Credentials are not recorded (RFC 6265 §4).
    assert all(name.lower() != "set-cookie" for name, _ in manifest.headers.response)


def test_capture_can_be_turned_off(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/app"), FetchPolicy(capture_network_json=False, browser_timeout_s=10))

    assert b"<p>Catalogue item 0 with a short description</p>" in result.bundle.body
    assert result.bundle.manifest.network_bodies == ()


def test_capture_keeps_the_first_fifty_json_bodies_under_two_megabytes_in_order(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/many"), FetchPolicy(browser_timeout_s=20))

    assert b"loaded" in result.bundle.body
    assert [e.url for e in result.bundle.manifest.network_bodies] == [server.url(f"/api/n/{i}") for i in range(50)]
    assert result.bundle.network[49] == b'{"n": 49}'


def test_redirects_are_followed_within_the_page_host(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/hop"))

    assert result.block_class == "ok"
    assert result.bundle.manifest.final_url == server.url("/app")


def test_redirect_hop_to_a_private_address_is_rejected_after_a_public_first_hop(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/hop-private"))

    (attempt,) = result.attempts
    assert (attempt.block_class, attempt.error) == ("error", "ssrf_rejected: private_address")
    assert (result.bundle.body, result.bundle.raw_body, result.bundle.network) == (b"", None, ())


@pytest.fixture(scope="module")
def other_loopback_server() -> Iterator[Server]:
    """A JSON service on another loopback port, which the connector does not admit."""
    srv: Server | None = None

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            assert srv is not None
            srv.requests.append((self.headers.get("Host", ""), self.path, dict(self.headers.items())))
            self.send_response(200)
            self.send_header("Content-Type", _JSON)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b'{"secret": 1}')

        def log_message(self, format: str, *args: object) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    srv = Server(port=httpd.server_address[1])
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield srv
    httpd.shutdown()
    httpd.server_close()


def _subresources_page(target: str) -> bytes:
    # The page reaches for `target` three ways: fetch, XHR and an iframe.
    return f"""<html><body><p>Page with subresources</p><iframe src="{target}frame"></iframe><script>
fetch('{target}fetch').catch(() => {{}});
const xhr = new XMLHttpRequest(); xhr['open']('GET', '{target}xhr'); xhr['send']();
</script></body></html>""".encode()


@pytest.mark.parametrize(
    ("host", "reason"),
    [
        # RFC 3927 link-local, the cloud metadata address; RFC 1122 §3.2.1.3 loopback. Chromium's implicit proxy
        # bypass rules (`ProxyBypassRules`, net/proxy_resolution) cover both.
        pytest.param("169.254.169.254", "link-local", id="link-local"),
        pytest.param("127.0.0.1", "loopback", id="loopback"),
    ],
)
def test_a_subresource_to_a_loopback_or_link_local_address_is_refused_by_the_guard(
    browser: Browser, server: Server, other_loopback_server: Server, host: str, reason: str
) -> None:
    port = other_loopback_server.port if host == "127.0.0.1" else 80
    target = f"http://{host}:{port}/"
    path = f"/subresources-{reason}"
    server.routes[path] = Reply(body=_subresources_page(target))

    result = browser.fetch(server.url(path), FetchPolicy(browser_timeout_s=10))

    assert result.attempts[0].error is None  # the page itself loads; only its subresources are refused
    assert b"Page with subresources" in result.bundle.body
    assert browser.connector is not None
    # The guard names the port explicitly in the URL it checks.
    assert (host, port) in browser.connector.refused
    assert other_loopback_server.requests == []
    assert result.bundle.manifest.network_bodies == ()


@pytest.mark.parametrize(
    ("url", "error"),
    [
        pytest.param("file:///etc/passwd", "ssrf_rejected: scheme", id="file-scheme"),
        pytest.param("data:text/html,<p>x</p>", "ssrf_rejected: scheme", id="data-scheme"),
        pytest.param("http://internal.example.com/", "ssrf_rejected: private_address", id="private-host"),
        pytest.param("http://169.254.169.254/latest/", "ssrf_rejected: private_address", id="metadata-address"),
    ],
)
def test_a_rejected_first_url_is_never_opened(browser: Browser, url: str, error: str) -> None:
    result = browser.fetch(url)

    (attempt,) = result.attempts
    assert (attempt.status, attempt.block_class, attempt.error) == (None, "error", error)
    assert "context" not in result.bundle.manifest.timings_ms  # no browser context was opened


def test_not_found_is_classified_from_the_navigation_status(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/nowhere"))

    assert (result.block_class, result.bundle.manifest.status_code) == ("not_found", 404)


def test_a_page_that_never_goes_idle_is_read_at_the_hard_cap(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/busy"), FetchPolicy(browser_timeout_s=3, capture_network_json=False))

    assert result.attempts[0].error is None
    assert b"Polling page" in result.bundle.body
    assert 2_000 <= result.duration_ms < 3_500


def test_navigation_that_outlives_the_budget_is_a_timeout(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/stall"), FetchPolicy(browser_timeout_s=2))

    (attempt,) = result.attempts
    assert (attempt.block_class, attempt.error) == ("error", "timeout")
    assert result.duration_ms < 4_000


# --- INV-29: cookies stay inside one fetch -----------------------------------------------------------------------


def test_inv29_a_cookie_set_by_one_fetch_is_absent_from_the_next(browser: Browser, server: Server) -> None:
    first = len(server.requests)
    browser.fetch(server.url("/app"))  # `/app` sets `session=s1`
    second = len(server.requests)
    browser.fetch(server.url("/app"))

    # Within the first fetch the page's own requests carry the cookie; the second fetch starts without it.
    assert ("/api/items", "session=s1") in [(path, _cookie(h)) for _, path, h in server.requests[first:second]]
    assert [(path, _cookie(h)) for _, path, h in server.requests[second:] if path == "/app"] == [("/app", None)]


@pytest.mark.parametrize(
    ("set_cookie", "host", "path", "sent"),
    [
        # RFC 6265 §5.4: a host-only cookie goes to its own host only; `keep`, for the parent domain, does go
        # (§5.1.3 domain-match), so the hop carries cookies at all.
        (("other=1", "keep=1; Domain=example.test"), "cdn.example.test", "/inv29/end", "keep=1"),
        (("other=1", "keep=1; Domain=example.test"), "eu.shop.example.test", "/inv29/end", "keep=1"),
        # §5.3 step 6: a Domain attribute that the setting host does not domain-match is ignored with its cookie.
        (("other=1; Domain=cdn.example.test", "keep=1"), "shop.example.test", "/inv29/end", "keep=1"),
        # §5.1.4: a cookie goes only to request paths its Path matches.
        (("other=1; Path=/private", "keep=1; Path=/"), "shop.example.test", "/inv29/end", "keep=1"),
    ],
    ids=["another_host", "sub_host", "foreign_domain_attribute", "another_path"],
)
def test_inv29_a_cookie_that_does_not_match_the_next_hop_is_not_sent(
    browser: Browser, server: Server, set_cookie: tuple[str, str], host: str, path: str, sent: str
) -> None:
    location = server.url(path, host)
    server.routes["/inv29/start"] = Reply(
        302, headers=(("Location", location), *(("Set-Cookie", c) for c in set_cookie))
    )
    server.routes[path] = Reply(body=b"<html><body><p>Redirect target</p></body></html>")
    first = len(server.requests)

    result = browser.fetch(server.url("/inv29/start"))

    assert result.bundle.manifest.final_url == location
    hop = [h for request_host, p, h in server.requests[first:] if p == path and request_host.startswith(host + ":")]
    assert [_cookie(h) for h in hop] == [sent]


def _cookie(headers: dict[str, str]) -> str | None:
    return next((value for name, value in headers.items() if name.lower() == "cookie"), None)


# --- INV-30: untrusted bodies are bounded --------------------------------------------------------------------------


def test_inv30_a_body_over_the_cap_is_an_error_without_a_body(browser: Browser, server: Server) -> None:
    server.routes["/inv30/large"] = Reply(body=b"<html><body><p>" + b"x" * 50_000 + b"</p></body></html>")

    result = browser.fetch(server.url("/inv30/large"), FetchPolicy(max_body_bytes=10_000, browser_timeout_s=10))

    (attempt,) = result.attempts
    assert (attempt.status, attempt.block_class, attempt.error) == (200, "error", "body_cap")
    assert (result.bundle.body, result.bundle.raw_body, result.bundle.network) == (b"", None, ())


def test_inv30_a_compression_bomb_stops_at_the_decompressed_cap_without_a_body(
    browser: Browser, server: Server
) -> None:
    bomb = gzip.compress(b"<html><body><p>" + b"x" * 5_000_000 + b"</p></body></html>")  # about 5 kB on the wire
    server.routes["/inv30/bomb"] = Reply(body=bomb, headers=(("Content-Encoding", "gzip"),))
    policy = FetchPolicy(max_body_bytes=1_000_000, max_decompressed_bytes=100_000, browser_timeout_s=10)

    result = browser.fetch(server.url("/inv30/bomb"), policy)

    (attempt,) = result.attempts
    assert (attempt.status, attempt.block_class, attempt.error) == (200, "error", "body_cap")
    assert (result.bundle.body, result.bundle.raw_body, result.bundle.network) == (b"", None, ())


def test_user_agent_and_client_hints_name_chrome_and_agree(browser: Browser, server: Server) -> None:
    # 127.0.0.1 is a secure context (W3C Secure Contexts §3.2), where Chromium sends client hints.
    browser.fetch(server.url("/app", host="127.0.0.1"))

    sent = next(h for host, path, h in server.requests if path == "/app" and host.startswith("127.0.0.1"))
    agent = sent["User-Agent"]
    assert "HeadlessChrome" not in agent
    brands = dict(re.findall(r'"([^"]+)";v="(\d+)"', sent["sec-ch-ua"]))
    assert "HeadlessChrome" not in brands
    chrome_major = re.search(r" Chrome/(\d+)\.", agent)
    assert chrome_major is not None
    assert brands["Chromium"] == chrome_major.group(1)
