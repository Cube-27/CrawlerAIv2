"""The health of a proxy pool's endpoints, in this process (ARCHITECTURE §7.1, D-1324): an endpoint that fails
`QUARANTINE_AFTER` times in a row is left out of the pool's choices for a quarantine that doubles with each further
failure, from `QUARANTINE_MIN` to `QUARANTINE_MAX`; one success ends its run of failures.

What counts as a failure is the rung's to say (`acquire.proxy_verdict`): a block or a network failure through the
endpoint, never an outcome the endpoint has no part in (an SSRF refusal, a body cap).
"""

import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final

QUARANTINE_AFTER: Final = 3  # consecutive failures; one or two can be the site's, not the endpoint's
QUARANTINE_MIN: Final = timedelta(minutes=1)
QUARANTINE_MAX: Final = timedelta(minutes=30)


@dataclass
class EndpointHealth:
    consecutive_fail: int = 0
    quarantined_until: float = 0.0  # on the health's clock; 0 when never quarantined


@dataclass
class PoolHealth:
    """Per-endpoint health of one pool, keyed by any hashable endpoint identity."""

    clock: Callable[[], float] = time.monotonic
    _by_endpoint: dict[Hashable, EndpointHealth] = field(default_factory=dict)

    def available(self, endpoint: Hashable) -> bool:
        health = self._by_endpoint.get(endpoint)
        return health is None or health.quarantined_until <= self.clock()

    def recovers_at(self, endpoint: Hashable) -> float:
        health = self._by_endpoint.get(endpoint)
        return 0.0 if health is None else health.quarantined_until

    def report(self, endpoint: Hashable, healthy: bool) -> None:
        health = self._by_endpoint.setdefault(endpoint, EndpointHealth())
        if healthy:
            health.consecutive_fail = 0
            return
        health.consecutive_fail += 1
        if health.consecutive_fail >= QUARANTINE_AFTER:
            health.quarantined_until = self.clock() + quarantine(health.consecutive_fail).total_seconds()


def quarantine(consecutive_fail: int) -> timedelta:
    """The quarantine after `consecutive_fail` failures in a row: `QUARANTINE_MIN`, doubled for each failure past
    `QUARANTINE_AFTER`, at most `QUARANTINE_MAX`."""
    # Doublings past the cap's ratio change nothing; bounding them keeps the timedelta in range.
    doublings = min(consecutive_fail - QUARANTINE_AFTER, _MAX_DOUBLINGS)
    duration: timedelta = min(QUARANTINE_MIN * 2**doublings, QUARANTINE_MAX)
    return duration


_MAX_DOUBLINGS: Final = int(QUARANTINE_MAX / QUARANTINE_MIN).bit_length()
