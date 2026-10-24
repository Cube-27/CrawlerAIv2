"""The country a request goes out from: what a record states about where its page
was fetched, because a site may price by the visitor's country.

A fetch through a proxy pool goes out from the pool's country (`SNOWCRAWL_PROXY_POOLS`, `country`); a direct fetch from
the machine's, which the operator declares (`SNOWCRAWL_EGRESS_COUNTRY`). Nothing looks an address up: a country nobody
declared is unknown, and `basis` says how a known one is known.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from snowcrawl.core.proxy import ProxyPool

__all__ = ["UNKNOWN", "Egress", "EgressBasis", "Egresses"]

# `pool`: the pool the fetch went through declares its country; `machine`: a direct fetch from the machine whose country
# the operator declares; `unknown`: neither (a pool without a declared country is unknown, never the machine's).
EgressBasis = Literal["pool", "machine", "unknown"]


@dataclass(frozen=True, slots=True)
class Egress:
    """An ISO 3166-1 alpha-2 country (`None`: unknown) and how it is known."""

    country: str | None
    basis: EgressBasis


UNKNOWN = Egress(None, "unknown")


@dataclass(frozen=True, slots=True)
class Egresses:
    """The places a process fetches from: its configured proxy pools and its own country."""

    pools: Mapping[str, ProxyPool] = field(default_factory=dict)
    machine_country: str | None = None

    def of(self, pool: str | None) -> Egress:
        """The egress of a fetch through proxy pool `pool` (`None`: direct)."""
        if pool is None:
            return UNKNOWN if self.machine_country is None else Egress(self.machine_country, "machine")
        configured = self.pools.get(pool)
        return (
            UNKNOWN
            if configured is None or configured.place.country is None
            else Egress(configured.place.country, "pool")
        )
