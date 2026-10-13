"""Politeness per site (SPEC-02 §4.6): a request rate, and the pause a server asks for.

The limiter's state lives in the worker process. With several workers a site sees up to one request per interval
from each, which the design point (0.1 tasks/s) accepts; shared state is a candidate only if measured.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final

from crawlerai.storage.capture_bundle import HeaderList

DEFAULT_INTERVAL: Final = timedelta(seconds=1)  # SPEC-02 §4.6: 1 request/s
BACKOFF_MAX: Final = timedelta(minutes=15)  # SPEC-02 §4.6: the longest backoff
# RFC 6585 §4 (429 Too Many Requests) and RFC 9110 §15.6.4 (503 Service Unavailable): the statuses that ask a
# client to slow down, optionally with a Retry-After.
SLOW_DOWN: Final = frozenset({429, 503})


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
        return timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    # RFC 9110 §5.6.7: an HTTP-date is in GMT; the parser leaves one without a zone (`-0000`) naive.
    when = when if when.tzinfo else when.replace(tzinfo=UTC)
    return max(when - now, timedelta(0))


class HostLimiter:
    """Admission per host: one request per interval (a token bucket that holds one token), and none while a pause
    a server asked for runs."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._next: dict[str, float] = {}  # host -> when its next request may go, on `clock`

    def admit(self, host: str, interval: timedelta) -> timedelta:
        """Zero, recording a request to `host` now, when one may go; otherwise how long until one may."""
        now = self._clock()
        # In timedelta's microseconds, so that a wait too short to express admits the request rather than return 0.
        wait = timedelta(seconds=self._next.get(host, now) - now)
        if wait > timedelta(0):
            return wait
        self._next[host] = now + interval.total_seconds()
        return timedelta(0)

    def pause(self, host: str, after: timedelta) -> None:
        """Admit nothing to `host` for `after`, unless a longer wait is already due."""
        self._next[host] = max(self._next.get(host, 0.0), self._clock() + after.total_seconds())
