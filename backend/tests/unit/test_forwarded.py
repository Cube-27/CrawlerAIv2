"""The client address behind trusted proxies (rest-api spec, INV-32): `Forwarded` (RFC 7239) and `X-Forwarded-For` are
client-controlled (RFC 7239 §8.1), so they are read only when the peer is a configured trusted proxy, and then only up
to the nearest hop that is not one."""

from ipaddress import ip_network

import pytest

from crawlerai.api.forwarded import client_address

PROXIES = (ip_network("10.0.0.0/8"), ip_network("2001:db8:ffff::/48"))


def test_an_untrusted_peer_is_the_client_whatever_it_forwards() -> None:
    headers = [("forwarded", "for=203.0.113.5"), ("x-forwarded-for", "198.51.100.9")]
    assert client_address("192.0.2.1", headers, PROXIES) == "192.0.2.1"
    assert client_address("10.0.0.1", headers, ()) == "10.0.0.1"


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
