"""The TLS ClientHello a client sends, read on the loopback address, and its JA4 fingerprint: how the browser rung's
Chrome and the HTTP rung's impersonation open a connection (`acquire.impersonate`).

A listener of this process on the loopback address reads the first ClientHello it receives (RFC 8446 §4.1.2, in one
TLS record, §5.1) and closes the connection; the client's request fails, and nothing leaves the machine.
"""

import asyncio
import contextlib
import hashlib
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlunsplit

__all__ = ["HELLO_HOST", "ClientHello", "hello_listener", "ja4", "parse_client_hello"]

# A host name, not an address, so a client sends the server_name extension it sends to a site (RFC 6066 §3 names
# no address); `localhost` resolves to the loopback address in each client (RFC 6761 §6.3).
HELLO_HOST: Final = "localhost"
_LOOPBACK: Final = "127.0.0.1"
_LOOPBACK_IPV6: Final = "::1"
_HANDSHAKE: Final = 22  # TLS ContentType handshake (RFC 8446 §5.1)
_CLIENT_HELLO: Final = 1  # HandshakeType client_hello (RFC 8446 §4)
_SERVER_NAME: Final = 0x0000  # RFC 6066 §3
_SIGNATURE_ALGORITHMS: Final = 0x000D  # RFC 8446 §4.2.3
_ALPN: Final = 0x0010  # RFC 7301 §3.1
_SUPPORTED_VERSIONS: Final = 0x002B  # RFC 8446 §4.2.1
# draft-ietf-tls-trust-anchor-ids §4.1 `trust_anchors`, at BoringSSL's provisional code point.
_TRUST_ANCHORS: Final = 0xCA34
# JA4's version labels (FoxIO JA4 specification, TLS client, part a): TLS 1.3 to SSL 2, then DTLS 1.0, 1.2, 1.3.
_VERSIONS: Final = {
    0x0304: "13",
    0x0303: "12",
    0x0302: "11",
    0x0301: "10",
    0x0300: "s3",
    0x0002: "s2",
    0xFEFF: "d1",
    0xFEFD: "d2",
    0xFEFC: "d3",
}
_UNHASHED: Final = "000000000000"


@dataclass(frozen=True)
class ClientHello:
    """What a ClientHello offers, in its order; GREASE values (RFC 8701) included."""

    version: int  # legacy_version
    ciphers: tuple[int, ...]
    extensions: tuple[int, ...]
    supported_versions: tuple[int, ...] = ()
    signature_algorithms: tuple[int, ...] = ()
    alpn: tuple[bytes, ...] = ()
    trust_anchors: tuple[str, ...] | None = None  # relative OIDs; None: the extension is absent


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.at = 0

    def take(self, size: int) -> bytes:
        if self.at + size > len(self.data):
            raise ValueError("truncated ClientHello")
        chunk = self.data[self.at : self.at + size]
        self.at += size
        return chunk

    def number(self, size: int) -> int:
        return int.from_bytes(self.take(size))

    def vector(self, length_size: int) -> "_Reader":
        return _Reader(self.take(self.number(length_size)))

    def __bool__(self) -> bool:
        return self.at < len(self.data)


def parse_client_hello(record: bytes) -> ClientHello:
    """The ClientHello in one TLS record (RFC 8446 §5.1, §4.1.2). Raises `ValueError` on anything else."""
    reader = _Reader(record)
    if reader.number(1) != _HANDSHAKE:
        raise ValueError("not a handshake record")
    reader.take(2)  # legacy_record_version
    body = reader.vector(2)
    if body.number(1) != _CLIENT_HELLO:
        raise ValueError("not a ClientHello")
    hello = body.vector(3)
    version = hello.number(2)
    hello.take(32)  # random
    hello.vector(1)  # legacy_session_id
    ciphers = _numbers(hello.vector(2), 2)
    hello.vector(1)  # legacy_compression_methods
    fields: dict[str, object] = {}
    types = []
    extensions = hello.vector(2) if hello else _Reader(b"")
    while extensions:
        kind = extensions.number(2)
        types.append(kind)
        _read_extension(kind, extensions.vector(2), fields)
    return ClientHello(version, ciphers, tuple(types), **fields)  # type: ignore[arg-type]


def _read_extension(kind: int, data: _Reader, fields: dict[str, object]) -> None:
    if kind == _SUPPORTED_VERSIONS:
        fields["supported_versions"] = _numbers(data.vector(1), 2)
    elif kind == _SIGNATURE_ALGORITHMS:
        fields["signature_algorithms"] = _numbers(data.vector(2), 2)
    elif kind == _ALPN:
        names = data.vector(2)
        fields["alpn"] = tuple(_items(names, 1))
    elif kind == _TRUST_ANCHORS:
        fields["trust_anchors"] = tuple(_relative_oid(anchor) for anchor in _items(data.vector(2), 1))


def _numbers(reader: _Reader, size: int) -> tuple[int, ...]:
    values = []
    while reader:
        values.append(reader.number(size))
    return tuple(values)


def _items(reader: _Reader, length_size: int) -> Iterator[bytes]:
    while reader:
        yield reader.take(reader.number(length_size))


def _relative_oid(encoded: bytes) -> str:
    """A relative object identifier's dotted form (ITU-T X.690 §8.20: base-128 subidentifiers, high bit set on all
    but the last octet of each)."""
    arcs = []
    value = 0
    for octet in encoded:
        value = value << 7 | octet & 0x7F
        if not octet & 0x80:
            arcs.append(value)
            value = 0
    return ".".join(map(str, arcs))


def _grease(value: int) -> bool:
    """RFC 8701 §2: 0x0A0A, 0x1A1A, ... 0xFAFA."""
    return value & 0x0F0F == 0x0A0A and value >> 8 == value & 0xFF


def ja4(hello: ClientHello, transport: str = "t") -> str:
    """The JA4 fingerprint of `hello` (FoxIO JA4 specification, TLS client; `transport` `t` for TCP): protocol,
    version, SNI, cipher and extension counts and ALPN; the truncated SHA-256 of the sorted ciphers; that of the
    sorted extensions without SNI and ALPN, then the signature algorithms in their order. GREASE is ignored."""
    ciphers = [value for value in hello.ciphers if not _grease(value)]
    extensions = [value for value in hello.extensions if not _grease(value)]
    offered = [value for value in hello.supported_versions if not _grease(value)]
    version = _VERSIONS.get(max(offered, default=hello.version), "00")
    sni = "d" if _SERVER_NAME in extensions else "i"
    head = f"{transport}{version}{sni}{min(len(ciphers), 99):02d}{min(len(extensions), 99):02d}{_alpn(hello.alpn)}"
    hashed = sorted(value for value in extensions if value not in (_SERVER_NAME, _ALPN))
    algorithms = [value for value in hello.signature_algorithms if not _grease(value)]
    listed = _hex(hashed) + (f"_{_hex(algorithms)}" if algorithms else "")
    return f"{head}_{_hash(_hex(sorted(ciphers)), ciphers)}_{_hash(listed, hashed)}"


def _alpn(protocols: tuple[bytes, ...]) -> str:
    if not protocols or not protocols[0]:
        return "00"
    first = protocols[0]
    ends = chr(first[0]) + chr(first[-1])
    return ends if ends.isascii() and ends.isalnum() else first.hex()[0] + first.hex()[-1]


def _hex(values: list[int]) -> str:
    return ",".join(f"{value:04x}" for value in values)


def _hash(text: str, values: list[int]) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12] if values else _UNHASHED


@asynccontextmanager
async def hello_listener() -> AsyncIterator[tuple[str, "asyncio.Future[ClientHello]"]]:
    """A listener on the loopback addresses that reads the first ClientHello sent to it (module docstring): the URL a
    client opens, and the ClientHello once a client has sent it (a malformed one leaves it unset)."""
    first: asyncio.Future[ClientHello] = asyncio.get_running_loop().create_future()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(OSError, ValueError, asyncio.IncompleteReadError):
            header = await reader.readexactly(5)
            if header[0] == _HANDSHAKE and not first.done():
                record = header + await reader.readexactly(int.from_bytes(header[3:5]))
                first.set_result(parse_client_hello(record))
        writer.close()

    async with contextlib.AsyncExitStack() as servers:
        ipv4 = await servers.enter_async_context(await asyncio.start_server(serve, _LOOPBACK, 0))
        port = ipv4.sockets[0].getsockname()[1]
        # `localhost` may resolve to the IPv6 loopback address alone (RFC 6761 §6.3 names both): the same port there,
        # unless the machine has no IPv6 or the port is taken on it.
        with contextlib.suppress(OSError):
            await servers.enter_async_context(await asyncio.start_server(serve, _LOOPBACK_IPV6, port))
        yield urlunsplit(("https", f"{HELLO_HOST}:{port}", "/", "", "")), first
