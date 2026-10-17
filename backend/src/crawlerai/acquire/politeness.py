"""Politeness per site (SPEC-02 §4.6): a request rate, adapted to how the host answers, and the pause a server asks
for.

The rate adapts per host (D-1327), as TCP's congestion control does (RFC 5681 §3.1: back off multiplicatively on a
congestion signal, grow back slowly): a 429 or 503 (`SLOW_DOWN`), or a challenge (`AttemptRecord.challenge`), doubles
the host's spacing, up to `BACKOFF_MAX`; after `RECOVERY_RUN` `ok` answers in a row it shrinks by `RECOVERY_FACTOR`,
never below the site's configured interval and its robots.txt `Crawl-delay` (`interval`).

The limiter's state lives in the worker process. With several workers a site sees up to one request per interval
from each, which the design point (0.1 tasks/s) accepts; shared state is a candidate only if measured.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final, Protocol

from crawlerai.acquire.types import AttemptRecord
from crawlerai.storage.capture_bundle import HeaderList

DEFAULT_INTERVAL: Final = timedelta(seconds=1)  # SPEC-02 §4.6: 1 request/s
BACKOFF_MIN: Final = timedelta(seconds=30)  # SPEC-02 §4.6: the first backoff
BACKOFF_MAX: Final = timedelta(minutes=15)  # SPEC-02 §4.6: the longest backoff
# RFC 6585 §4 (429 Too Many Requests) and RFC 9110 §15.6.4 (503 Service Unavailable): the statuses that ask a
# client to slow down, optionally with a Retry-After.
SLOW_DOWN: Final = frozenset({429, 503})
# D-1327: the adaptive spacing's recovery, unmeasured starting points: 20 `ok` answers in a row shrink it by 10%.
RECOVERY_RUN: Final = 20
RECOVERY_FACTOR: Final = 0.9


class Admit(Protocol):
    """Waits until the site's rate admits one more request, records it and answers True; answers False, recording
    nothing, when that turn is too far off to wait for in place. `after` is a pause the site asked for (D-1263: a 503's
    `Retry-After`, else the first backoff): the site is paused for it first, and the turn comes no sooner."""

    def __call__(self, *, after: timedelta = ...) -> Awaitable[bool]: ...


async def refuse(*, after: timedelta = timedelta(0)) -> bool:
    """The `Admit` of a fetch that may send no further request: robots.txt disallows the page (SPEC-15 §4.6)."""
    return False


def asked_pause(attempt: AttemptRecord) -> timedelta:
    """The pause a 429 or 503 `attempt` asks for (SPEC-02 §4.6): its `Retry-After`, else the first backoff."""
    return BACKOFF_MIN if attempt.retry_after is None else attempt.retry_after


def slowed_down(attempts: Iterable[AttemptRecord]) -> AttemptRecord | None:
    """The last attempt a server answered with a 429 or 503 (`SLOW_DOWN`), if any."""
    return next((a for a in reversed(tuple(attempts)) if a.status in SLOW_DOWN), None)


def interval(crawl_delay_ms: int | None, robots_delay: timedelta | None) -> timedelta:
    """The time between two requests to a site: the site's own setting, else the default, and never shorter than the
    `Crawl-delay` its robots.txt asks for (`None` when robots are not consulted)."""
    configured = DEFAULT_INTERVAL if crawl_delay_ms is None else timedelta(milliseconds=crawl_delay_ms)
    return configured if robots_delay is None else max(configured, robots_delay)


def retry_after(headers: HeaderList, now: datetime) -> timedelta | None:
    """The pause a `Retry-After` header asks for (RFC 9110 §10.2.3: delay-seconds or an HTTP-date); `None` when it
    is absent or unreadable. A date in the past asks for none."""
    values = [value.strip() for name, value in headers if name.lower() == "retry-after"]
    if not values:
        return None
    value = values[-1]
    if value.isascii() and value.isdigit():
        try:
            return timedelta(seconds=int(value))
        except (OverflowError, ValueError):
            # More seconds than a timedelta holds, or digits than int() parses: as long a pause as can be expressed.
            return timedelta.max
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    # RFC 9110 §5.6.7: an HTTP-date is in GMT; the parser leaves one without a zone (`-0000`) naive.
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return max(when - now, timedelta(0))


class HostLimiter:
    """Admission per host: one request per spacing (a token bucket that holds one token), and none while a pause
    a server asked for runs. The spacing is the site's interval, or longer while the host's answers asked for fewer
    requests (`observe`)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._next: dict[str, float] = {}  # host -> when its next request may go, on `clock`
        self._adapted: dict[str, timedelta] = {}  # host -> its spacing, while longer than its interval
        self._ok_run: dict[str, int] = {}  # host -> `ok` answers since its spacing last changed

    def admit(self, host: str, interval: timedelta) -> timedelta:
        """Zero, recording a request to `host` now, when one may go; otherwise how long until one may."""
        now = self._clock()
        # In timedelta's microseconds, so that a wait too short to express admits the request rather than return 0.
        wait = timedelta(seconds=self._next.get(host, now) - now)
        if wait > timedelta(0):
            return wait
        self._next[host] = now + self.spacing(host, interval).total_seconds()
        return timedelta(0)

    def spacing(self, host: str, interval: timedelta) -> timedelta:
        """The time between two requests to `host` now: its `interval`, or the adapted spacing while longer."""
        adapted = self._adapted.get(host)
        return interval if adapted is None else max(interval, adapted)

    def observe(self, host: str, interval: timedelta, attempts: Iterable[AttemptRecord]) -> None:
        """Adapt `host`'s spacing to the answers of a fetch's `attempts` (module docstring)."""
        for attempt in attempts:
            if attempt.status in SLOW_DOWN or attempt.challenge is not None:
                self._slowed(host, interval)
            elif attempt.block_class == "ok":
                self._answered(host, interval)

    def _slowed(self, host: str, interval: timedelta) -> None:
        self._adapted[host] = min(self.spacing(host, interval) * 2, max(BACKOFF_MAX, interval))
        self._ok_run[host] = 0

    def _answered(self, host: str, interval: timedelta) -> None:
        adapted = self._adapted.get(host)
        if adapted is None:
            return
        run = self._ok_run.get(host, 0) + 1
        self._ok_run[host] = run % RECOVERY_RUN
        if run < RECOVERY_RUN:
            return
        if (shrunk := adapted * RECOVERY_FACTOR) > interval:
            self._adapted[host] = shrunk
        else:
            del self._adapted[host]

    async def wait(
        self, host: str, interval: timedelta, bound: timedelta = timedelta.max, *, after: timedelta = timedelta(0)
    ) -> bool:
        """Wait in place until a request to `host` may go, record it and answer True; answer False at once, recording
        nothing, when it may go only more than `bound` from now. `after` pauses the host first (`pause`): a pause
        longer than `bound` is not waited for, and is left to the caller's backoff."""
        if after > bound:
            return False
        if after:
            self.pause(host, after)
        while wait := self.admit(host, interval):
            if wait > bound:
                return False
            await asyncio.sleep(wait.total_seconds())
        return True

    def pause(self, host: str, after: timedelta) -> None:
        """Admit nothing to `host` for `after`, unless a longer wait is already due."""
        self._next[host] = max(self._next.get(host, 0.0), self._clock() + after.total_seconds())
