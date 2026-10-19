"""Politeness per site (acquisition spec): a request rate, adapted to how the host answers, and the pause a server asks
for.

The rate adapts per host (D-1327), as TCP's congestion control does (RFC 5681 §3.1: back off multiplicatively on a
congestion signal, grow back slowly): a 429 or 503 (`SLOW_DOWN`), or a challenge (`AttemptRecord.challenge`), doubles
the host's spacing, up to `BACKOFF_MAX`; after `RECOVERY_RUN` `ok` answers in a row it shrinks by `RECOVERY_FACTOR`,
never below the site's configured interval and its robots.txt `Crawl-delay` (`interval`).

A host is also held while a request to it is in flight (owner plan 2026-10-19, P1): no other task's request goes to it
until the holder's fetch returns, browser navigations included, so a page slower than the interval is not overlapped.
Work being cancelled (a task at its deadline) neither holds a host nor is admitted: what outlives its cancellation
sends nothing more.

The limiter's state lives in the worker process. With several workers a site sees up to one request per interval,
and one in flight, from each, which the design point (0.1 tasks/s) accepts; shared state is a candidate only if
measured.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final, Protocol

from crawlerai.acquire.types import AttemptRecord
from crawlerai.core.retry import backoff_delay
from crawlerai.storage.capture_bundle import HeaderList

DEFAULT_INTERVAL: Final = timedelta(seconds=1)  # acquisition spec: 1 request/s
BACKOFF_MAX: Final = timedelta(minutes=15)  # acquisition spec: the longest backoff
# RFC 6585 §4 (429 Too Many Requests) and RFC 9110 §15.6.4 (503 Service Unavailable): the statuses that ask a
# client to slow down, optionally with a Retry-After.
SLOW_DOWN: Final = frozenset({429, 503})
# D-1327: the adaptive spacing's recovery, unmeasured starting points: 20 `ok` answers in a row shrink it by 10%.
RECOVERY_RUN: Final = 20
RECOVERY_FACTOR: Final = 0.9


class Admit(Protocol):
    """Waits until the site's rate admits one more request, records it and answers True; answers False, recording
    nothing, when that turn is too far off to wait for in place. `after` is a pause the site asked for (D-1263: a 503's
    `backoff`): the site is paused for it first, and the turn comes no sooner."""

    def __call__(self, *, after: timedelta = ...) -> Awaitable[bool]: ...


async def refuse(*, after: timedelta = timedelta(0)) -> bool:
    """The `Admit` of a fetch that may send no further request: robots.txt disallows the page (adapters spec)."""
    return False


def backoff(attempt: AttemptRecord, tries: int = 1) -> timedelta | None:
    """The one back-off of a host that answered `attempt` with a 429 or 503 on try `tries` of the work (acquisition spec
    §4.6): the pause its `Retry-After` asks for, else the queue's backoff for that try (`backoff_delay`), at most
    `BACKOFF_MAX`. None when the server asks for more than `BACKOFF_MAX`: retrying before it allows breaks its
    request, and waiting longer holds the work open without bound, so the work ends instead."""
    if attempt.retry_after is not None:
        return None if attempt.retry_after > BACKOFF_MAX else attempt.retry_after
    return min(backoff_delay(tries), BACKOFF_MAX)


def slowed_down(attempts: Iterable[AttemptRecord]) -> AttemptRecord | None:
    """The last attempt a server answered with a 429 or 503 (`SLOW_DOWN`), if any."""
    return next((a for a in reversed(tuple(attempts)) if a.status in SLOW_DOWN), None)


def page_requests(attempts: Iterable[AttemptRecord]) -> tuple[AttemptRecord, ...]:
    """The attempts of a page fetch that went to the page's host: an adapter's or recipe's API request (method `api`)
    goes to its endpoint, whose host's rate it is admitted at and adapts (D-1327)."""
    return tuple(attempt for attempt in attempts if attempt.method != "api")


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


def _current() -> asyncio.Task[object] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:  # no event loop runs: a synchronous caller
        return None


class HostLimiter:
    """Admission per host: one request per spacing (a token bucket that holds one token), none while another task's
    request to it is in flight (`holding`), and none while a pause a server asked for runs. The spacing is the site's
    interval, or longer while the host's answers asked for fewer requests (`observe`)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._next: dict[str, float] = {}  # host -> when its next request may go, on `clock`
        self._adapted: dict[str, timedelta] = {}  # host -> its spacing, while longer than its interval
        self._ok_run: dict[str, int] = {}  # host -> `ok` answers since its spacing last changed
        self._held: dict[str, asyncio.Task[object]] = {}  # host -> the task whose request to it is in flight

    def admit(self, host: str, interval: timedelta) -> timedelta:
        """Zero, recording a request to `host` now, when one may go; otherwise how long until one may: while another
        task's request to `host` is in flight, the spacing, after which the caller asks again. Raises `CancelledError`
        in a task being cancelled (module docstring)."""
        current = _current()
        if current is not None and current.cancelling():
            raise asyncio.CancelledError
        now = self._clock()
        # In timedelta's microseconds, so that a wait too short to express admits the request rather than return 0.
        wait = timedelta(seconds=self._next.get(host, now) - now)
        if wait <= timedelta(0) and self._busy(host, current):
            wait = self.spacing(host, interval)
        if wait > timedelta(0):
            return wait
        self._next[host] = now + self.spacing(host, interval).total_seconds()
        return timedelta(0)

    @contextmanager
    def holding(self, host: str) -> Iterator[None]:
        """Hold `host` for the current task while the block runs (a fetch, its requests in flight): `admit` lets no
        other task's request go to it until the block ends or the task is being cancelled. A hold the task has already
        is kept (an adapter's request to the page's host within the page's fetch)."""
        current = _current()
        if current is None or self._held.get(host) is current:
            yield
            return
        self._held[host] = current
        try:
            yield
        finally:
            if self._held.get(host) is current:
                del self._held[host]

    def _busy(self, host: str, current: asyncio.Task[object] | None) -> bool:
        holder = self._held.get(host)
        return holder is not None and holder is not current and not holder.done() and not holder.cancelling()

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
        # The turn `admit` reserved used the old spacing; push it so the new spacing holds from this answer on.
        self.pause(host, self.spacing(host, interval))

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
        """Wait in place until a request to `host` may go, record it and answer True; answer False, recording nothing,
        once it may go only more than `bound` after the wait began. `after` pauses the host first (`pause`): a pause
        longer than `bound` is not waited for, and is left to the caller's backoff."""
        if after > bound:
            return False
        if after:
            self.pause(host, after)
        give_up = self._clock() + bound.total_seconds()
        while wait := self.admit(host, interval):
            if self._clock() + wait.total_seconds() > give_up:
                return False
            await asyncio.sleep(wait.total_seconds())
        return True

    def pause(self, host: str, after: timedelta) -> None:
        """Admit nothing to `host` for `after`, unless a longer wait is already due."""
        self._next[host] = max(self._next.get(host, 0.0), self._clock() + after.total_seconds())
