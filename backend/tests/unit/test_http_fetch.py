"""HTTP fetch (SPEC-02 §4.5, §4.7): manual redirects through the SSRF guard, caps, timeouts and the manifest.

A local server on 127.0.0.1 serves synthetic pages under `.test` hosts; no live network. `LoopbackConnector`
admits only those hosts, at the server's port, and sends every other URL through the real guard with a stub
resolver, so redirect hops leaving the server are checked exactly as in production.
"""

import asyncio
import gzip
import socket
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlsplit

import pytest

from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import decode, encode

_LOOPBACK = IPv4Address("127.0.0.1")
_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_PAGE = f"<html><body><h1>Catalogue</h1>{_LINKS}</body></html>".encode()
_SHELL = b'<html><body><div id="root"></div><script>start()</script></body></html>'


@dataclass(frozen=True)
class Reply:
    status: int = 200
    headers: Sequence[tuple[str, str]] = ()
    body: bytes = b""
    delay_s: float = 0.0  # sleep after the headers, before the body


@dataclass
class Server:
    port: int
    routes: dict[str, Callable[[str], Reply]] = field(default_factory=dict)
    requests: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)  # (host + path, headers)

    def url(self, path: str, host: str = "shop.example.test") -> str:
        return f"http://{host}:{self.port}{path}"

    def route(self, path: str, reply: Reply | Callable[[str], Reply]) -> None:
        self.routes[path] = reply if callable(reply) else (lambda _host: reply)


@pytest.fixture
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            srv = state[0]
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            srv.requests.append((host + self.path, list(self.headers.items())))
            reply = srv.routes[self.path](host) if self.path in srv.routes else Reply(404, body=b"no route")
            self.send_response(reply.status)
            for name, value in reply.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.flush()
            time.sleep(reply.delay_s)
            self.wfile.write(reply.body)

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


class LoopbackConnector(SafeConnector):
    """Admits `.test` hosts on the local server's port; everything else goes through the real guard."""

    def __init__(self, port: int, dns: dict[str, str]) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            if host not in dns:
                raise OSError("no such host")
            return [ip_address(dns[host])]

        super().__init__(resolve)
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname and parts.hostname.endswith(".test") and parts.port == self._port:
            return Target(url=url, host=parts.hostname, port=self._port, ip=_LOOPBACK)
        return await super().check(url)


_DNS = {"internal.example.com": "10.0.0.1", "public.example.com": "93.184.215.14"}


def fetch(server: Server, url: str, policy: FetchPolicy | None = None) -> FetchResult:
    connector = LoopbackConnector(server.port, _DNS)
    return asyncio.run(fetch_http(url, policy or FetchPolicy(), engine_version="test", connector=connector))


def outcome(result: FetchResult) -> tuple[int, str, str | None]:
    (attempt,) = result.attempts
    return result.bundle.manifest.status_code, result.block_class, attempt.error


def html(body: bytes, status: int = 200, *extra: tuple[str, str]) -> Reply:
    return Reply(status, (("Content-Type", "text/html; charset=utf-8"), *extra), body)


def redirect(location: str, status: int = 302) -> Reply:
    return Reply(status, (("Location", location),))


# --- a plain fetch -----------------------------------------------------------------------------------------------


def test_a_page_is_fetched_into_a_bundle_through_the_pinned_address(server: Server) -> None:
    # `shop.example.test` resolves nowhere (RFC 2606): the request can only reach the server through the address the
    # connector checked.
    server.route("/p", html(_PAGE))
    result = fetch(server, server.url("/p"))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.status_code, manifest.block_class) == ("http", 200, "ok")
    assert (manifest.url, manifest.final_url) == (server.url("/p"), server.url("/p"))
    assert result.bundle.body == _PAGE
    assert result.attempts == (
        AttemptRecord(method="http", status=200, block_class="ok", duration_ms=result.attempts[0].duration_ms),
    )
    assert manifest.engine_version == "test"
    assert manifest.fetch_policy == FetchPolicy().model_dump(mode="json")
    assert decode(encode(result.bundle)) == result.bundle


def test_the_manifest_records_the_headers_sent_and_received(server: Server) -> None:
    server.route("/p", html(_PAGE, 200, ("X-Served-By", "fixture")))
    manifest = fetch(server, server.url("/p")).bundle.manifest

    sent = dict((name.lower(), value) for name, value in manifest.headers.request)
    received = dict((name.lower(), value) for name, value in server.requests[0][1])
    assert sent["user-agent"] == received["user-agent"]
    assert "Chrome/" in sent["user-agent"]
    assert ("X-Served-By", "fixture") in manifest.headers.response
    assert ("Content-Type", "text/html; charset=utf-8") in manifest.headers.response


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (html(_SHELL), (200, "shell", None)),
        (html(b"gone", 404), (404, "not_found", None)),
        (html(b"slow down", 429, ("Retry-After", "120")), (429, "blocked", None)),
        (html(b"oops", 500), (500, "error", None)),
    ],
)
def test_the_final_response_is_classified(server: Server, reply: Reply, expected: tuple[int, str, None]) -> None:
    server.route("/p", reply)
    assert outcome(fetch(server, server.url("/p"))) == expected


def test_retry_after_is_kept_for_the_backoff(server: Server) -> None:
    server.route("/p", html(b"slow down", 429, ("Retry-After", "120")))
    assert ("Retry-After", "120") in fetch(server, server.url("/p")).bundle.manifest.headers.response


# --- redirects ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_are_followed(server: Server, status: int) -> None:
    server.route("/start", redirect("/middle", status))
    server.route("/middle", redirect(server.url("/end")))
    server.route("/end", html(_PAGE))
    result = fetch(server, server.url("/start"))

    assert outcome(result) == (200, "ok", None)
    assert (result.bundle.manifest.url, result.bundle.manifest.final_url) == (server.url("/start"), server.url("/end"))
    assert result.bundle.body == _PAGE
    assert [r for r, _ in server.requests] == [
        "shop.example.test/start",
        "shop.example.test/middle",
        "shop.example.test/end",
    ]


def test_a_redirect_to_another_host_is_pinned_to_that_hosts_checked_address(server: Server) -> None:
    server.route(
        "/p", lambda host: redirect(server.url("/p", "cdn.example.test")) if host.startswith("shop") else html(_PAGE)
    )
    result = fetch(server, server.url("/p"))
    assert outcome(result) == (200, "ok", None)
    assert result.bundle.manifest.final_url == server.url("/p", "cdn.example.test")
    assert [r for r, _ in server.requests] == ["shop.example.test/p", "cdn.example.test/p"]


def test_five_redirects_are_followed_and_a_sixth_is_an_error(server: Server) -> None:
    for i in range(6):
        server.route(f"/hop{i}", redirect(f"/hop{i + 1}"))
    server.route("/hop6", html(_PAGE))

    assert outcome(fetch(server, server.url("/hop1"))) == (200, "ok", None)
    server.requests.clear()
    result = fetch(server, server.url("/hop0"))
    assert outcome(result) == (302, "error", "too_many_redirects")
    assert result.bundle.manifest.final_url == server.url("/hop5")
    assert len(server.requests) == 6


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://internal.example.com/admin", "private_address"),
        ("http://127.0.0.1/", "private_address"),
        ("http://[::ffff:169.254.169.254]/latest/meta-data/", "private_address"),
        ("file:///etc/passwd", "scheme"),
        ("gopher://public.example.com/", "scheme"),
        ("http://public.example.com:6379/", "port"),
        ("http://unknown.example.com/", "dns"),
    ],
)
def test_a_redirect_hop_that_fails_the_guard_is_an_error(server: Server, location: str, reason: str) -> None:
    server.route("/p", redirect(location))
    result = fetch(server, server.url("/p"))
    assert outcome(result) == (302, "error", f"ssrf_rejected: {reason}")
    assert result.bundle.body == b""
    assert len(server.requests) == 1


def test_a_rejected_first_url_is_never_requested(server: Server) -> None:
    result = fetch(server, "http://internal.example.com/")
    assert outcome(result) == (0, "error", "ssrf_rejected: private_address")
    assert result.attempts[0].status is None
    assert server.requests == []


def test_a_redirect_without_location_is_the_final_response(server: Server) -> None:
    server.route("/p", html(b"moved, somewhere", 302))
    assert outcome(fetch(server, server.url("/p"))) == (302, "ok", None)


# --- cookies -----------------------------------------------------------------------------------------------------


def test_cookies_are_sent_across_hops_but_never_recorded(server: Server) -> None:
    server.route("/login", Reply(302, (("Location", "/p"), ("Set-Cookie", "session=s3cr3t"))))
    server.route("/p", html(_PAGE, 200, ("Set-Cookie", "seen=1")))
    manifest = fetch(server, server.url("/login")).bundle.manifest

    assert ("Cookie", "session=s3cr3t") in server.requests[1][1]
    recorded = [name.lower() for name, _ in (*manifest.headers.request, *manifest.headers.response)]
    assert "cookie" not in recorded
    assert "set-cookie" not in recorded


# --- caps and failures -------------------------------------------------------------------------------------------


def test_a_body_at_the_cap_is_kept(server: Server) -> None:
    body = b"<p>" + b"x" * 993 + b"</p>"
    server.route("/p", html(body))
    result = fetch(server, server.url("/p"), FetchPolicy(max_body_bytes=1000, max_decompressed_bytes=1000))
    assert result.bundle.body == body


def test_a_body_over_the_cap_is_an_error(server: Server) -> None:
    server.route("/p", html(b"x" * 50_000))
    result = fetch(server, server.url("/p"), FetchPolicy(max_body_bytes=10_000))
    assert outcome(result) == (200, "error", "body_cap")
    assert result.bundle.body == b""


def test_a_compressed_body_is_stored_decoded(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"), ("Content-Encoding", "gzip")), gzip.compress(_PAGE)))
    result = fetch(server, server.url("/p"))
    assert outcome(result) == (200, "ok", None)
    assert result.bundle.body == _PAGE


def test_a_compression_bomb_stops_at_the_decompressed_cap(server: Server) -> None:
    bomb = gzip.compress(b"\0" * 20_000_000)  # about 20 kB on the wire
    server.route("/p", Reply(200, (("Content-Type", "text/html"), ("Content-Encoding", "gzip")), bomb))
    result = fetch(server, server.url("/p"), FetchPolicy(max_body_bytes=1_000_000, max_decompressed_bytes=100_000))
    assert outcome(result) == (200, "error", "body_cap")


def test_a_body_that_fails_to_decode_is_an_error(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"), ("Content-Encoding", "gzip")), b"not gzip at all"))
    assert outcome(fetch(server, server.url("/p"))) == (200, "error", "decode_error")


def test_a_slow_body_runs_out_of_time(server: Server) -> None:
    server.route("/p", Reply(200, (("Content-Type", "text/html"),), _PAGE, delay_s=3.0))
    started = time.monotonic()
    result = fetch(server, server.url("/p"), FetchPolicy(timeout_s=0.5))
    assert outcome(result) == (200, "error", "timeout")
    assert time.monotonic() - started < 2.5


def test_the_time_budget_covers_every_hop(server: Server) -> None:
    server.route("/a", Reply(302, (("Location", "/b"),), delay_s=0.4))
    server.route("/b", Reply(302, (("Location", "/c"),), delay_s=0.4))
    server.route("/c", html(_PAGE))
    assert outcome(fetch(server, server.url("/a"), FetchPolicy(timeout_s=0.6)))[1:] == ("error", "timeout")


def test_a_refused_connection_is_a_network_error(server: Server) -> None:
    closed = Server(port=_closed_port())
    result = asyncio.run(
        fetch_http(closed.url("/p"), FetchPolicy(), engine_version="test", connector=LoopbackConnector(closed.port, {}))
    )
    assert outcome(result) == (0, "error", "network_error: curl 7")
    assert result.attempts[0].status is None


def test_proxy_environment_variables_are_ignored(server: Server, monkeypatch: pytest.MonkeyPatch) -> None:
    # A proxy resolves the host itself, which would bypass the pinned address (SPEC-02 §4.5). Proxies come only
    # from the configured pools (PR 7).
    closed = _closed_port()
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{closed}")
    server.route("/p", html(_PAGE))
    assert outcome(fetch(server, server.url("/p"))) == (200, "ok", None)


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
