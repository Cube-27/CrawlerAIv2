"""Proxy pools (SPEC-02 §3, §4.5, ARCHITECTURE §7.1, D-1323, D-1324): a fetch whose policy names a configured pool goes
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
import struct
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from socketserver import BaseRequestHandler, TCPServer, ThreadingTCPServer

import pytest
from pydantic import ValidationError

from crawlerai.acquire.api import JsonRequest, fetch_json
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.tunnel import open_tunnel
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.proxy import PoolMode, ProxyEndpoint, ProxyPool, pool_endpoint
from crawlerai.core.proxy_health import QUARANTINE_AFTER, QUARANTINE_MIN, PoolHealth, quarantine
from crawlerai.core.settings import IMPERSONATE_DEFAULT, AcquireSettings

_LINKS = "".join(f'<a href="/item/{i}">Item {i}</a>' for i in range(8))
_PAGE = f"<html><body><h1>Catalogue</h1>{_LINKS}</body></html>".encode()
# The guard's view of DNS. The public address is never connected to: through a pool, the proxy resolves names.
_DNS = {"shop.example.test": "93.184.215.14", "internal.example.test": "10.0.0.1"}
_CREDENTIALS = ("pool user", "p@ss:word")
_JSON = b'{"items": [{"id": 1, "name": "Synthetic"}]}'


@dataclass
class Origin:
    """The site behind the proxy. Records the Host of every request it serves."""

    port: int
    hosts: list[str] = field(default_factory=list)


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
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                _relay(client, upstream)

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


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    def pump(source: socket.socket, sink: socket.socket) -> None:
        with contextlib.suppress(OSError):
            while data := source.recv(65_536):
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


def _fetch(url: str, pools: dict[str, ProxyPool], pool: str | None = "dc") -> FetchResult:
    return asyncio.run(
        fetch_http(
            url,
            FetchPolicy(proxy_pool=pool, timeout_s=5),
            engine_version="test",
            impersonate=IMPERSONATE_DEFAULT,
            connector=StubConnector(),
            pools=pools,
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


def test_without_the_setting_there_are_no_pools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLERAI_PROXY_POOLS", raising=False)

    assert AcquireSettings().proxy_pools == {}


def test_an_endpoint_without_credentials_sends_no_authorization() -> None:
    assert ProxyEndpoint.parse("http://proxy.example.com").authorization is None
    assert ProxyEndpoint.parse("http://proxy.example.com").port == 80  # RFC 9110 §4.2.1


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


def test_a_pool_of_several_endpoints_is_read_with_its_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CRAWLERAI_PROXY_POOLS",
        '{"dc": {"endpoints": ["http://a.example.com:3128", "http://u:p@b.example.com:8080"], "mode": "sticky"}}',
    )

    pool = AcquireSettings().proxy_pools["dc"]

    assert pool.mode == "sticky"
    assert pool.endpoints == (
        ProxyEndpoint("a.example.com", 3128),
        ProxyEndpoint("b.example.com", 8080, "u", "p"),
    )


# --- HTTP fetch --------------------------------------------------------------------------------------------------


def test_a_fetch_naming_a_pool_goes_through_its_proxy(origin: Origin, proxy: StubProxy) -> None:
    result = _fetch("http://shop.example.test/p", _pools(proxy.endpoint()))

    assert _outcome(result) == (200, "ok", None)
    assert result.bundle.body == _PAGE
    assert proxy.tunnels == ["shop.example.test:80"]
    assert origin.hosts == ["shop.example.test"]
    assert result.bundle.manifest.fetch_policy["proxy_pool"] == "dc"


def test_the_environments_no_proxy_does_not_send_a_pool_fetch_direct(
    origin: Origin, proxy: StubProxy, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Going direct would skip the pool and let curl resolve the host itself, unpinned from the checked address.
    monkeypatch.setenv("no_proxy", "*")

    result = _fetch("http://shop.example.test/p", _pools(proxy.endpoint()))

    assert _outcome(result) == (200, "ok", None)
    assert proxy.tunnels == ["shop.example.test:80"]


def test_the_pools_credentials_reach_the_proxy_and_never_the_capture(origin: Origin, proxy: StubProxy) -> None:
    endpoint = proxy.endpoint(_CREDENTIALS)
    proxy.required = endpoint.authorization

    result = _fetch("http://shop.example.test/p", _pools(endpoint))

    assert _outcome(result) == (200, "ok", None)
    assert proxy.tunnels == ["shop.example.test:80"]
    manifest = result.bundle.manifest
    recorded = manifest.headers.request + manifest.headers.response
    assert all(name.lower() != "proxy-authorization" for name, _ in recorded)


def test_a_proxy_that_refuses_the_tunnel_is_an_error(origin: Origin, proxy: StubProxy) -> None:
    proxy.required = "Basic other"

    result = _fetch("http://shop.example.test/p", _pools(proxy.endpoint(_CREDENTIALS)))

    # curl reports a refused CONNECT as it reports an unreachable server (CURLE_COULDNT_CONNECT).
    assert _outcome(result) == (0, "error", "network_error: curl 7")
    assert len(proxy.authorizations) == 1
    assert origin.hosts == []


def test_the_host_is_checked_before_it_is_requested_through_the_pool(origin: Origin, proxy: StubProxy) -> None:
    result = _fetch("http://internal.example.test/p", _pools(proxy.endpoint()))

    assert _outcome(result) == (0, "error", "ssrf_rejected: private_address")
    assert proxy.tunnels == []


def test_each_redirect_hop_is_checked_and_followed_through_the_pool(origin: Origin, proxy: StubProxy) -> None:
    followed = _fetch("http://shop.example.test/hop", _pools(proxy.endpoint()))
    assert _outcome(followed) == (200, "ok", None)
    assert followed.bundle.manifest.final_url == "http://shop.example.test/p"
    assert set(proxy.tunnels) == {"shop.example.test:80"}

    refused = _fetch("http://shop.example.test/hop-private", _pools(proxy.endpoint()))
    assert _outcome(refused) == (302, "error", "ssrf_rejected: private_address")
    assert "internal.example.test:80" not in proxy.tunnels


def test_a_pool_that_is_not_configured_refuses_the_fetch(origin: Origin, proxy: StubProxy) -> None:
    # Fetching without the pool would send the request from somewhere the site's configuration did not ask for.
    result = _fetch("http://shop.example.test/p", _pools(proxy.endpoint()), pool="other")

    assert _outcome(result) == (0, "error", "proxy_pool_unknown")
    assert (proxy.tunnels, origin.hosts) == ([], [])


# --- pools of several endpoints (D-1323, D-1324) --------------------------------------------------------------------


def test_a_rotating_pool_sends_successive_fetches_through_each_endpoint_in_turn(
    origin: Origin, proxy: StubProxy, second_proxy: StubProxy
) -> None:
    pools = _pools(proxy.endpoint(), second_proxy.endpoint())

    outcomes = [_outcome(_fetch("http://shop.example.test/p", pools)) for _ in range(4)]

    assert outcomes == [(200, "ok", None)] * 4
    assert (len(proxy.tunnels), len(second_proxy.tunnels)) == (2, 2)


def test_a_sticky_pool_keeps_a_site_on_one_endpoint(origin: Origin, proxy: StubProxy, second_proxy: StubProxy) -> None:
    pools = _pools(proxy.endpoint(), second_proxy.endpoint(), mode="sticky")

    for _ in range(4):
        assert _outcome(_fetch("http://shop.example.test/p", pools)) == (200, "ok", None)

    assert sorted((len(proxy.tunnels), len(second_proxy.tunnels))) == [0, 4]


def test_an_endpoint_that_keeps_failing_is_left_out_until_its_quarantine_ends(
    origin: Origin, proxy: StubProxy, second_proxy: StubProxy
) -> None:
    proxy.required = "Basic other"  # refuses every tunnel
    pools = _pools(proxy.endpoint(), second_proxy.endpoint())

    outcomes = [_outcome(_fetch("http://shop.example.test/p", pools))[1] for _ in range(10)]

    # Taken in turn, the refusing endpoint fails QUARANTINE_AFTER times; then only the other one is chosen.
    assert outcomes == ["error", "ok"] * QUARANTINE_AFTER + ["ok"] * (10 - 2 * QUARANTINE_AFTER)
    assert len(proxy.authorizations) == QUARANTINE_AFTER
    pool = pools["dc"]
    pool.health.clock = lambda: time.monotonic() + QUARANTINE_MIN.total_seconds()
    assert pool.pick("shop.example.test") == proxy.endpoint()  # its quarantine over, it is chosen again


def test_a_pool_whose_every_endpoint_is_quarantined_still_sends_through_one() -> None:
    first, second = ProxyEndpoint("127.0.0.1", 1), ProxyEndpoint("127.0.0.1", 2)
    now = [0.0]
    pool = ProxyPool((first, second), "rotate", PoolHealth(clock=lambda: now[0]))
    for _ in range(QUARANTINE_AFTER):
        pool.report(first, healthy=False)
    now[0] = 1.0
    for _ in range(QUARANTINE_AFTER + 1):
        pool.report(second, healthy=False)

    # Never direct: the endpoint that recovers first (the shorter quarantine began earlier).
    assert pool.pick("shop.example.test") == first


@pytest.mark.parametrize(
    ("failures", "minutes"),
    [
        (QUARANTINE_AFTER, 1),
        (QUARANTINE_AFTER + 1, 2),
        (QUARANTINE_AFTER + 4, 16),
        (QUARANTINE_AFTER + 5, 30),
        (99, 30),
    ],
)
def test_the_quarantine_doubles_with_each_further_failure_up_to_thirty_minutes(failures: int, minutes: int) -> None:
    assert quarantine(failures) == timedelta(minutes=minutes)


def test_one_success_ends_an_endpoints_run_of_failures() -> None:
    endpoint = ProxyEndpoint("127.0.0.1", 1)
    pool = ProxyPool((endpoint,), "rotate", PoolHealth(clock=lambda: 0.0))
    for healthy in [False] * (QUARANTINE_AFTER - 1) + [True] + [False] * (QUARANTINE_AFTER - 1):
        pool.report(endpoint, healthy=healthy)

    assert pool.health.available(endpoint) is True


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


def test_inv16_the_browser_guard_checks_the_host_before_asking_any_endpoint_of_a_pool(
    origin: Origin, proxy: StubProxy, second_proxy: StubProxy
) -> None:
    pools = _pools(proxy.endpoint(), second_proxy.endpoint())
    for _ in range(2):
        endpoint = pool_endpoint("dc", pools, "http://internal.example.test/")
        assert endpoint is not None
        code, _ = _guarded(proxy, endpoint, "internal.example.test")
        assert code == 2  # RFC 1928 §6: connection not allowed by ruleset

    assert (proxy.authorizations, second_proxy.authorizations) == ([], [])


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


def test_a_json_fetch_naming_a_pool_goes_through_a_tunnel_of_its_proxy(origin: Origin, proxy: StubProxy) -> None:
    endpoint = proxy.endpoint(_CREDENTIALS)
    proxy.required = endpoint.authorization

    result = _fetch_json("http://shop.example.test/j", _pools(endpoint))

    assert _outcome(result) == (200, "ok", None)
    assert result.bundle.body == _JSON
    assert proxy.tunnels == ["shop.example.test:80"]  # a CONNECT tunnel even for `http:`, naming the host
    assert origin.hosts == ["shop.example.test"]
    manifest = result.bundle.manifest
    assert all(
        name.lower() != "proxy-authorization" for name, _ in manifest.headers.request + manifest.headers.response
    )


def test_a_json_fetch_follows_each_checked_hop_through_the_pool(origin: Origin, proxy: StubProxy) -> None:
    followed = _fetch_json("http://shop.example.test/j-hop", _pools(proxy.endpoint()))
    assert _outcome(followed) == (200, "ok", None)
    assert followed.bundle.manifest.final_url == "http://shop.example.test/j"

    refused = _fetch_json("http://shop.example.test/j-hop-private", _pools(proxy.endpoint()))
    assert _outcome(refused) == (302, "error", "ssrf_rejected: private_address")
    assert "internal.example.test:80" not in proxy.tunnels


def test_a_json_fetch_whose_tunnel_is_refused_is_an_error_naming_no_credential(
    origin: Origin, proxy: StubProxy
) -> None:
    proxy.required = "Basic other"

    result = _fetch_json("http://shop.example.test/j", _pools(proxy.endpoint(_CREDENTIALS)))

    # curl reports a refused CONNECT as it reports an unreachable server (CURLE_COULDNT_CONNECT).
    assert _outcome(result) == (0, "error", "network_error: curl 7")
    assert origin.hosts == []


def test_a_json_fetch_naming_an_unknown_pool_sends_nothing(origin: Origin, proxy: StubProxy) -> None:
    result = _fetch_json("http://shop.example.test/j", _pools(proxy.endpoint()), pool="other")

    assert _outcome(result) == (0, "error", "proxy_pool_unknown")
    assert (proxy.tunnels, origin.hosts) == ([], [])


def test_a_tunnel_cancelled_before_the_proxy_answers_closes_its_socket() -> None:
    async def run() -> bool:
        closed = asyncio.Event()

        async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read()  # never answers CONNECT; returns once the client closes its side
            closed.set()
            writer.close()

        server = await asyncio.start_server(silent, "127.0.0.1", 0)
        port = int(server.sockets[0].getsockname()[1])
        kept: list[BaseException] = []
        try:
            async with asyncio.timeout(0.2):
                await open_tunnel(ProxyEndpoint(host="127.0.0.1", port=port), "shop.example.test", 80)
        except TimeoutError as e:
            kept.append(e)  # its traceback keeps the tunnel's frame alive: closing must not rest on garbage collection
        try:
            await asyncio.wait_for(closed.wait(), 2)
        finally:
            server.close()
        return closed.is_set()

    assert asyncio.run(run()) is True


# --- the browser's guard -----------------------------------------------------------------------------------------


async def _through_guard(guard: SocksGuard, host: str, port: int) -> tuple[int, bytes]:
    """Open a SOCKS5 CONNECT to `host` (RFC 1928 §4), send a GET, and return the reply code and what came back."""
    reader, writer = await asyncio.open_connection(*guard.address)
    try:
        writer.write(bytes([5, 1, 0]))
        assert await reader.readexactly(2) == bytes([5, 0])
        name = host.encode()
        writer.write(bytes([5, 1, 0, 3, len(name)]) + name + struct.pack("!H", port))
        _, code = await reader.readexactly(2)
        await reader.readexactly(8)  # the rest of the reply: address type, IPv4 address, port
        if code != 0:
            return code, b""
        writer.write(f"GET /p HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        return code, await reader.read()
    finally:
        writer.close()


def _guarded(proxy: StubProxy, endpoint: ProxyEndpoint, host: str) -> tuple[int, bytes]:
    async def run() -> tuple[int, bytes]:
        async with SocksGuard(StubConnector(), upstream=endpoint) as guard:
            return await _through_guard(guard, host, 80)

    return asyncio.run(run())


def test_the_guard_tunnels_through_the_pool_with_its_credentials(origin: Origin, proxy: StubProxy) -> None:
    endpoint = proxy.endpoint(_CREDENTIALS)
    proxy.required = endpoint.authorization

    code, received = _guarded(proxy, endpoint, "shop.example.test")

    assert code == 0
    assert received.startswith(b"HTTP/1.0 200") or received.startswith(b"HTTP/1.1 200")
    assert received.endswith(_PAGE)
    assert proxy.tunnels == ["shop.example.test:80"]
    assert origin.hosts == ["shop.example.test"]


def test_the_guard_checks_the_host_before_asking_the_pool(origin: Origin, proxy: StubProxy) -> None:
    code, _ = _guarded(proxy, proxy.endpoint(), "internal.example.test")

    assert code == 2  # RFC 1928 §6: connection not allowed by ruleset
    assert proxy.authorizations == []


def test_a_tunnel_the_pool_refuses_fails_the_connection(origin: Origin, proxy: StubProxy) -> None:
    proxy.required = "Basic other"

    code, _ = _guarded(proxy, proxy.endpoint(_CREDENTIALS), "shop.example.test")

    assert code == 1  # RFC 1928 §6: general SOCKS server failure
    assert origin.hosts == []


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
