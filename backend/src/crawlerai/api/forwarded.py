"""The client address of a request (rest-api spec, INV-32). `Forwarded` (RFC 7239) and `X-Forwarded-For` are written by
whoever sends them (RFC 7239 §8.1), so they are read only when the peer is a configured trusted proxy, and then from
the right, through trusted hops only: the first hop that is not a trusted proxy is the client. Hops further left were
written by that client and are ignored."""

from collections.abc import Iterable, Iterator, Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

Address = IPv4Address | IPv6Address
Network = IPv4Network | IPv6Network
UNKNOWN_CLIENT = "unknown"


def _forwarded_for(value: str) -> Iterator[str]:
    """The `for` parameter of each element of a `Forwarded` value (RFC 7239 §4), in order; "" when one has none."""
    for element in value.split(","):
        node = ""
        for pair in element.split(";"):
            name, _, parameter = pair.partition("=")
            if name.strip().lower() == "for":  # parameter names are case-insensitive (§4)
                node = parameter.strip().strip('"')
        yield node


def _node_address(node: str) -> Address | None:
    """The IP address of a node (RFC 7239 §6): `192.0.2.1`, `192.0.2.1:80`, `[2001:db8::1]` or `[2001:db8::1]:80`;
    None for `unknown`, an obfuscated identifier, or anything else that is not an address."""
    if node.startswith("["):
        node = node[1 : node.find("]")]
    elif node.count(":") == 1:  # an IPv4 address with a port; a bare IPv6 address has several colons
        node = node.partition(":")[0]
    try:
        return ip_address(node)
    except ValueError:
        return None


def _hops(headers: Iterable[tuple[str, str]]) -> list[str]:
    """The forwarded hops, client side first. `Forwarded` is the standard; `X-Forwarded-For` is read without it.
    Repeated header lines concatenate in order (RFC 9110 §5.3)."""
    forwarded = [value for name, value in headers if name.lower() == "forwarded"]
    if forwarded:
        return [node for value in forwarded for node in _forwarded_for(value)]
    x_forwarded = [value for name, value in headers if name.lower() == "x-forwarded-for"]
    return [node.strip() for value in x_forwarded for node in value.split(",")]


def _trusted(address: Address, proxies: Sequence[Network]) -> bool:
    return any(address in network for network in proxies)


def client_address(peer: str | None, headers: Iterable[tuple[str, str]], proxies: Sequence[Network]) -> str:
    """The client's address: the peer's, unless the peer is a trusted proxy that forwards a readable one."""
    if peer is None:
        return UNKNOWN_CLIENT
    peer_address = _node_address(peer)
    if peer_address is None or not _trusted(peer_address, proxies):
        return peer
    client = peer_address
    for node in reversed(_hops(headers)):
        address = _node_address(node)
        if address is None:
            # An unreadable hop hides who is behind it; the last address we could read stands for the client.
            break
        client = address
        if not _trusted(address, proxies):
            break
    return str(client)
