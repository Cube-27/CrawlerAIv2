"""The webhook's signature and backoff (SPEC-10 §4.2), and the SSRF-guarded POST that sends it (`post` in
`crawlerai.acquire.http`).

A local server on 127.0.0.1 takes the POSTs under a `.test` host, admitted by a connector that pins that host to it;
every other URL goes through the real guard with a stub resolver. No live network.
"""

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlsplit

import pytest

from crawlerai.acquire.http import post
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, SsrfRejected, Target
from crawlerai.api.webhooks import retry_delay, signature


def test_the_signature_is_the_hex_hmac_sha256_of_the_body() -> None:
    # RFC 4231 §4.3, test case 2.
    expected = "sha256=5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"

    assert signature("Jefe", b"what do ya want for nothing?") == expected


def test_retries_wait_30_s_then_2_min() -> None:
    assert [retry_delay(1), retry_delay(2)] == [timedelta(seconds=30), timedelta(minutes=2)]


@dataclass
class Server:
    port: int
    status: int = 204
    received: list[tuple[str, bytes, dict[str, str]]] = field(default_factory=list)  # (path, body, headers)


@pytest.fixture
def server() -> Iterator[Server]:
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:
            srv = state[0]
            body = self.rfile.read(int(self.headers["Content-Length"]))
            srv.received.append((self.path, body, dict(self.headers.items())))
            self.send_response(srv.status)
            if srv.status == 302:
                self.send_header("Location", "/elsewhere")
            reply = b"x" * 4096
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

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
    """Pins `hooks.example.test` on the server's port to 127.0.0.1; anything else goes through the real guard, whose
    resolver answers 10.0.0.1, a private address."""

    def __init__(self, port: int) -> None:
        async def private(_host: str) -> list[IPAddress]:
            return [ip_address("10.0.0.1")]

        super().__init__(private)
        self._port = port

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname == "hooks.example.test" and parts.port == self._port:
            return Target(url=url, host=parts.hostname, port=self._port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


def _post(server: Server, url: str) -> int:
    headers = {"Content-Type": "application/json", "X-CrawlerAI-Signature": "sha256=00"}
    return asyncio.run(post(url, b'{"id": 1}', headers, connector=LoopbackConnector(server.port), timeout_s=5))


def test_post_sends_the_body_and_headers_and_returns_the_status(server: Server) -> None:
    status = _post(server, f"http://hooks.example.test:{server.port}/done")

    [(path, body, headers)] = server.received
    assert (status, path, body) == (204, "/done", b'{"id": 1}')
    assert (headers["Content-Type"], headers["X-CrawlerAI-Signature"]) == ("application/json", "sha256=00")


def test_post_returns_a_redirect_without_following_it(server: Server) -> None:
    server.status = 302

    status = _post(server, f"http://hooks.example.test:{server.port}/done")

    assert (status, [path for path, _, _ in server.received]) == (302, ["/done"])


def test_post_to_a_host_that_resolves_to_a_private_address_is_refused_unsent(server: Server) -> None:
    url = "https://internal.example.com/done"

    with pytest.raises(SsrfRejected, match="private_address"):
        _post(server, url)
    assert server.received == []
