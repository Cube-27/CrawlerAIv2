"""Proxy pools: datacenter or ISP proxies configured by hand in
`CRAWLERAI_PROXY_POOLS`, and used for a fetch whose `proxy_pool` names its pool. A pool is one proxy URL, or
`{"endpoints": [url, ...], "mode": "rotate" | "sticky"}`: `rotate` takes its endpoints in turn, `sticky` keeps
each site on one endpoint (rendezvous hashing, Thaler and Ravishankar 1998: a site moves only when its endpoint leaves
the choice). A pool may declare the `country` its endpoints go out from (ISO 3166-1 alpha-2: one pool, one country),
which records state as their egress (`core/egress.py`). An endpoint in quarantine (`proxy_health`) is chosen only
when every endpoint of the pool is, and then the one that recovers first: a pool never sends a site's request direct.

Being configured is the allowlist §7.1 asks of proxy endpoints: the SSRF guard checks the pages' hosts, not the
proxy's own address. Only HTTP proxies are supported, and every request goes through a CONNECT tunnel
(RFC 9110 §9.3.6), so the proxy relays bytes it doesn't read.
"""

import base64
import hashlib
import itertools
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from crawlerai.core.proxy_health import PoolHealth

__all__ = ["PoolMode", "ProxyEndpoint", "ProxyPool", "UnknownProxyPool", "pool_endpoint", "proxy_pool"]

PoolMode = Literal["rotate", "sticky"]
_POOL_KEYS = frozenset({"endpoints", "mode"})
# ISO 3166-1 alpha-2: two uppercase letters.
_COUNTRY = re.compile(r"[A-Z]{2}", re.ASCII)

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


@dataclass(frozen=True)
class ProxyPool:
    """A pool's endpoints and how a fetch picks one, with their health in this process (not compared, not shown)."""

    endpoints: tuple[ProxyEndpoint, ...]
    mode: PoolMode = "rotate"
    country: str | None = None
    health: PoolHealth = field(default_factory=PoolHealth, compare=False, repr=False)
    _turns: Iterator[int] = field(default_factory=itertools.count, compare=False, repr=False)

    @classmethod
    def __get_pydantic_core_schema__(cls, source: type, handler: GetCoreSchemaHandler) -> CoreSchema:
        """Settings validate a pool with `parse` alone: its health is process state, not a validated field."""
        return core_schema.no_info_plain_validator_function(cls.parse)

    @classmethod
    def parse(cls, value: object) -> Self:
        """A proxy URL (`ProxyEndpoint.parse`), or `{"endpoints": [url, ...], "mode": "rotate" | "sticky"}` with at
        least one endpoint and, optionally, the `country` the endpoints go out from; `mode` is required with a list, so
        a pool's behaviour is never a default (C7). Error messages never contain a URL."""
        if not isinstance(value, dict):
            return cls((ProxyEndpoint.parse(value),))
        endpoints, mode = value.get("endpoints"), value.get("mode")
        country = value.get("country")
        if set(value) - {"country"} != _POOL_KEYS or not isinstance(endpoints, list) or not endpoints:
            raise ValueError(
                'a proxy pool is a proxy URL or {"endpoints": [url, ...], "mode": "rotate" | "sticky", '
                '"country"?: "XX"}'
            )
        if "country" in value and not (isinstance(country, str) and _COUNTRY.fullmatch(country)):
            raise ValueError("a proxy pool's country is an ISO 3166-1 alpha-2 code, two uppercase letters")
        if mode != "rotate" and mode != "sticky":
            raise ValueError('a proxy pool\'s mode is "rotate" or "sticky"')
        parsed = tuple(ProxyEndpoint.parse(url) for url in endpoints)
        if len(set(parsed)) != len(parsed):
            raise ValueError("a proxy pool lists an endpoint twice")
        return cls(parsed, mode, country)

    def pick(self, key: str) -> ProxyEndpoint:
        """The endpoint a request for `key` (the requested host) goes through."""
        choices = [endpoint for endpoint in self.endpoints if self.health.available(endpoint)]
        if not choices:
            return min(self.endpoints, key=self.health.recovers_at)
        if self.mode == "sticky":
            return max(choices, key=lambda endpoint: _weight(key, endpoint))
        return choices[next(self._turns) % len(choices)]

    def report(self, endpoint: ProxyEndpoint, healthy: bool | None) -> None:
        """Record how a request through `endpoint` went; `None` says nothing about the endpoint."""
        if healthy is not None:
            self.health.report(endpoint, healthy)


def _weight(key: str, endpoint: ProxyEndpoint) -> bytes:
    """The rendezvous weight of `endpoint` for `key`: a hash of both, the same in every process. Every part of the
    endpoint goes in, its password too (a pool's endpoints differ in at least one part), so no two endpoints tie; the
    digest is never shown."""
    identity = f"{endpoint.host}:{endpoint.port}\n{endpoint.username or ''}\n{endpoint.password or ''}"
    return hashlib.sha256(f"{key}\n{identity}".encode()).digest()


class UnknownProxyPool(Exception):
    """A fetch named a pool that isn't configured. It is refused rather than fetched without the pool."""

    def __init__(self) -> None:
        super().__init__("proxy_pool_unknown")


def proxy_pool(name: str | None, pools: Mapping[str, ProxyPool] | None) -> ProxyPool | None:
    """Pool `name` among `pools` (none configured when None), or None when no pool is asked for."""
    if name is None:
        return None
    pool = (pools or {}).get(name)
    if pool is None:
        raise UnknownProxyPool
    return pool


def pool_endpoint(pool: ProxyPool | None, url: str) -> ProxyEndpoint | None:
    """The endpoint of `pool` that a request for `url` goes through, or None without a pool."""
    return None if pool is None else pool.pick(urlsplit(url).hostname or "")
