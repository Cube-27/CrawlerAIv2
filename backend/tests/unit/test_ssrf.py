"""SSRF guard (SPEC-02 §4.5, ARCHITECTURE §7.1 and §18, INV-16). A stub resolver stands in for DNS; no network."""

import asyncio
import socket
from collections.abc import Sequence
from ipaddress import IPv4Address, IPv6Address, ip_address

import pytest

from crawlerai.acquire.ssrf import IPAddress, RejectReason, SafeConnector, SsrfRejected, Target, is_public

_PUBLIC_V4 = "93.184.215.14"
_PUBLIC_V6 = "2606:2800:21f:cb07::1"

# One address per range the guard must reject, with the standard that reserves it.
_NON_PUBLIC = [
    "10.0.0.1",  # RFC 1918
    "172.16.0.1",  # RFC 1918
    "172.31.255.255",  # RFC 1918
    "192.168.1.1",  # RFC 1918
    "127.0.0.1",  # loopback, RFC 1122
    "127.255.255.254",
    "0.0.0.0",  # noqa: S104 -- unspecified / "this network", RFC 1122; a value under test, not a bind address
    "169.254.0.1",  # link-local, RFC 3927
    "169.254.169.254",  # cloud metadata, inside link-local
    "100.64.0.1",  # shared address space, RFC 6598
    "192.0.0.1",  # IETF protocol assignments, RFC 6890
    "192.0.2.1",  # documentation, RFC 5737
    "198.18.0.1",  # benchmarking, RFC 2544
    "240.0.0.1",  # reserved, RFC 1112
    "255.255.255.255",  # limited broadcast, RFC 919
    "224.0.0.1",  # multicast, RFC 5771
    "239.255.255.250",  # multicast
    "::1",  # loopback, RFC 4291
    "::",  # unspecified, RFC 4291
    "fe80::1",  # link-local, RFC 4291
    "fc00::1",  # unique-local, RFC 4193
    "fd12:3456::1",  # unique-local
    "ff02::1",  # multicast, RFC 4291
    "::ffff:127.0.0.1",  # IPv4-mapped loopback, RFC 4291
    "::ffff:10.0.0.1",  # IPv4-mapped private
    "::ffff:169.254.169.254",  # IPv4-mapped metadata
    "::127.0.0.1",  # IPv4-compatible (deprecated, RFC 4291 §2.5.5.1), inside the IETF-reserved ::/8
    "::10.0.0.1",
    "::169.254.169.254",
    "::93.184.215.14",  # IPv4-compatible is rejected even when the embedded address is public
    "4000::1",  # outside 2000::/3, the only IPv6 global unicast allocation (IANA IPv6 address space)
    "64:ff9b::7f00:1",  # NAT64 well-known prefix embedding 127.0.0.1, RFC 6052
    "64:ff9b::a9fe:a9fe",  # NAT64 embedding 169.254.169.254
    "2002:7f00:1::1",  # 6to4 embedding 127.0.0.1, RFC 3056
    "2001:db8::1",  # documentation, RFC 3849
]


class StubResolver:
    def __init__(self, table: dict[str, Sequence[str]]) -> None:
        self.table = table
        self.calls: list[str] = []

    async def __call__(self, host: str) -> list[IPAddress]:
        self.calls.append(host)
        if host not in self.table:
            raise socket.gaierror(socket.EAI_NONAME, "not found")
        return [ip_address(a) for a in self.table[host]]


def _reason(connector: SafeConnector, url: str) -> RejectReason:
    with pytest.raises(SsrfRejected) as e:
        asyncio.run(connector.check(url))
    return e.value.reason


@pytest.mark.parametrize("address", _NON_PUBLIC)
def test_is_public_rejects_reserved_ranges(address: str) -> None:
    assert is_public(ip_address(address)) is False


@pytest.mark.parametrize("address", [_PUBLIC_V4, _PUBLIC_V6, "::ffff:93.184.215.14", "64:ff9b::5db8:d70e"])
def test_is_public_accepts_global_unicast(address: str) -> None:
    assert is_public(ip_address(address)) is True


@pytest.mark.parametrize("address", _NON_PUBLIC)
def test_host_resolving_to_a_reserved_address_is_rejected(address: str) -> None:
    connector = SafeConnector(StubResolver({"www.example.com": [address]}))
    assert _reason(connector, "https://www.example.com/p") == "private_address"


@pytest.mark.parametrize("address", _NON_PUBLIC)
def test_literal_reserved_ip_is_rejected_without_dns(address: str) -> None:
    resolver = StubResolver({})
    host = f"[{address}]" if ":" in address else address
    assert _reason(SafeConnector(resolver), f"http://{host}/") == "private_address"
    assert resolver.calls == []


def test_host_that_cannot_be_idna_encoded_is_rejected_as_host() -> None:
    # The system resolver encodes the host (IDNA, RFC 5891) before any lookup; a label over 63 octets
    # (RFC 1035 §2.3.4) fails there, so no query leaves the process.
    assert _reason(SafeConnector(), f"https://{'a' * 64}.example.com/") == "host"


def test_any_reserved_address_among_several_rejects() -> None:
    connector = SafeConnector(StubResolver({"www.example.com": [_PUBLIC_V4, "10.1.2.3"]}))
    assert _reason(connector, "https://www.example.com/") == "private_address"


@pytest.mark.parametrize(
    ("table", "reason"),
    [({}, "dns"), ({"www.example.com": []}, "dns")],
)
def test_resolution_failure_fails_closed(table: dict[str, Sequence[str]], reason: RejectReason) -> None:
    assert _reason(SafeConnector(StubResolver(table)), "https://www.example.com/") == reason


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://www.example.com/",
        "gopher://www.example.com/",
        "data:text/html,hi",
        "javascript:alert(1)",
        "//www.example.com/",
        "www.example.com",
    ],
)
def test_non_http_schemes_are_rejected(url: str) -> None:
    assert _reason(SafeConnector(StubResolver({"www.example.com": [_PUBLIC_V4]})), url) == "scheme"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.example.com:22/",
        "https://www.example.com:6379/",
        "http://www.example.com:0/",
        "http://www.example.com:99999/",
    ],
)
def test_ports_outside_the_web_set_are_rejected(url: str) -> None:
    assert _reason(SafeConnector(StubResolver({"www.example.com": [_PUBLIC_V4]})), url) == "port"


# Hosts the WHATWG URL Standard parses as IPv4 although they are not dotted quads.
_NUMERIC_HOSTS = ["2130706433", "0x7f.1", "127.1", "127.0.0.1.", "017700000001", "www.example.0x7f"]


@pytest.mark.parametrize("url", ["http:///p", "http://:80/", *(f"http://{host}/" for host in _NUMERIC_HOSTS)])
def test_malformed_or_non_canonical_hosts_are_rejected(url: str) -> None:
    resolver = StubResolver({})
    assert _reason(SafeConnector(resolver), url) == "host"
    assert resolver.calls == []


@pytest.mark.parametrize(
    ("url", "port"),
    [
        ("http://www.example.com/", 80),
        ("https://www.example.com/", 443),
        ("http://www.example.com:8080/", 8080),
        ("https://www.example.com:8443/", 8443),
        ("HTTPS://WWW.EXAMPLE.COM/", 443),
    ],
)
def test_public_target_is_pinned_to_the_checked_address(url: str, port: int) -> None:
    resolver = StubResolver({"www.example.com": [_PUBLIC_V4, _PUBLIC_V6]})
    target = asyncio.run(SafeConnector(resolver).check(url))
    assert target == Target(url=url, host="www.example.com", port=port, ip=IPv4Address(_PUBLIC_V4))
    assert resolver.calls == ["www.example.com"]


def test_literal_public_ipv6_is_accepted_without_dns() -> None:
    resolver = StubResolver({})
    target = asyncio.run(SafeConnector(resolver).check(f"https://[{_PUBLIC_V6}]/x"))
    assert target == Target(url=f"https://[{_PUBLIC_V6}]/x", host=_PUBLIC_V6, port=443, ip=IPv6Address(_PUBLIC_V6))
    assert resolver.calls == []


def test_redirect_to_a_private_address_is_rejected_after_a_public_first_hop() -> None:
    resolver = StubResolver({"www.example.com": [_PUBLIC_V4], "internal.example.net": ["10.0.0.5"]})
    connector = SafeConnector(resolver)
    first = asyncio.run(connector.check("https://www.example.com/start"))
    assert first.ip == IPv4Address(_PUBLIC_V4)
    with pytest.raises(SsrfRejected) as e:
        asyncio.run(connector.redirect(first, "http://internal.example.net/admin"))
    assert e.value.reason == "private_address"
    assert resolver.calls == ["www.example.com", "internal.example.net"]


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://169.254.169.254/latest/meta-data/", "private_address"),
        ("http://[::ffff:127.0.0.1]/", "private_address"),
        ("file:///etc/passwd", "scheme"),
        ("ftp://www.example.com/", "scheme"),
        ("https://www.example.com:22/", "port"),
        # A scheme-relative location keeps the current scheme and is checked like any other.
        (f"//{_NUMERIC_HOSTS[1]}/", "host"),
    ],
)
def test_every_redirect_hop_is_rechecked(location: str, reason: RejectReason) -> None:
    connector = SafeConnector(StubResolver({"www.example.com": [_PUBLIC_V4]}))
    first = asyncio.run(connector.check("https://www.example.com/start"))
    with pytest.raises(SsrfRejected) as e:
        asyncio.run(connector.redirect(first, location))
    assert e.value.reason == reason


def test_relative_redirect_resolves_against_the_current_url_and_is_rechecked() -> None:
    resolver = StubResolver({"www.example.com": [_PUBLIC_V4]})
    connector = SafeConnector(resolver)
    first = asyncio.run(connector.check("https://www.example.com/a/b"))
    hop = asyncio.run(connector.redirect(first, "../c?q=1"))
    assert hop == Target(url="https://www.example.com/c?q=1", host="www.example.com", port=443, ip=first.ip)
    assert resolver.calls == ["www.example.com", "www.example.com"]


def test_rejection_message_does_not_carry_the_url() -> None:
    # Logs redact URLs when configured (SPEC-02 §4.11); the exception must not leak them.
    connector = SafeConnector(StubResolver({"secret.example.com": ["10.0.0.1"]}))
    with pytest.raises(SsrfRejected) as e:
        asyncio.run(connector.check("https://secret.example.com/token=abc"))
    assert str(e.value) == "ssrf_rejected: private_address"
