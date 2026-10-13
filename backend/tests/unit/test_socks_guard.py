"""The browser's SSRF guard (SPEC-02 §4.5, INV-16): a SOCKS5 front that checks every connection the browser opens
and connects only to the checked address. Spoken to here as a SOCKS5 client would (RFC 1928); no browser, no DNS.

`.test` hosts are pinned to a local echo server; every other name goes through the real guard with a stub resolver.
"""

import asyncio
import socket
import struct
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from ipaddress import IPv4Address, ip_address
from urllib.parse import urlsplit

import pytest

from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import IPAddress, SafeConnector, Target

_DNS = {"internal.example.com": "10.0.0.1", "public.example.com": "93.184.215.14"}


class PinnedConnector(SafeConnector):
    """`.test` hosts pass, pinned to 127.0.0.1; other hosts are checked for real against `_DNS`. `lookups` counts
    every check that reached the resolver or the pin."""

    def __init__(self) -> None:
        async def resolve(host: str) -> list[IPAddress]:
            self.lookups.append(host)
            if host not in _DNS:
                raise OSError("no such host")
            return [ip_address(_DNS[host])]

        super().__init__(resolve)
        self.lookups: list[str] = []

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        if parts.hostname and parts.hostname.endswith(".test") and parts.port is not None:
            self.lookups.append(parts.hostname)
            return Target(url=url, host=parts.hostname, port=parts.port, ip=IPv4Address("127.0.0.1"))
        return await super().check(url)


@asynccontextmanager
async def echo_server() -> AsyncIterator[int]:
    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while data := await reader.read(1024):
            writer.write(b"echo:" + data)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()


def _domain_request(host: str, port: int, command: int = 1) -> bytes:
    name = host.encode()
    return bytes([5, command, 0, 3, len(name)]) + name + struct.pack("!H", port)


async def _socks(
    guard: SocksGuard, request: bytes, methods: bytes = b"\x00"
) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    """Greet, send `request`, and return the method choice plus the reply's first two bytes (version, code)."""
    host, port = guard.address
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(bytes([5, len(methods)]) + methods)
    choice = await reader.readexactly(2)
    if choice != b"\x05\x00":
        return choice, reader, writer
    writer.write(request)
    head = await reader.readexactly(2)
    return head, reader, writer


def _run[T](scenario: Coroutine[None, None, T]) -> T:
    return asyncio.run(asyncio.wait_for(scenario, 10))


def test_connect_to_an_admitted_host_tunnels_to_the_pinned_address() -> None:
    async def scenario() -> None:
        async with echo_server() as port, SocksGuard(PinnedConnector()) as guard:
            head, reader, writer = await _socks(guard, _domain_request("shop.example.test", port))
            rest = await reader.readexactly(8)  # RSV, ATYP IPv4, BND.ADDR, BND.PORT
            writer.write(b"ping")
            echoed = await reader.readexactly(9)
            writer.close()

        assert (head, rest[:2]) == (b"\x05\x00", b"\x00\x01")
        assert echoed == b"echo:ping"

    _run(scenario())


@pytest.mark.parametrize(
    ("host", "port", "reason"),
    [
        pytest.param("internal.example.com", 443, "private_address", id="name-resolving-private"),
        pytest.param("missing.example.com", 443, "dns", id="unresolvable"),
        pytest.param("public.example.com", 22, "port", id="non-web-port"),
    ],
)
def test_connect_to_a_rejected_target_is_refused_by_ruleset_and_recorded(host: str, port: int, reason: str) -> None:
    async def scenario() -> None:
        async with SocksGuard(PinnedConnector()) as guard:
            head, _, writer = await _socks(guard, _domain_request(host, port))
            writer.close()
            rejections = dict(guard.rejections)

        # RFC 1928 §6: X'02' connection not allowed by ruleset.
        assert head == b"\x05\x02"
        assert rejections == {(host, port): reason}

    _run(scenario())


@pytest.mark.parametrize(
    ("atyp", "address"),
    [
        pytest.param(1, IPv4Address("127.0.0.1").packed, id="ipv4-loopback"),
        pytest.param(1, IPv4Address("169.254.169.254").packed, id="ipv4-metadata"),
        pytest.param(4, ip_address("::ffff:10.0.0.1").packed, id="ipv4-mapped-ipv6"),
        pytest.param(4, ip_address("fd00::1").packed, id="ipv6-unique-local"),
    ],
)
def test_connect_to_a_literal_private_address_is_refused(atyp: int, address: bytes) -> None:
    async def scenario() -> bytes:
        async with SocksGuard(PinnedConnector()) as guard:
            head, _, writer = await _socks(guard, bytes([5, 1, 0, atyp]) + address + struct.pack("!H", 443))
            writer.close()
            return head

    assert _run(scenario()) == b"\x05\x02"


def test_a_host_is_checked_once_per_guard_so_its_address_cannot_change_mid_fetch() -> None:
    connector = PinnedConnector()

    async def scenario() -> None:
        async with echo_server() as port, SocksGuard(connector) as guard:
            for _ in range(3):
                head, _, writer = await _socks(guard, _domain_request("shop.example.test", port))
                assert head == b"\x05\x00"
                writer.close()

    _run(scenario())
    assert connector.lookups == ["shop.example.test"]


def test_targets_checked_before_the_guard_starts_are_not_checked_again() -> None:
    connector = PinnedConnector()

    async def scenario() -> None:
        async with echo_server() as port:
            first = await connector.check(f"http://shop.example.test:{port}/")
            async with SocksGuard(connector, checked=(first,)) as guard:
                head, _, writer = await _socks(guard, _domain_request("shop.example.test", port))
                writer.close()
        assert head == b"\x05\x00"

    _run(scenario())
    assert connector.lookups == ["shop.example.test"]


def test_only_the_connect_command_is_supported() -> None:
    async def scenario() -> bytes:
        async with SocksGuard(PinnedConnector()) as guard:
            head, _, writer = await _socks(guard, _domain_request("shop.example.test", 443, command=2))  # BIND
            writer.close()
            return head

    # RFC 1928 §6: X'07' command not supported.
    assert _run(scenario()) == b"\x05\x07"


def test_a_client_offering_no_unauthenticated_method_is_refused() -> None:
    async def scenario() -> bytes:
        async with SocksGuard(PinnedConnector()) as guard:
            choice, _, writer = await _socks(guard, b"", methods=b"\x02")  # username/password only
            writer.close()
            return choice

    # RFC 1928 §3: X'FF' no acceptable methods.
    assert _run(scenario()) == b"\x05\xff"


def test_leaving_the_guard_closes_open_tunnels_and_the_listener() -> None:
    async def scenario() -> tuple[bytes, tuple[str, int]]:
        async with echo_server() as port:
            async with SocksGuard(PinnedConnector()) as guard:
                head, reader, writer = await _socks(guard, _domain_request("shop.example.test", port))
                await reader.readexactly(8)
                address = guard.address
            rest = await reader.read()  # EOF once the guard closed the tunnel
            writer.close()
        assert head == b"\x05\x00"
        return rest, address

    rest, address = _run(scenario())
    assert rest == b""
    with pytest.raises(OSError):  # refused; Windows retries the SYN and times out instead
        socket.create_connection(address, timeout=2).close()
