"""Proxy pools (ARCHITECTURE §7.1, SPEC-02 §3, OPEN_QUESTIONS #10): one datacenter or ISP proxy per pool, configured
by hand in `CRAWLERAI_PROXY_POOLS` as `{pool_name: proxy_url}`, and used for a site whose `proxy_pool` names it.

Being configured is the allowlist §7.1 asks of proxy endpoints: the SSRF guard checks the pages' hosts, not the
proxy's own address. Only HTTP proxies are supported, and every request goes through a CONNECT tunnel
(RFC 9110 §9.3.6), so the proxy relays bytes it doesn't read.
"""

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Self
from urllib.parse import unquote, urlsplit

__all__ = ["ProxyEndpoint", "UnknownProxyPool", "pool_endpoint"]

_HTTP_DEFAULT_PORT = 80  # RFC 9110 §4.2.1


@dataclass(frozen=True)
class ProxyEndpoint:
    host: str
    port: int
    # Credentials stay out of reprs, and so out of logs and error reports.
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)

    @classmethod
    def parse(cls, url: object) -> Self:
        """`http://[user[:password]@]host[:port]`. Error messages never contain the URL: it may hold a password."""
        if not isinstance(url, str):
            raise ValueError("a proxy URL is a string")  # a ValueError, which pydantic reports as a validation error
        parts = urlsplit(url)
        if parts.scheme.lower() != "http":
            raise ValueError("a proxy URL must use the http scheme")
        if not parts.hostname or parts.path not in ("", "/") or parts.query or parts.fragment:
            raise ValueError("a proxy URL is http://[user[:password]@]host[:port]")
        try:
            port = parts.port or _HTTP_DEFAULT_PORT
        except ValueError:
            # urllib's message quotes the port; `from None` keeps it, and the URL, out of the error.
            raise ValueError("a proxy URL has an invalid port") from None
        username = None if parts.username is None else unquote(parts.username)
        password = None if parts.password is None else unquote(parts.password)
        return cls(host=parts.hostname, port=port, username=username, password=password)

    @property
    def authorization(self) -> str | None:
        """The `Proxy-Authorization` value (RFC 9110 §11.7.2) for the configured credentials: Basic (RFC 7617)."""
        if self.username is None:
            return None
        credentials = f"{self.username}:{self.password or ''}".encode()
        return f"Basic {base64.b64encode(credentials).decode('ascii')}"


class UnknownProxyPool(Exception):
    """A fetch named a pool that isn't configured. It is refused rather than fetched without the pool."""

    def __init__(self) -> None:
        super().__init__("proxy_pool_unknown")


def pool_endpoint(name: str | None, pools: Mapping[str, ProxyEndpoint] | None) -> ProxyEndpoint | None:
    """The endpoint of pool `name` among `pools` (none configured when None), or None when no pool is asked for."""
    if name is None:
        return None
    endpoint = (pools or {}).get(name)
    if endpoint is None:
        raise UnknownProxyPool
    return endpoint
