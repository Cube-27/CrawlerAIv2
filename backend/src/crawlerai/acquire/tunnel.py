"""CONNECT tunnels through a proxy pool (RFC 9110 §9.3.6, ARCHITECTURE §7.1, SPEC-02 §3): the one way a rung reaches a
site through a pool. The browser's guard opens them (`socks_guard`); the JSON rung's httpx transport opens them through
`Tunnels`, so that every request of `fetch_json`, `http:` included, goes through a tunnel the proxy relays unread.

The tunnel names the host: the proxy resolves it, so the address can't be pinned. The SSRF guard has checked the host
before (INV-16).
"""

import asyncio
import contextlib
import ssl
from collections.abc import Iterable
from typing import cast

import httpcore
import httpx

from crawlerai.acquire.ssrf import bracketed
from crawlerai.core.proxy import ProxyEndpoint

__all__ = ["TunnelRefused", "open_tunnel", "tunnelled_transport"]

# The longest CONNECT response head read: a proxy that sends more is refused rather than buffered without bound.
_HEAD_MAX_BYTES = 16_384


class TunnelRefused(Exception):
    """The proxy answered a CONNECT with no 2xx, or with no readable response. The message names no host or
    credential."""

    def __init__(self) -> None:
        super().__init__("proxy_refused")


async def open_tunnel(proxy: ProxyEndpoint, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """A CONNECT tunnel to `host`:`port` through `proxy`; any 2xx answer opens it. Raises `OSError` when the proxy
    can't be reached and `TunnelRefused` when it refuses the tunnel."""
    reader, writer = await asyncio.open_connection(proxy.host, proxy.port, limit=_HEAD_MAX_BYTES)
    # RFC 9112 §3.2.3: CONNECT names the authority.
    authority_form = f"{bracketed(host)}:{port}"
    head = [f"CONNECT {authority_form} HTTP/1.1", f"Host: {authority_form}"]
    if proxy.authorization is not None:
        head.append(f"Proxy-Authorization: {proxy.authorization}")
    try:
        # The host is ASCII: a browser names it in IDNA (A-label) form, and URL parsing gives the JSON rung the same.
        writer.write(("\r\n".join(head) + "\r\n\r\n").encode("ascii"))
        await writer.drain()
        # A 2xx CONNECT response ends with its header section: what follows belongs to the tunnel (RFC 9110 §9.3.6).
        response = await reader.readuntil(b"\r\n\r\n")
    except (OSError, UnicodeEncodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as e:
        writer.close()
        raise TunnelRefused from e
    # RFC 9112 §4: status-line = HTTP-version SP status-code SP [ reason-phrase ].
    fields = response.split(b" ", 2)
    if len(fields) < 2 or not fields[1].startswith(b"2"):
        writer.close()
        raise TunnelRefused
    return reader, writer


def tunnelled_transport(proxy: ProxyEndpoint) -> httpx.AsyncHTTPTransport:
    """httpx's transport, with every connection a tunnel through `proxy` (`Tunnels`). httpx takes no network backend,
    so the transport's connection pool is replaced by one on `Tunnels`, with httpx's own TLS context."""
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=httpx.create_ssl_context(trust_env=False), network_backend=Tunnels(proxy)
    )
    return transport


class Tunnels(httpcore.AsyncNetworkBackend):
    """An httpcore network backend whose TCP connections are CONNECT tunnels through `proxy`: httpcore then speaks to
    the origin as if connected directly (TLS with the origin's name, origin-form requests)."""

    def __init__(self, proxy: ProxyEndpoint) -> None:
        self._proxy = proxy

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            async with asyncio.timeout(timeout):
                reader, writer = await open_tunnel(self._proxy, host, port)
        except TimeoutError as e:
            raise httpcore.ConnectTimeout("proxy_timeout") from e
        except (OSError, TunnelRefused) as e:
            # httpx reports it as `ProxyError`, by class name only (`acquire.api._reason`).
            raise httpcore.ProxyError("proxy_refused") from e
        return _Stream(reader, writer)

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[object] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("unix sockets are not tunnelled")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _Stream(httpcore.AsyncNetworkStream):
    """An asyncio stream pair as an httpcore network stream, its errors mapped to httpcore's."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        try:
            async with asyncio.timeout(timeout):
                return await self._reader.read(max_bytes)
        except TimeoutError as e:
            raise httpcore.ReadTimeout("read_timeout") from e
        except OSError as e:
            raise httpcore.ReadError("read_error") from e

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        try:
            async with asyncio.timeout(timeout):
                self._writer.write(buffer)
                await self._writer.drain()
        except TimeoutError as e:
            raise httpcore.WriteTimeout("write_timeout") from e
        except OSError as e:
            raise httpcore.WriteError("write_error") from e

    async def aclose(self) -> None:
        self._writer.close()
        with contextlib.suppress(OSError):
            await self._writer.wait_closed()

    async def start_tls(
        self, ssl_context: ssl.SSLContext, server_hostname: str | None = None, timeout: float | None = None
    ) -> httpcore.AsyncNetworkStream:
        try:
            await self._writer.start_tls(ssl_context, server_hostname=server_hostname, ssl_handshake_timeout=timeout)
        except TimeoutError as e:
            raise httpcore.ConnectTimeout("tls_timeout") from e
        except (OSError, ssl.SSLError) as e:
            raise httpcore.ConnectError("tls_error") from e
        return self

    def get_extra_info(self, info: str) -> object:
        if info == "is_readable":
            # httpcore asks whether an idle pooled connection has data or EOF waiting, which means it was dropped.
            return self._reader.at_eof()
        return cast(object, self._writer.get_extra_info(info))
