"""The browser's SSRF guard (SPEC-02 §4.5, ARCHITECTURE §7.1, §18, INV-16): a SOCKS5 proxy on loopback that the
browser context sends every connection through.

A request interceptor can't be the guard: the browser follows redirects itself, and interception sees only the
first request of a redirect chain. Behind a SOCKS5 proxy the browser resolves no names (RFC 1928 §4 lets it send the
host name), so each connection, on every redirect hop and from every frame or worker, names its host here. The
guard checks it with `SafeConnector.check` and connects only to the checked address, which is fixed for the life of
the guard: a name is resolved once per fetch, and a changed DNS answer can't redirect a later connection.

Only CONNECT with no authentication is spoken (RFC 1928 §3, §4). Bytes are relayed unread, so TLS stays end to end
between the browser and the site.

With an `upstream` proxy pool, the guard still checks each host, then opens the connection as a CONNECT tunnel
through the pool's proxy (RFC 9110 §9.3.6), naming the host: the proxy resolves it, so the address can't be pinned
(ARCHITECTURE §7.1).
"""

import asyncio
import contextlib
import struct
from collections.abc import Iterable
from ipaddress import IPv4Address, IPv6Address
from types import TracebackType
from typing import Self, cast

from crawlerai.acquire.ssrf import RejectReason, SafeConnector, SsrfRejected, Target, authority
from crawlerai.core.proxy import ProxyEndpoint

__all__ = ["SocksGuard"]

# RFC 1928 §3 method, §4 command and address types, §6 reply codes.
_VERSION = 5
_NO_AUTH = 0
_NO_ACCEPTABLE_METHOD = 0xFF
_CONNECT = 1
_IPV4, _DOMAIN, _IPV6 = 1, 3, 4
_SUCCEEDED = 0
_GENERAL_FAILURE = 1
_NOT_ALLOWED = 2
_HOST_UNREACHABLE = 4
_COMMAND_NOT_SUPPORTED = 7
_ADDRESS_TYPE_NOT_SUPPORTED = 8

_CHUNK = 65_536


class _Refused(Exception):
    def __init__(self, reply: int) -> None:
        super().__init__(reply)
        self.reply = reply


class SocksGuard:
    """`async with SocksGuard(connector) as guard:` listens on `guard.url` until the block ends, then closes the
    listener and every tunnel. `checked` targets were checked by the caller already and are used as they are.
    `upstream` is the proxy pool every connection goes through, if any. `rejections` maps each refused (host, port) to
    the guard's reason."""

    def __init__(
        self, connector: SafeConnector, checked: Iterable[Target] = (), upstream: ProxyEndpoint | None = None
    ) -> None:
        self._connector = connector
        self._upstream = upstream
        self._targets: dict[tuple[str, int], asyncio.Future[Target]] = {}
        for target in checked:
            done: asyncio.Future[Target] = asyncio.get_running_loop().create_future()
            done.set_result(target)
            self._targets[(target.host.lower(), target.port)] = done
        self._handlers: set[asyncio.Task[None]] = set()
        self._server: asyncio.Server | None = None
        self.rejections: dict[tuple[str, int], RejectReason] = {}
        self.address: tuple[str, int] = ("127.0.0.1", 0)  # the listening address, once the guard is entered

    @property
    def url(self) -> str:
        host, port = self.address
        return f"socks5://{host}:{port}"

    def rejection_for(self, url: str) -> RejectReason | None:
        """Why the guard refused the connection `url` needs, if it did."""
        try:
            host, port = authority(url)
        except SsrfRejected:
            return None  # refused before any connection: the guard never saw it
        return self.rejections.get((host.lower(), port))

    async def __aenter__(self) -> Self:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.address = ("127.0.0.1", int(self._server.sockets[0].getsockname()[1]))
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()  # closes the listening socket now
        # A check runs apart from the handler that started it (it is shared by every connection to its host), so it
        # is cancelled too: none outlives the fetch.
        checks = [check for check in self._targets.values() if not check.done()]
        for handler in self._handlers:
            handler.cancel()
        for check in checks:
            check.cancel()
        await asyncio.gather(*self._handlers, return_exceptions=True)
        await asyncio.gather(*checks, return_exceptions=True)
        # Every handler has closed its tunnels. `Server.wait_closed` is not awaited: on Windows a connection the
        # browser reset is never detached from the server (CPython's proactor `_call_connection_lost` raises from
        # `shutdown` before `_detach`), and the wait would never end.

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # asyncio.start_server runs each connection's callback in a task of its own.
        handler = cast(asyncio.Task[None], asyncio.current_task())
        self._handlers.add(handler)
        upstream: asyncio.StreamWriter | None = None
        try:
            if not await _negotiate(reader, writer):
                return
            try:
                upstream_reader, upstream = await self._connect(reader)
            except _Refused as refused:
                writer.write(_reply(refused.reply))
                await writer.drain()
                return
            writer.write(_reply(_SUCCEEDED))
            await writer.drain()
            await asyncio.gather(_relay(reader, upstream), _relay(upstream_reader, writer))
        except (OSError, asyncio.IncompleteReadError):
            pass  # the browser or the site went away; the browser sees its connection close
        finally:
            for stream in (upstream, writer):
                if stream is not None:
                    stream.close()
            self._handlers.discard(handler)

    async def _connect(self, reader: asyncio.StreamReader) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        _, command, _, address_type = await reader.readexactly(4)
        host = await _read_host(reader, address_type)
        (port,) = struct.unpack("!H", await reader.readexactly(2))
        if command != _CONNECT:
            raise _Refused(_COMMAND_NOT_SUPPORTED)
        target = await self._check(host, port)
        if self._upstream is not None:
            return await _tunnel(self._upstream, target)
        try:
            return await asyncio.open_connection(str(target.ip), target.port)
        except OSError as e:
            raise _Refused(_HOST_UNREACHABLE) from e

    async def _check(self, host: str, port: int) -> Target:
        key = (host.lower(), port)
        if key not in self._targets:
            # The scheme only selects `check`'s rules for web URLs: its port allowlist is the same for http and https,
            # and the tunnel carries whichever the page uses.
            literal = f"[{host}]" if ":" in host else host
            self._targets[key] = asyncio.ensure_future(self._connector.check(f"https://{literal}:{port}/"))
        try:
            return await asyncio.shield(self._targets[key])
        except SsrfRejected as e:
            self.rejections[key] = e.reason
            raise _Refused(_NOT_ALLOWED) from e


async def _tunnel(proxy: ProxyEndpoint, target: Target) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A CONNECT tunnel to `target`'s host through `proxy` (RFC 9110 §9.3.6). Any 2xx answer opens it."""
    try:
        reader, writer = await asyncio.open_connection(proxy.host, proxy.port)
    except OSError as e:
        raise _Refused(_HOST_UNREACHABLE) from e
    # RFC 9112 §3.2.3: CONNECT names the authority; an IPv6 literal goes in brackets (RFC 3986 §3.2.2).
    host = f"[{target.host}]" if ":" in target.host else target.host
    head = [f"CONNECT {host}:{target.port} HTTP/1.1", f"Host: {host}:{target.port}"]
    if proxy.authorization is not None:
        head.append(f"Proxy-Authorization: {proxy.authorization}")
    try:
        # The host is ASCII: a browser names it in IDNA (A-label) form, and the guard admitted it.
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii"))
        await writer.drain()
        # A 2xx CONNECT response ends with its header section: what follows belongs to the tunnel (RFC 9110 §9.3.6).
        response = await reader.readuntil(b"\r\n\r\n")
    except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as e:
        writer.close()
        raise _Refused(_GENERAL_FAILURE) from e
    # RFC 9112 §4: status-line = HTTP-version SP status-code SP [ reason-phrase ].
    fields = response.split(b" ", 2)
    if len(fields) < 2 or not fields[1].startswith(b"2"):
        writer.close()
        raise _Refused(_GENERAL_FAILURE)
    return reader, writer


async def _negotiate(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    version, count = await reader.readexactly(2)
    methods = await reader.readexactly(count)
    accepted = version == _VERSION and _NO_AUTH in methods
    writer.write(bytes([_VERSION, _NO_AUTH if accepted else _NO_ACCEPTABLE_METHOD]))
    await writer.drain()
    return accepted


async def _read_host(reader: asyncio.StreamReader, address_type: int) -> str:
    if address_type == _IPV4:
        return str(IPv4Address(await reader.readexactly(4)))
    if address_type == _IPV6:
        return str(IPv6Address(await reader.readexactly(16)))
    if address_type == _DOMAIN:
        (length,) = await reader.readexactly(1)
        try:
            # A browser sends the IDNA (A-label) form of the host (RFC 5891), which is ASCII.
            return (await reader.readexactly(length)).decode("ascii")
        except UnicodeDecodeError as e:
            raise _Refused(_GENERAL_FAILURE) from e
    raise _Refused(_ADDRESS_TYPE_NOT_SUPPORTED)


def _reply(code: int) -> bytes:
    # RFC 1928 §6: BND.ADDR and BND.PORT are unused by a CONNECT client here, so they are zeros.
    return bytes([_VERSION, code, 0, _IPV4]) + bytes(4) + struct.pack("!H", 0)


async def _relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(OSError):
        while data := await reader.read(_CHUNK):
            writer.write(data)
            await writer.drain()
    # Either side ending ends the tunnel: neither the browser nor the site waits on a half-closed connection.
    writer.close()
