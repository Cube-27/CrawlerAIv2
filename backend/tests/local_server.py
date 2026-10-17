"""A local server on 127.0.0.1 serving synthetic pages under `.test` hosts, for the HTTP and JSON rungs' tests; no live
network. `LoopbackConnector` admits only those hosts, at the server's port, and sends every other URL through the real
guard with a stub resolver, so redirect hops leaving the server are checked exactly as in production.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlsplit

from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target

__all__ = ["LoopbackConnector", "Reply", "Server", "serving"]

_LOOPBACK = IPv4Address("127.0.0.1")


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
    bodies: list[bytes] = field(default_factory=list)  # each request's body, in order

    def url(self, path: str, host: str = "shop.example.test") -> str:
        return f"http://{host}:{self.port}{path}"

    def route(self, path: str, reply: Reply | Callable[[str], Reply]) -> None:
        self.routes[path] = reply if callable(reply) else (lambda _host: reply)


def serving() -> Iterator[Server]:
    """A pytest fixture's body: the server, running until the test ends."""
    state: list[Server] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            srv = state[0]
            host = self.headers.get("Host", "").rsplit(":", 1)[0]
            srv.requests.append((host + self.path, list(self.headers.items())))
            length = int(self.headers.get("Content-Length") or 0)
            srv.bodies.append(self.rfile.read(length) if length else b"")
            reply = srv.routes[self.path](host) if self.path in srv.routes else Reply(404, body=b"no route")
            self.send_response(reply.status)
            for name, value in reply.headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(reply.body)))
            self.end_headers()
            self.wfile.flush()
            time.sleep(reply.delay_s)
            self.wfile.write(reply.body)

        do_POST = do_GET

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
    """Admits `.test` hosts on the local server's port, pinned to `pins[host]` (127.0.0.1 by default); everything
    else goes through the real guard."""

    def __init__(
        self, port: int, dns: dict[str, str], pins: dict[str, IPAddress] | None = None, dns_delay_s: float = 0.0
    ) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            await asyncio.sleep(dns_delay_s)
            if host not in dns:
                raise OSError("no such host")
            return [ip_address(dns[host])]

        super().__init__(resolve)
        self._port = port
        self._pins = pins or {}

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname and parts.hostname.endswith(".test") and parts.port == self._port:
            ip = self._pins.get(parts.hostname, _LOOPBACK)
            return Target(url=url, host=parts.hostname, port=self._port, ip=ip)
        return await super().check(url)
