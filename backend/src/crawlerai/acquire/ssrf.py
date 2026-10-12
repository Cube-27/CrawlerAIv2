"""SSRF guard: every outbound target is a public IP, on every redirect hop (SPEC-02 §4.5, ARCHITECTURE §7.1, §18,
INV-16). It fails closed: anything it can't prove public is rejected.

Fetchers call `SafeConnector.check` before the first request and `SafeConnector.redirect` before each hop they
follow, and connect only to `Target.ip`. The resolver is injected so tests run without DNS.
"""

import asyncio
import re
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address, IPv6Network, ip_address
from typing import Literal
from urllib.parse import urljoin, urlsplit

IPAddress = IPv4Address | IPv6Address
Resolver = Callable[[str], Awaitable[Sequence[IPAddress]]]
RejectReason = Literal["scheme", "host", "port", "dns", "private_address"]

_SCHEMES = {"http": 80, "https": 443}
# Ports a web page is served on: the http/https defaults (RFC 9110 §4.2) and their registered alternates
# (IANA service names http-alt 8080, pcsync-https 8443). Anything else could reach a non-web service.
_PORTS = frozenset({80, 443, 8080, 8443})
# WHATWG URL Standard §3.5 "ends in a number checker": a host whose last label is decimal digits or 0x-hex is
# parsed as an IPv4 address (`2130706433`, `0x7f.1`, `127.1`). Only canonical dotted quads are accepted, so the
# address checked here is the one any client would connect to.
_ENDS_IN_NUMBER = re.compile(r"(?i)(?:^|\.)(?:[0-9]+|0x[0-9a-f]*)\.?$")
# RFC 6052 §2.1: the NAT64 well-known prefix embeds an IPv4 address in its last 32 bits.
_NAT64 = IPv6Network("64:ff9b::/96")


class SsrfRejected(Exception):
    """The message never contains the URL, so logs stay redacted when configured (SPEC-02 §4.11)."""

    def __init__(self, reason: RejectReason) -> None:
        super().__init__(f"ssrf_rejected: {reason}")
        self.reason: RejectReason = reason


@dataclass(frozen=True)
class Target:
    """A checked URL and the address to connect to for it."""

    url: str
    host: str
    port: int
    ip: IPAddress


def is_public(ip: IPAddress) -> bool:
    """`is_global` follows the IANA special-purpose address registries (RFC 6890): it excludes private (RFC 1918),
    loopback, link-local (including the 169.254.169.254 metadata address), unique-local (RFC 4193), unspecified,
    shared, documentation and reserved ranges. Multicast (RFC 5771, RFC 4291 §2.7) is excluded on top. An IPv6
    address that embeds an IPv4 address (RFC 4291 §2.5.5.2 mapped, RFC 6052 NAT64) is public only if that IPv4
    address is."""
    if isinstance(ip, IPv6Address):
        embedded = ip.ipv4_mapped or (IPv4Address(int(ip) & 0xFFFFFFFF) if ip in _NAT64 else None)
        if embedded is not None:
            return is_public(embedded)
    return ip.is_global and not ip.is_multicast


async def system_resolver(host: str) -> list[IPAddress]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    # An IPv6 sockaddr may carry a zone (`fe80::1%eth0`); the zone does not change which range the address is in.
    return [ip_address(str(info[4][0]).split("%", 1)[0]) for info in infos]


async def resolve_public(host: str, resolver: Resolver = system_resolver) -> IPAddress:
    """Resolve once and return the address to pin; reject if resolution fails or any address is not public."""
    try:
        addresses = await resolver(host)
    except OSError as e:
        raise SsrfRejected("dns") from e
    if not addresses:
        raise SsrfRejected("dns")
    if not all(is_public(a) for a in addresses):
        raise SsrfRejected("private_address")
    return addresses[0]


class SafeConnector:
    def __init__(self, resolver: Resolver = system_resolver) -> None:
        self._resolver = resolver

    async def check(self, url: str) -> Target:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in _SCHEMES:
            raise SsrfRejected("scheme")
        host = parts.hostname
        if not host:
            raise SsrfRejected("host")
        try:
            explicit = parts.port
        except ValueError as e:
            raise SsrfRejected("port") from e
        port = _SCHEMES[scheme] if explicit is None else explicit
        if port not in _PORTS:
            raise SsrfRejected("port")

        literal = _literal_ip(host)
        if literal is not None:
            if not is_public(literal):
                raise SsrfRejected("private_address")
            return Target(url=url, host=host, port=port, ip=literal)
        if _ENDS_IN_NUMBER.search(host):
            raise SsrfRejected("host")
        return Target(url=url, host=host, port=port, ip=await resolve_public(host, self._resolver))

    async def redirect(self, current: Target, location: str) -> Target:
        """The next hop of a redirect: `location` is resolved against the current URL (RFC 9110 §10.2.2) and
        checked from scratch."""
        return await self.check(urljoin(current.url, location))


def _literal_ip(host: str) -> IPAddress | None:
    try:
        return ip_address(host)
    except ValueError:
        return None
