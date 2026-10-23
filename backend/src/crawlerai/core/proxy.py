"""Proxy pools (acquisition spec, OPEN_QUESTIONS #10): datacenter or ISP proxies configured by hand in
`CRAWLERAI_PROXY_POOLS`, and used for a fetch whose `proxy_pool` names its pool. A pool is one proxy URL, or
`{"endpoints": [url, ...], "mode": "rotate" | "sticky"}` (D-1323): `rotate` takes its endpoints in turn, `sticky` keeps
each site on one endpoint (rendezvous hashing, Thaler and Ravishankar 1998: a site moves only when its endpoint leaves
the choice). A pool may declare where its endpoints go out from (`ExitPlace`: one pool, one place): the `country`
records state as their egress (`core/egress.py`), the `timezone` and `locale` the browser rung's context takes
(`acquire.locality`). An endpoint in quarantine (`proxy_health`) is chosen only when every endpoint of the pool is, and
then the one that recovers first: a pool never sends a site's request direct.

Sticky exits: an endpoint whose username or password holds `{session}` is a provider's gateway that keeps one exit
address per session id it is given there (the `sticky` mode keeps a site on one endpoint; this keeps it on one address
behind it). A site's first fetch through the gateway mints an id (`SiteExits`), and the site's fetches, HTTP and browser
alike, go out through that exit until it has served `SESSION_FETCHES` fetches, lived `SESSION_TTL`, or a fetch through
it failed (a block, no answer: `report`); the next fetch mints another. The exit is part of the endpoint, so the site's
cookie session and browser profile, which are keyed by it, end with it.

Being configured is the allowlist §7.1 asks of proxy endpoints: the SSRF guard checks the pages' hosts, not the
proxy's own address. Only HTTP proxies are supported, and every request goes through a CONNECT tunnel
(RFC 9110 §9.3.6), so the proxy relays bytes it doesn't read.
"""

import base64
import hashlib
import itertools
import re
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Final, Literal, Self
from urllib.parse import unquote, urlsplit

from pydantic import GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema

from crawlerai.core.proxy_health import PoolHealth

__all__ = [
    "SESSION_FETCHES",
    "SESSION_TTL",
    "UNDECLARED",
    "ExitPlace",
    "PoolMode",
    "ProxyEndpoint",
    "ProxyPool",
    "UnknownProxyPool",
    "pool_endpoint",
    "proxy_pool",
]

# A site's session, its cookies (`acquire.session`) and its sticky exit alike, lasts at most this long and this many
# fetches.
SESSION_TTL: Final = timedelta(minutes=30)
SESSION_FETCHES: Final = 200

PoolMode = Literal["rotate", "sticky"]
_POOL_KEYS = frozenset({"endpoints", "mode"})
_PLACE_KEYS = frozenset({"country", "timezone", "locale"})
# The placeholder of a provider's session id in an endpoint's credentials.
_SESSION = "{session}"
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
    # The `{session}` endpoint this sticky exit fills in (`ProxyPool.pick`); None for a configured endpoint.
    gateway: "ProxyEndpoint | None" = field(default=None, compare=False, repr=False)

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

    @property
    def sessioned(self) -> bool:
        """Whether its credentials take a provider session id (`{session}`)."""
        return _SESSION in f"{self.username or ''}\n{self.password or ''}"

    @property
    def configured(self) -> "ProxyEndpoint":
        """The configured endpoint: itself, or the gateway of a sticky exit, whose health it shares."""
        return self.gateway or self

    def exit(self, session: str) -> "ProxyEndpoint":
        """The exit of this gateway for provider session id `session`."""

        def filled(value: str | None) -> str | None:
            return None if value is None else value.replace(_SESSION, session)

        return replace(self, username=filled(self.username), password=filled(self.password), gateway=self)


@dataclass(frozen=True, slots=True)
class ExitPlace:
    """Where an exit's addresses are, as the operator declares them: an ISO 3166-1 alpha-2 country, an IANA time zone
    and a BCP 47 locale; None: undeclared. A pool declares its own (`ProxyPool`), the machine its direct one
    (`CRAWLERAI_EGRESS_*`)."""

    country: str | None = None
    timezone: str | None = None
    locale: str | None = None

    @classmethod
    def parse(cls, value: Mapping[str, object]) -> Self:
        """The place a pool's `country`, `timezone` and `locale` declare; what they name is checked at startup
        (`acquire.locality.check_places`)."""
        declared: dict[str, str] = {}
        for key in _PLACE_KEYS & value.keys():
            text = value[key]
            if not isinstance(text, str) or not text:
                raise ValueError("a proxy pool's country, timezone and locale are strings")
            declared[key] = text
        if "country" in declared and not _COUNTRY.fullmatch(declared["country"]):
            raise ValueError("a proxy pool's country is an ISO 3166-1 alpha-2 code, two uppercase letters")
        return cls(**declared)


UNDECLARED: Final = ExitPlace()


@dataclass
class SiteExit:
    """The sticky exit a site's fetches go out through, while it lives."""

    endpoint: ProxyEndpoint
    expires_at: float  # on the pool's clock
    fetches_left: int


@dataclass
class SiteExits:
    """A pool's sticky exits in this process, by site."""

    clock: Callable[[], float] = time.monotonic
    _by_site: dict[str, SiteExit] = field(default_factory=dict)

    def held(self, site: str) -> SiteExit | None:
        """The site's exit while it lives; a spent or expired one is dropped."""
        held = self._by_site.get(site)
        if held is not None and (held.fetches_left <= 0 or self.clock() >= held.expires_at):
            del self._by_site[site]
            return None
        return held

    def mint(self, site: str, gateway: ProxyEndpoint) -> SiteExit:
        held = SiteExit(gateway.exit(secrets.token_hex(8)), self.clock() + SESSION_TTL.total_seconds(), SESSION_FETCHES)
        self._by_site[site] = held
        return held

    def drop(self, endpoint: ProxyEndpoint) -> None:
        for site, held in tuple(self._by_site.items()):
            if held.endpoint == endpoint:
                del self._by_site[site]


@dataclass(frozen=True)
class ProxyPool:
    """A pool's endpoints and how a fetch picks one, with their health in this process (not compared, not shown)."""

    endpoints: tuple[ProxyEndpoint, ...]
    mode: PoolMode = "rotate"
    place: ExitPlace = UNDECLARED
    health: PoolHealth = field(default_factory=PoolHealth, compare=False, repr=False)
    exits: SiteExits = field(default_factory=SiteExits, compare=False, repr=False)
    _turns: Iterator[int] = field(default_factory=itertools.count, compare=False, repr=False)

    @classmethod
    def __get_pydantic_core_schema__(cls, source: type, handler: GetCoreSchemaHandler) -> CoreSchema:
        """Settings validate a pool with `parse` alone: its health is process state, not a validated field."""
        return core_schema.no_info_plain_validator_function(cls.parse)

    @classmethod
    def parse(cls, value: object) -> Self:
        """A proxy URL (`ProxyEndpoint.parse`), or `{"endpoints": [url, ...], "mode": "rotate" | "sticky"}` with at
        least one endpoint and, optionally, the `country`, `timezone` and `locale` the endpoints go out from
        (`ExitPlace`); `mode` is required with a list, so a pool's behaviour is never a default (C7). Error messages
        never contain a URL."""
        if not isinstance(value, dict):
            return cls((ProxyEndpoint.parse(value),))
        endpoints, mode = value.get("endpoints"), value.get("mode")
        if set(value) - _PLACE_KEYS != _POOL_KEYS or not isinstance(endpoints, list) or not endpoints:
            raise ValueError(
                'a proxy pool is a proxy URL or {"endpoints": [url, ...], "mode": "rotate" | "sticky", '
                '"country"?: "XX", "timezone"?: "Area/City", "locale"?: "ll-CC"}'
            )
        place = ExitPlace.parse(value)
        if mode != "rotate" and mode != "sticky":
            raise ValueError('a proxy pool\'s mode is "rotate" or "sticky"')
        parsed = tuple(ProxyEndpoint.parse(url) for url in endpoints)
        if len(set(parsed)) != len(parsed):
            raise ValueError("a proxy pool lists an endpoint twice")
        return cls(parsed, mode, place)

    def pick(self, site: str) -> ProxyEndpoint:
        """The endpoint a request to `site` (a registrable domain) goes through: its sticky exit while it lives and its
        gateway is available, else a configured endpoint, a gateway's new exit for the site."""
        held = self.exits.held(site)
        if held is None or not self.health.available(held.endpoint.configured):
            endpoint = self._configured(site)
            if not endpoint.sessioned:
                return endpoint
            held = self.exits.mint(site, endpoint)
        held.fetches_left -= 1
        return held.endpoint

    def carries(self, site: str, endpoint: ProxyEndpoint) -> bool:
        """Whether a request to `site` may still go through `endpoint`, as a site session's fetch does without `pick`:
        it is available, and a sticky exit is still the site's, one of its fetches spent."""
        if not self.health.available(endpoint.configured):
            return False
        if endpoint.gateway is None:
            return True
        held = self.exits.held(site)
        if held is None or held.endpoint != endpoint:
            return False
        held.fetches_left -= 1
        return True

    def _configured(self, site: str) -> ProxyEndpoint:
        choices = [endpoint for endpoint in self.endpoints if self.health.available(endpoint)]
        if not choices:
            return min(self.endpoints, key=self.health.recovers_at)
        if self.mode == "sticky":
            return max(choices, key=lambda endpoint: _weight(site, endpoint))
        return choices[next(self._turns) % len(choices)]

    def report(self, endpoint: ProxyEndpoint, healthy: bool | None) -> None:
        """Record how a request through `endpoint` went; `None` says nothing about the endpoint. A sticky exit's
        health is its gateway's, and a failure through it ends it: the site's next fetch takes a new exit."""
        if healthy is not None:
            self.health.report(endpoint.configured, healthy)
        if healthy is False and endpoint.gateway is not None:
            self.exits.drop(endpoint)


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


def pool_endpoint(pool: ProxyPool | None, site: str) -> ProxyEndpoint | None:
    """The endpoint of `pool` that a request to `site` (a registrable domain) goes through, or None without a pool."""
    return None if pool is None else pool.pick(site)
