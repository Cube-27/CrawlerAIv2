"""Proxy pools (acquisition spec, D-1323, D-1324): a fetch whose policy names a configured pool goes
through one of that pool's proxies, in every fetcher, picked in turn or kept per site, an endpoint that keeps failing
left out for a while; and the SSRF guard still checks every host before it is requested, whichever endpoint carries it.

The proxy is a local stub speaking HTTP CONNECT (RFC 9110 §9.3.6). Like a real proxy it resolves names itself: it
sends every tunnel to a local origin server, whatever host it names. The guard's resolver is a stub, so no test
touches DNS or the network.
"""

import asyncio
import base64
import contextlib
import os
import socket
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from socketserver import BaseRequestHandler, TCPServer, ThreadingTCPServer

import pytest
from pydantic import ValidationError

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.session import CookieExport, SessionCookie, SiteSessions
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.proxy import PoolMode, ProxyEndpoint, ProxyPool
from crawlerai.core.settings import IMPERSONATE_DEFAULT, AcquireSettings

_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_PAGE = f"<html><body><h1>Catalogue</h1>{_LINKS}</body></html>".encode()
# The guard's view of DNS. The public address is never connected to: through a pool, the proxy resolves names.
_DNS = {"shop.example.test": "93.184.215.14", "internal.example.test": "10.0.0.1"}
_CREDENTIALS = ("pool user", "p@ss:word")
_JSON = b'{"items": [{"id": 1, "name": "Synthetic"}]}'


@dataclass
class Origin:
    """The site behind the proxy. Records the Host and Cookie of every request it serves."""

    port: int
    hosts: list[str] = field(default_factory=list)
    cookies: list[str | None] = field(default_factory=list)


@pytest.fixture
def origin() -> Iterator[Origin]:
    state: list[Origin] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        routes: dict[str, tuple[int, tuple[tuple[str, str], ...], bytes]] = {  # noqa: RUF012
            "/p": (200, (("Content-Type", "text/html"),), _PAGE),
            "/j": (200, (("Content-Type", "application/json"),), _JSON),
            "/j-hop": (302, (("Location", "/j"),), b""),
            "/j-hop-private": (302, (("Location", "http://internal.example.test/j"),), b""),
            "/hop": (302, (("Location", "/p"),), b""),
            "/hop-private": (302, (("Location", "http://internal.example.test/"),), b""),
        }

        def do_GET(self) -> None:
            state[0].hosts.append(self.headers.get("Host", ""))
            state[0].cookies.append(self.headers.get("Cookie"))
            status, headers, body = self.routes.get(self.path, (404, (), b"no route"))
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    yield from _serve(ThreadingHTTPServer(("127.0.0.1", 0), Handler), lambda port: state.append(Origin(port)), state)


@dataclass
class StubProxy:
    """An HTTP CONNECT proxy that tunnels every target to `origin_port`. With `required` set, a CONNECT without
    that `Proxy-Authorization` gets 407 (RFC 9110 §15.5.8)."""

    port: int
    origin_port: int
    required: str | None = None
    tunnels: list[str] = field(default_factory=list)  # the authority of every tunnel opened
    authorizations: list[str | None] = field(default_factory=list)  # as received, one per CONNECT
    moved: list[int] = field(default_factory=list)  # the bytes of each connection, both ways, CONNECT included

    def endpoint(self, credentials: tuple[str, str] | None = None) -> ProxyEndpoint:
        username, password = credentials or (None, None)
        return ProxyEndpoint(host="127.0.0.1", port=self.port, username=username, password=password)


@pytest.fixture
def proxy(origin: Origin) -> Iterator[StubProxy]:
    yield from _stub_proxy(origin)


@pytest.fixture
def second_proxy(origin: Origin) -> Iterator[StubProxy]:
    yield from _stub_proxy(origin)


def _stub_proxy(origin: Origin) -> Iterator[StubProxy]:
    state: list[StubProxy] = []

    class Handler(BaseRequestHandler):
        def handle(self) -> None:
            stub, client = state[0], self.request
            head = _read_head(client)
            moved = [len(head) + 4]  # the head and its blank line (RFC 9112 §2.1)
            stub.moved.append(0)
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            headers = {name.lower(): value.strip() for name, _, value in (h.partition(":") for h in header_lines)}
            stub.authorizations.append(headers.get("proxy-authorization"))
            method, authority, _ = request_line.split(" ")
            if method != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
                return
            if stub.required is not None and headers.get("proxy-authorization") != stub.required:
                client.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n")
                return
            stub.tunnels.append(authority)
            with socket.create_connection(("127.0.0.1", stub.origin_port)) as upstream:
                established = b"HTTP/1.1 200 Connection established\r\n\r\n"
                client.sendall(established)
                moved.append(len(established))
                _relay(client, upstream, moved)
            stub.moved[-1] = sum(moved)

    yield from _serve(
        _Threads(("127.0.0.1", 0), Handler),
        lambda port: state.append(StubProxy(port, origin.port)),
        state,
    )


class _Threads(ThreadingTCPServer):
    daemon_threads = True  # as ThreadingHTTPServer sets it: a test never waits on a tunnel left open


def _serve[T](server: TCPServer, started: Callable[[int], None], state: list[T]) -> Iterator[T]:
    started(int(server.server_address[1]))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield state[0]
    server.shutdown()
    server.server_close()


def _read_head(sock: socket.socket) -> bytes:
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(1)
        if not chunk:
            break
        head += chunk
    return head.split(b"\r\n\r\n", 1)[0]


def _relay(client: socket.socket, upstream: socket.socket, moved: list[int]) -> None:
    def pump(source: socket.socket, sink: socket.socket) -> None:
        with contextlib.suppress(OSError):
            while data := source.recv(65_536):
                moved.append(len(data))
                sink.sendall(data)
        # Either side ending ends the tunnel, as a proxy does.
        for sock in (source, sink):
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)

    back = threading.Thread(target=pump, args=(upstream, client), daemon=True)
    back.start()
    pump(client, upstream)
    back.join(timeout=5)


class StubConnector(SafeConnector):
    """The real guard, resolving names from `_DNS` only."""

    def __init__(self) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            if host not in _DNS:
                raise OSError("no such host")
            return [ip_address(_DNS[host])]

        super().__init__(resolve)


def _pools(*endpoints: ProxyEndpoint, mode: PoolMode = "rotate") -> dict[str, ProxyPool]:
    return {"dc": ProxyPool(endpoints, mode)}


def _fetch(
    url: str, pools: dict[str, ProxyPool], pool: str | None = "dc", sessions: SiteSessions | None = None
) -> FetchResult:
    return asyncio.run(
        fetch_http(
            url,
            FetchPolicy(proxy_pool=pool, timeout_s=5),
            engine_version="test",
            impersonate=IMPERSONATE_DEFAULT,
            connector=StubConnector(),
            pools=pools,
            sessions=sessions,
        )
    )


def _outcome(result: FetchResult) -> tuple[int, str, str | None]:
    return result.bundle.manifest.status_code, result.block_class, result.attempts[-1].error


# --- settings ----------------------------------------------------------------------------------------------------


def test_pools_are_read_from_json_with_credentials_percent_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLERAI_PROXY_POOLS", '{"dc": "http://pool%20user:p%40ss%3Aword@proxy.example.com:3128"}')

    (name, pool), *rest = AcquireSettings().proxy_pools.items()

    assert (name, rest) == ("dc", [])
    (endpoint,) = pool.endpoints
    assert endpoint == ProxyEndpoint("proxy.example.com", 3128, "pool user", "p@ss:word")
    # RFC 7617 §2: Basic credentials are base64("user:password").
    assert endpoint.authorization == "Basic " + base64.b64encode(b"pool user:p@ss:word").decode()
    assert repr(endpoint) == "ProxyEndpoint(host='proxy.example.com', port=3128)"


@pytest.mark.parametrize(
    "value",
    [
        '"socks5://user:secret-pw@proxy.example.com:1080"',
        '"http://user:secret-pw@:3128"',
        '"http://user:secret-pw@proxy.example.com:3128/path"',
        '"http://user:secret-pw@proxy.example.com:99999"',
        '"proxy.example.com:3128"',
        '{"url": "http://user:secret-pw@proxy.example.com:3128"}',
        # D-1323: a pool of several endpoints names its mode, lists at least one endpoint, and none twice.
        '{"endpoints": ["http://user:secret-pw@proxy.example.com:3128"]}',
        '{"endpoints": ["http://user:secret-pw@proxy.example.com:3128"], "mode": "random"}',
        '{"endpoints": [], "mode": "rotate"}',
        '{"endpoints": ["http://user:secret-pw@a.example.com:1", "http://user:secret-pw@a.example.com:1"], '
        '"mode": "sticky"}',
        '{"endpoints": ["socks5://user:secret-pw@proxy.example.com:1080"], "mode": "rotate"}',
    ],
)
def test_a_proxy_url_other_than_http_host_port_is_refused_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("CRAWLERAI_PROXY_POOLS", f'{{"dc": {value}}}')

    with pytest.raises(ValidationError) as refused:
        AcquireSettings()

    assert "secret-pw" not in str(refused.value)
    assert refused.value.errors()[0]["loc"] == ("proxy_pools", "dc")


# --- HTTP fetch --------------------------------------------------------------------------------------------------


def test_the_pools_credentials_reach_the_proxy_and_never_the_capture(origin: Origin, proxy: StubProxy) -> None:
    endpoint = proxy.endpoint(_CREDENTIALS)
    proxy.required = endpoint.authorization

    result = _fetch("http://shop.example.test/p", _pools(endpoint))

    assert _outcome(result) == (200, "ok", None)
    assert proxy.tunnels == ["shop.example.test:80"]
    manifest = result.bundle.manifest
    recorded = manifest.headers.request + manifest.headers.response
    assert all(name.lower() != "proxy-authorization" for name, _ in recorded)


# --- pools of several endpoints (D-1323, D-1324) --------------------------------------------------------------------


def _session_through(endpoint: ProxyEndpoint) -> SiteSessions:
    sessions = SiteSessions()
    cookies = (SessionCookie("clearance", "1", "example.test", "/", secure=False, host_only=False, expires=None),)
    identity = (("User-Agent", "Mozilla/5.0 Solver/153.0"),)
    assert sessions.open("http://shop.example.test/", "dc", CookieExport(cookies, endpoint), identity) is not None
    return sessions


def test_inv29_a_site_session_keeps_the_sites_fetches_on_the_endpoint_its_cookies_came_through(
    origin: Origin, proxy: StubProxy, second_proxy: StubProxy
) -> None:
    pools = _pools(proxy.endpoint(), second_proxy.endpoint())
    sessions = _session_through(second_proxy.endpoint())

    for _ in range(4):
        assert _outcome(_fetch("http://shop.example.test/p", pools, sessions=sessions)) == (200, "ok", None)

    assert (len(proxy.tunnels), len(second_proxy.tunnels)) == (0, 4)
    assert origin.cookies == ["clearance=1"] * 4


@pytest.mark.parametrize("mode", ["rotate", "sticky"])
def test_inv16_every_endpoint_of_a_pool_reaches_only_checked_hosts(
    origin: Origin, proxy: StubProxy, second_proxy: StubProxy, mode: PoolMode
) -> None:
    pools = _pools(proxy.endpoint(), second_proxy.endpoint(), mode=mode)

    for _ in range(2):
        assert _outcome(_fetch("http://internal.example.test/p", pools)) == (
            0,
            "error",
            "ssrf_rejected: private_address",
        )
        refused = _fetch("http://shop.example.test/hop-private", pools)
        assert _outcome(refused) == (302, "error", "ssrf_rejected: private_address")
        refused_json = _fetch_json("http://shop.example.test/j-hop-private", pools)
        assert _outcome(refused_json) == (302, "error", "ssrf_rejected: private_address")

    tunnels = proxy.tunnels + second_proxy.tunnels
    assert "internal.example.test:80" not in tunnels
    assert set(tunnels) == {"shop.example.test:80"}


# --- JSON fetch (D-1264) ------------------------------------------------------------------------------------------


def _fetch_json(url: str, pools: dict[str, ProxyPool], pool: str | None = "dc") -> FetchResult:
    request = JsonRequest(url=url, page_url="http://shop.example.test/page")
    return asyncio.run(
        fetch_json(
            request,
            FetchPolicy(proxy_pool=pool, timeout_s=5),
            engine_version="test",
            impersonate=IMPERSONATE_DEFAULT,
            connector=StubConnector(),
            pools=pools,
        )
    )


# --- the browser's guard -----------------------------------------------------------------------------------------


# --- browser fetch -----------------------------------------------------------------------------------------------


@pytest.mark.browser
def test_a_browser_fetch_naming_a_pool_goes_through_its_proxy(origin: Origin, proxy: StubProxy) -> None:
    from patchright.async_api import Error as PlaywrightError

    from crawlerai.acquire.browser import fetch_browser, open_browser

    async def run() -> tuple[FetchResult, FetchResult]:
        async with open_browser() as session:

            async def fetch(pool: str) -> FetchResult:
                return await fetch_browser(
                    "http://shop.example.test/p",
                    FetchPolicy(proxy_pool=pool, browser_timeout_s=10),
                    session=session,
                    engine_version="test",
                    connector=StubConnector(),
                    pools=_pools(proxy.endpoint()),
                )

            return await fetch("dc"), await fetch("other")

    try:
        through_pool, unknown = asyncio.run(run())
    except PlaywrightError as e:
        if os.environ.get("CI") or "Executable doesn't exist" not in e.message:
            raise
        pytest.skip("Chromium is not installed: run `uv run patchright install --no-shell chromium`")

    assert _outcome(through_pool) == (200, "ok", None)
    assert b"<h1>Catalogue</h1>" in through_pool.bundle.body
    assert set(proxy.tunnels) == {"shop.example.test:80"}
    assert _outcome(unknown) == (0, "error", "proxy_pool_unknown")
