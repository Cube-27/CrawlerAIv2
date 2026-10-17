"""Browser fetch (SPEC-02 §4.8, §4.5): a JS-only page is rendered, the JSON it loads is captured within the caps, every
connection passes the SSRF guard, and the page and its workers present Chromium's own identity.

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
import socket
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
from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.challenges import SIGNATURES
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.proxy import ProxyEndpoint, ProxyPool
from crawlerai.core.proxy_health import QUARANTINE_AFTER
from crawlerai.storage.capture_bundle import decode, encode

pytestmark = pytest.mark.browser

_HTML = "text/html; charset=utf-8"
_JSON = "application/json"
_APP = b"""<html><body><nav><a href="/">Home</a></nav><div id="root"></div><script>
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
_SEARCH = b"""<html><body><p id="done"></p><script>
fetch('/api/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{"q": "lamp"}'})
  .then(r => r.json()).then(() => { document.getElementById('done').textContent = 'searched'; });
</script></body></html>"""
# Data loaded as JSON under other labels: behind a guard prefix, as text/plain, and as an XMLHttpRequest; beside a
# text/plain body that is no JSON, an empty JSON answer and a stylesheet fetched with fetch() (its body is not data).
_SNIFFED = b"""<html><body><p id="done"></p><script>
(async () => {
  await fetch('/api/guarded');
  await fetch('/api/plain-json');
  await fetch('/api/note');
  await fetch('/api/empty');
  await fetch('/style.css');
  await new Promise(done => {
    const x = new XMLHttpRequest(); x.onload = done; x['open']('GET', '/api/linked'); x.send();
  });
  document.getElementById('done').textContent = 'loaded';
})();
</script></body></html>"""
_GUARDED = b")]}'\n" + json.dumps({"items": [{"name": "Guarded item"}]}).encode()
# Six bodies of 1.9 MB each: past 10 MB in all at the sixth.
_HEAVY = b"""<html><body><p id="done"></p><script>
(async () => {
  for (let i = 0; i < 6; i++) await fetch('/api/heavy/' + i);
  document.getElementById('done').textContent = 'loaded';
})();
</script></body></html>"""
_HEAVY_BODY = b'{"pad": "' + b"x" * 1_900_000 + b'"}'
_BUSY = b"""<html><body><p>Polling page</p><p id="tick"></p><script>
let n = 0;
setInterval(() => { fetch('/api/n/0'); document.getElementById('tick').textContent = String(n++); }, 100);
</script></body></html>"""
# Network traffic that never stops under a DOM that stops changing once its text is in.
_STILL = b"""<html><body><p>Polling page with settled content</p><script>
setInterval(() => fetch('/api/n/0'), 100);
</script></body></html>"""
# Static content whose data call answers after the 2 s DOM quiet: the call is still in flight when the content is quiet.
_LATE_CALL = b"""<html><body><p>Static page whose data arrives late</p><script>
fetch('/api/late').then(r => r.json());
</script></body></html>"""
# An error document that replaces itself (`location.replace`, HTML Standard §7.2.4) after a countdown.
_REPLACES_ITSELF = b"""<html><body><p>One moment</p><script>
setTimeout(() => location.replace('/app'), 1000);
</script></body></html>"""

# A page that starts a dedicated worker (HTML Standard §10.2.6), which makes a request of its own.
_WITH_WORKER = b"""<html><body><p>Worker page</p><script>new Worker('/worker.js');</script></body></html>"""

# A 403 document with no site structure (a shell) that navigates on after longer than the 2 s DOM quiet.
_INTERSTITIAL = b"""<html><body><p>One moment</p><script>
setTimeout(() => location.replace('/app'), 4000);
</script></body></html>"""
# A 403 document that stands in for the page and never navigates on within the fetch (a challenge it cannot pass).
_REFUSED = b"<html><body><script>window.__challenge = 1;</script></body></html>"
# A 403 document that is a site page: enough text and hyperlinks (`acquire/classify.py`).
_REFUSAL_PAGE = (
    b"<html><body><nav>"
    + b"".join(b'<a href="/c/%d">Section %d</a>' % (i, i) for i in range(6))
    + b"</nav><p>"
    + b"This page is not available to you. " * 8
    + b"</p></body></html>"
)


# A page three times taller than the browser's viewport, with enough text not to be a shell.
_TALL = (
    b'<html><body><nav><a href="/">Home</a></nav><p>'
    + b"A paragraph of the tall page that is long enough to be read as content. " * 6
    + b"</p>"
    b'<div style="height: 3000px; background: #ccd"></div><p>The end of the tall page.</p></body></html>'
)


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
    if path.startswith("/api/heavy/"):
        return Reply(content_type=_JSON, body=_HEAVY_BODY)
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

        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.do_GET()

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
            "/tall": Reply(body=_TALL),
            "/many": Reply(body=_MANY),
            "/search": Reply(body=_SEARCH),
            "/api/search": Reply(content_type=_JSON, body=b'{"hits": []}'),
            "/sniffed": Reply(body=_SNIFFED),
            "/api/guarded": Reply(content_type="text/plain; charset=utf-8", body=_GUARDED),
            "/api/plain-json": Reply(content_type="text/plain", body=b'[{"id": 1}, {"id": 2}]'),
            "/api/empty": Reply(204, content_type=_JSON),
            "/api/linked": Reply(
                content_type="application/vnd.example+json",
                body=b'{"page": 1}',
                headers=(("Link", '</api/linked?page=2>; rel="next"'), ("Set-Cookie", "session=s2")),
            ),
            "/heavy": Reply(body=_HEAVY),
            "/busy": Reply(body=_BUSY),
            "/still": Reply(body=_STILL),
            "/late-call": Reply(body=_LATE_CALL),
            "/api/late": Reply(content_type=_JSON, body=b'{"late": true}', delay_s=3.5),
            "/replaces-itself": Reply(403, body=_REPLACES_ITSELF),
            "/with-worker": Reply(body=_WITH_WORKER),
            "/worker.js": Reply(content_type="text/javascript", body=b"fetch('/api/n/7');"),
            "/interstitial": Reply(403, body=_INTERSTITIAL),
            "/refusal": Reply(403, body=_REFUSAL_PAGE),
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

    def fetch(
        self,
        url: str,
        policy: FetchPolicy | None = None,
        *,
        export: CookieExport | None = None,
        pools: dict[str, ProxyPool] | None = None,
    ) -> FetchResult:
        self.connector = LocalConnector(self.port)
        return self.runner.run(
            fetch_browser(
                url,
                policy or FetchPolicy(browser_timeout_s=10),
                session=self.session,
                engine_version=ENGINE_VERSION,
                connector=self.connector,
                pools=pools,
                export=export,
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
            pytest.skip("Chromium is not installed: run `uv run patchright install --no-shell chromium`")
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
    assert [(e.url, e.status, e.content_type, e.file, e.method, e.request_body) for e in entries] == [
        (server.url("/api/items"), 200, _JSON, "network/0001.json", "GET", None)
    ]
    assert result.bundle.network == (_ITEMS,)
    assert decode(encode(result.bundle)) == result.bundle


def test_a_listing_rendered_in_the_browser_is_not_judged_by_its_linked_items(browser: Browser, server: Server) -> None:
    # The page's items render as unlinked paragraphs from fetched JSON: the browser is the last rung, so the listing
    # rule (a shell, for the browser to retry) does not apply, and the rows the JSON holds stay extractable.
    result = browser.fetch(server.url("/app"), FetchPolicy(browser_timeout_s=10, page_kind="listing"))

    assert (result.block_class, result.bundle.manifest.fetch_policy["page_kind"]) == ("ok", "listing")


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


def test_capture_records_the_method_body_and_headers_of_the_request_behind_each_json_body(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/search"))

    assert b"searched" in result.bundle.body
    (entry,) = result.bundle.manifest.network_bodies
    assert (entry.url, entry.method, entry.request_body) == (server.url("/api/search"), "POST", '{"q": "lamp"}')
    sent = {name.lower(): value for name, value in entry.request_headers or ()}
    assert (sent["content-type"], sent["referer"]) == ("application/json", server.url("/search"))
    assert decode(encode(result.bundle)) == result.bundle


def test_json_is_kept_by_its_label_or_its_bytes_with_the_response_headers_and_resource_type(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/sniffed"))

    assert b"loaded" in result.bundle.body
    entries = result.bundle.manifest.network_bodies
    assert [(e.url, e.resource_type, e.action) for e in entries] == [
        (server.url("/api/guarded"), "fetch", 0),
        (server.url("/api/plain-json"), "fetch", 0),
        (server.url("/api/linked"), "xhr", 0),
    ]
    # Kept as received; the guard prefix is stripped when the body is read (`network_json`).
    assert result.bundle.network[0] == _GUARDED
    received = dict(entries[2].response_headers or ())
    assert received["Link"] == '</api/linked?page=2>; rel="next"'
    # Credentials are not recorded (RFC 6265 §4).
    assert "set-cookie" not in {name.lower() for name in received}
    assert decode(encode(result.bundle)) == result.bundle


def test_inv30_json_bodies_stop_at_ten_megabytes_per_page(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/heavy"), FetchPolicy(browser_timeout_s=20))

    assert b"loaded" in result.bundle.body
    assert [e.url for e in result.bundle.manifest.network_bodies] == [server.url(f"/api/heavy/{i}") for i in range(5)]


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


def test_a_page_whose_content_settles_is_read_without_waiting_for_its_network(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/still"), FetchPolicy(browser_timeout_s=20, capture_network_json=False))

    assert result.attempts[0].error is None
    assert b"Polling page with settled content" in result.bundle.body
    # Two quiet seconds after `load`, not 90% of the 20 s cap.
    assert 2_000 <= result.duration_ms < 8_000


def test_a_data_call_still_in_flight_when_the_content_is_quiet_is_waited_for(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/late-call"), FetchPolicy(browser_timeout_s=20))

    assert [entry.url for entry in result.bundle.manifest.network_bodies] == [server.url("/api/late")]
    assert result.bundle.network == (b'{"late": true}',)
    # The 2 s quiet passed while the call was in flight; it arrived within the 3 s more a call is given.
    assert 3_500 <= result.duration_ms < 8_000


def test_an_error_document_that_navigates_itself_is_read_where_the_navigation_ends(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/replaces-itself"), FetchPolicy(browser_timeout_s=15))

    manifest = result.bundle.manifest
    assert (result.block_class, manifest.status_code, manifest.final_url) == ("ok", 200, server.url("/app"))
    assert result.bundle.raw_body == _APP
    assert b"<p>Catalogue item 0 with a short description</p>" in result.bundle.body


def test_an_error_document_that_is_a_site_page_is_read_once_quiet(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/refusal"), FetchPolicy(browser_timeout_s=15))

    assert (result.block_class, result.bundle.manifest.status_code) == ("blocked", 403)
    assert result.duration_ms < 5_000


def test_an_interstitial_is_read_where_its_navigation_ends_after_the_quiet_time(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/interstitial"), FetchPolicy(browser_timeout_s=20))

    manifest = result.bundle.manifest
    assert (result.block_class, manifest.status_code, manifest.final_url) == ("ok", 200, server.url("/app"))
    assert b"<p>Catalogue item 0 with a short description</p>" in result.bundle.body


def test_an_interstitial_that_stays_is_read_after_its_share_of_the_budget(browser: Browser, server: Server) -> None:
    server.routes["/forbidden"] = Reply(
        403, body=b"<html><body><p>Access denied</p><script>void 0</script></body></html>"
    )

    result = browser.fetch(server.url("/forbidden"), FetchPolicy(browser_timeout_s=20))

    assert (result.block_class, result.bundle.manifest.status_code) == ("blocked", 403)
    # 40% of the 20 s budget waiting for a navigation, then the 2 s DOM quiet; never the 90% settle share.
    assert 8_000 <= result.duration_ms < 14_000


def test_a_refusal_that_cannot_navigate_is_not_waited_on(browser: Browser, server: Server) -> None:
    # D-1262: no script and no refresh: nothing can replace the document, so only the DOM quiet is waited.
    server.routes["/static-refusal"] = Reply(403, body=b"<html><body><p>Access denied</p></body></html>")

    result = browser.fetch(server.url("/static-refusal"), FetchPolicy(browser_timeout_s=20))

    assert (result.block_class, result.bundle.manifest.status_code) == ("blocked", 403)
    assert result.duration_ms < 6_000


def test_a_refreshing_refusal_with_links_is_read_where_its_refresh_ends(browser: Browser, server: Server) -> None:
    # D-1262: a refresh pragma declares the document navigates on, whatever its links (HTML Standard §4.2.5.3).
    body = _REFUSAL_PAGE.replace(b"<html>", b'<html><head><meta http-equiv="refresh" content="3; url=/app"></head>')
    server.routes["/refreshes"] = Reply(503, body=body)

    started = time.monotonic()
    result = browser.fetch(server.url("/refreshes"), FetchPolicy(browser_timeout_s=20))

    manifest = result.bundle.manifest
    assert (result.block_class, manifest.status_code, manifest.final_url) == ("ok", 200, server.url("/app"))
    # The wait ends with the navigation, not at its 8 s share of the budget.
    assert time.monotonic() - started < 8


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
    assert ("/api/items", "session=s1") in [(path, h.get("Cookie")) for _, path, h in server.requests[first:second]]
    assert [(path, h.get("Cookie")) for _, path, h in server.requests[second:] if path == "/app"] == [("/app", None)]


@pytest.mark.parametrize(
    ("set_cookie", "host"),
    [
        # RFC 6265 §5.4: a host-only cookie goes to its own host only; `keep`, for the parent domain, does go
        # (§5.1.3 domain-match), so the hop carries cookies at all.
        (("other=1", "keep=1; Domain=example.test"), "cdn.example.test"),
        (("other=1", "keep=1; Domain=example.test"), "eu.shop.example.test"),
        # §5.3 step 6: a Domain attribute that the setting host does not domain-match is ignored with its cookie.
        (("other=1; Domain=cdn.example.test", "keep=1"), "shop.example.test"),
        # §5.1.4: a cookie goes only to request paths its Path matches.
        (("other=1; Path=/private", "keep=1; Path=/"), "shop.example.test"),
    ],
    ids=["another_host", "sub_host", "foreign_domain_attribute", "another_path"],
)
def test_inv29_a_cookie_that_does_not_match_the_next_hop_is_not_sent(
    browser: Browser, server: Server, set_cookie: tuple[str, str], host: str
) -> None:
    path = "/inv29/end"
    location = server.url(path, host)
    server.routes["/inv29/start"] = Reply(
        302, headers=(("Location", location), *(("Set-Cookie", c) for c in set_cookie))
    )
    server.routes[path] = Reply(body=b"<html><body><p>Redirect target</p></body></html>")
    first = len(server.requests)

    result = browser.fetch(server.url("/inv29/start"))

    assert result.bundle.manifest.final_url == location
    hop = [h for request_host, p, h in server.requests[first:] if p == path and request_host.startswith(host + ":")]
    assert [h.get("Cookie") for h in hop] == ["keep=1"]


def test_inv29_asked_to_export_the_fetch_hands_over_the_contexts_cookies_and_records_none(
    browser: Browser, server: Server
) -> None:
    export = CookieExport()

    result = browser.fetch(server.url("/app"), export=export)  # `/app` sets `session=s1`

    assert result.block_class == "ok"
    assert [(c.name, c.value, c.domain, c.host_only) for c in export.cookies] == [
        ("session", "s1", "shop.example.test", True)
    ]
    assert export.proxy is None
    assert all(name.lower() not in ("cookie", "set-cookie") for name, _ in result.bundle.manifest.headers.request)


# --- challenges and proxy health (D-1326, D-1324) -------------------------------------------------------------------


def test_a_refused_document_is_labelled_with_the_vendor_whose_cookie_the_context_holds(
    browser: Browser, server: Server
) -> None:
    # The capture records no `Set-Cookie`: the cookie names come from the context, read without changing it.
    signature = next(s for s in SIGNATURES if s.cookie_prefixes)
    name = signature.cookie_prefixes[0]
    server.routes["/refused-labelled"] = Reply(403, body=_REFUSED, headers=(("Set-Cookie", f"{name}=1"),))
    server.routes["/refused"] = Reply(403, body=_REFUSED)

    labelled, structural = browser.fetch(server.url("/refused-labelled")), browser.fetch(server.url("/refused"))

    assert (labelled.block_class, labelled.attempts[0].challenge) == ("blocked", signature.vendor)
    assert (structural.block_class, structural.attempts[0].challenge) == ("blocked", "structural")


def test_a_pool_endpoint_that_no_browser_fetch_gets_through_is_quarantined(browser: Browser, server: Server) -> None:
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
    endpoint = ProxyEndpoint("127.0.0.1", port)
    pools = {"dc": ProxyPool((endpoint,), "rotate")}

    results = [
        browser.fetch(server.url("/app"), FetchPolicy(browser_timeout_s=10, proxy_pool="dc"), pools=pools)
        for _ in range(QUARANTINE_AFTER)
    ]

    assert [(r.attempts[0].status, r.block_class) for r in results] == [(None, "error")] * QUARANTINE_AFTER
    assert not pools["dc"].health.available(endpoint)


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
    bomb = gzip.compress(b"<html><body><p>" + b"x" * 1_000_000 + b"</p></body></html>")  # about 1 kB on the wire
    server.routes["/inv30/bomb"] = Reply(body=bomb, headers=(("Content-Encoding", "gzip"),))
    policy = FetchPolicy(max_body_bytes=1_000_000, max_decompressed_bytes=100_000, browser_timeout_s=10)

    result = browser.fetch(server.url("/inv30/bomb"), policy)

    (attempt,) = result.attempts
    assert (attempt.status, attempt.block_class, attempt.error) == (200, "error", "body_cap")
    assert (result.bundle.body, result.bundle.raw_body, result.bundle.network) == (b"", None, ())


def test_the_page_and_its_worker_present_chromiums_own_identity(browser: Browser, server: Server) -> None:
    # No override (D-1205): the document and a dedicated worker's request carry the same user agent, and its major
    # version is the one the client-hint brands name. 127.0.0.1 is a secure context (W3C Secure Contexts §3.2), where
    # Chromium sends client hints.
    browser.fetch(server.url("/with-worker", host="127.0.0.1"))

    sent = {path: h for host, path, h in server.requests if host.startswith("127.0.0.1")}
    agent = sent["/with-worker"]["User-Agent"]
    assert sent["/api/n/7"]["User-Agent"] == agent
    brands = dict(re.findall(r'"([^"]+)";v="(\d+)"', sent["/with-worker"]["sec-ch-ua"]))
    chrome_major = re.search(r"Chrome/(\d+)\.", agent)
    assert chrome_major is not None
    assert brands["Chromium"] == chrome_major.group(1)


def _png_size(data: bytes) -> tuple[int, int]:
    """The width and height in the IHDR chunk (W3C PNG Third Edition §11.2.2)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_no_file_is_made_of_the_page_unless_the_policy_asks() -> None:
    assert FetchPolicy().captures_page is False


def test_a_viewport_screenshot_is_a_png_of_the_visible_area_and_leaves_the_bundle_as_it_was(
    browser: Browser, server: Server
) -> None:
    result = browser.fetch(server.url("/tall"), FetchPolicy(browser_timeout_s=10, screenshot="viewport"))

    assert list(result.artifacts) == ["screenshot.png"]
    assert _png_size(result.artifacts["screenshot.png"]) == (1280, 720)
    assert decode(encode(result.bundle)) == result.bundle
    assert result.bundle.manifest.fetch_policy["screenshot"] == "viewport"


def test_a_full_page_screenshot_is_as_tall_as_the_page(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/tall"), FetchPolicy(browser_timeout_s=10, screenshot="full_page"))

    width, height = _png_size(result.artifacts["screenshot.png"])
    assert width <= 1280  # less the scroll bar the tall page makes
    assert height > 3000


def test_a_pdf_is_a_print_of_the_page(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/tall"), FetchPolicy(browser_timeout_s=10, pdf=True))

    assert list(result.artifacts) == ["page.pdf"]
    assert result.artifacts["page.pdf"].startswith(b"%PDF-")


def test_a_page_that_was_not_reached_has_no_files(browser: Browser, server: Server) -> None:
    result = browser.fetch(server.url("/missing"), FetchPolicy(browser_timeout_s=10, screenshot="viewport", pdf=True))

    assert (result.block_class, result.artifacts) == ("not_found", {})
