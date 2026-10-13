"""The client address behind trusted proxies (SPEC-07 §4.2, INV-32): `Forwarded` (RFC 7239) and `X-Forwarded-For` are
client-controlled (RFC 7239 §8.1), so they are read only when the peer is a configured trusted proxy, and then only up
to the nearest hop that is not one."""

from ipaddress import ip_network

import pytest

from crawlerai.api.forwarded import client_address

PROXIES = (ip_network("10.0.0.0/8"), ip_network("2001:db8:ffff::/48"))


@pytest.mark.parametrize(
    "headers",
    [
        {"forwarded": "for=203.0.113.5"},
        {"x-forwarded-for": "203.0.113.5"},
        {"forwarded": "for=203.0.113.5", "x-forwarded-for": "198.51.100.9"},
    ],
)
def test_an_untrusted_peer_is_the_client_whatever_it_forwards(headers: dict[str, str]) -> None:
    assert client_address("192.0.2.1", list(headers.items()), PROXIES) == "192.0.2.1"
    assert client_address("10.0.0.1", list(headers.items()), ()) == "10.0.0.1"


@pytest.mark.parametrize(
    ("headers", "client"),
    [
        ([("x-forwarded-for", "203.0.113.5")], "203.0.113.5"),
        ([("forwarded", "for=203.0.113.5;proto=https")], "203.0.113.5"),
        ([("forwarded", 'for="[2001:db8::1]:4711"')], "2001:db8::1"),
        ([("forwarded", 'For="203.0.113.5:80"')], "203.0.113.5"),
        # `Forwarded` is the standard header; `X-Forwarded-For` is read only without it.
        ([("forwarded", "for=203.0.113.5"), ("x-forwarded-for", "198.51.100.9")], "203.0.113.5"),
    ],
)
def test_a_trusted_peer_forwards_the_client(headers: list[tuple[str, str]], client: str) -> None:
    assert client_address("10.0.0.1", headers, PROXIES) == client


@pytest.mark.parametrize(
    "headers",
    [
        # The leftmost hop was written by the client, so it may be spoofed: the nearest untrusted hop is the client.
        [("x-forwarded-for", "198.51.100.1, 203.0.113.5, 10.0.0.2")],
        [("x-forwarded-for", "198.51.100.1"), ("x-forwarded-for", "203.0.113.5, 10.0.0.2")],
        [("forwarded", "for=198.51.100.1, for=203.0.113.5"), ("forwarded", "for=10.0.0.2;by=10.0.0.1")],
    ],
)
def test_hops_are_read_from_the_right_up_to_the_first_untrusted_one(headers: list[tuple[str, str]]) -> None:
    assert client_address("10.0.0.1", headers, PROXIES) == "203.0.113.5"


def test_a_chain_of_trusted_proxies_only_ends_at_its_leftmost_hop() -> None:
    headers = [("x-forwarded-for", "10.1.1.1, 2001:db8:ffff::5")]
    assert client_address("10.0.0.1", headers, PROXIES) == "10.1.1.1"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("forwarded", "for=unknown")],  # RFC 7239 §6.2
        [("forwarded", "for=_hidden")],  # an obfuscated identifier (§6.3)
        [("forwarded", "proto=https")],
        [("x-forwarded-for", "not an address")],
        [("x-forwarded-for", "198.51.100.1, garbage")],
    ],
)
def test_a_trusted_peer_without_a_readable_client_is_the_client(headers: list[tuple[str, str]]) -> None:
    assert client_address("10.0.0.1", headers, PROXIES) == "10.0.0.1"


def test_no_peer_is_an_unknown_client() -> None:
    assert client_address(None, [("x-forwarded-for", "203.0.113.5")], PROXIES) == "unknown"
