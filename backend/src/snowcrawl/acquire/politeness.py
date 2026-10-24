"""Politeness per site: a request rate, adapted to how the host answers, and the pause a server asks
for.

The rate adapts per host, as TCP's congestion control does (RFC 5681 §3.1: back off multiplicatively on a
congestion signal, grow back slowly): a 429 or 503 (`SLOW_DOWN`), or a challenge (`AttemptRecord.challenge`), doubles
the host's spacing, up to `BACKOFF_MAX`; after `RECOVERY_RUN` `ok` answers in a row it shrinks by `RECOVERY_FACTOR`,
never below the site's configured interval and its robots.txt `Crawl-delay` (`interval`).

A host is also held while a request to it is in flight (owner plan 2026-10-19, P1): no other task's request goes to it
until the holder's fetch returns, browser navigations included, so a page slower than the interval is not overlapped.
Work being cancelled (a task at its deadline) neither holds a host nor is admitted: what outlives its cancellation
sends nothing more.

With a shared store (`SharedTurns`, the database's `host_turn` rows: `acquire/host_turns.py`) the turn and the hold are
shared by every process (owner plan P1, "pacing shared across processes"): a turn is taken, and the host held, in one
statement, so two processes never both take a host's turn or hold it at once. The process's own state answers first,
and refuses without a round trip what the shared state would refuse too; only a turn the process itself would admit is
asked of the store. A hold in the store is a lease (`HOLD_LEASE`) the holding process renews while its holder runs
(`RENEW_EVERY`) and gives up as the holder is cancelled, so a process that dies, or work left behind, holds a host no
longer than the lease. The adaptive spacing stays per process; the pause it and a server's back-off ask for is shared.
"""

import asyncio
import itertools
import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final, Protocol

from snowcrawl.acquire.types import AttemptRecord
from snowcrawl.core.retry import backoff_delay
from snowcrawl.storage.capture_bundle import HeaderList

DEFAULT_INTERVAL: Final = timedelta(seconds=1)  # 1 request/s
BACKOFF_MAX: Final = timedelta(minutes=15)  # the longest backoff
# RFC 6585 §4 (429 Too Many Requests) and RFC 9110 §15.6.4 (503 Service Unavailable): the statuses that ask a
# client to slow down, optionally with a Retry-After.
SLOW_DOWN: Final = frozenset({429, 503})
# The adaptive spacing's recovery, unmeasured starting points: 20 `ok` answers in a row shrink it by 10%.
RECOVERY_RUN: Final = 20
RECOVERY_FACTOR: Final = 0.9
# A hold in the shared store lapses this long after its process last renewed it: a process that dies, or work left
# behind, holds its host no longer. Renewed every quarter of it, so three renewals may run late (an event loop busy with
# a page) before a running fetch's hold lapses.
HOLD_LEASE: Final = timedelta(minutes=1)
RENEW_EVERY: Final = HOLD_LEASE / 4

log = logging.getLogger(__name__)


class SharedTurns(Protocol):
    """Host turns and holds shared by every process (`acquire/host_turns.py`)."""

    async def take(self, host: str, spacing: timedelta, holder: str | None) -> timedelta:
        """Zero when `host`'s turn is due and no other holder's lease on it runs: its next turn is then `spacing` from
        now and, with a `holder`, the host is held for it for `HOLD_LEASE`. Otherwise how long until its turn: the
        spacing while another holds it."""
        ...

    async def pause(self, host: str, after: timedelta) -> None:
        """No turn of `host` for `after`, unless a later one is already due."""
        ...

    async def release(self, host: str, holder: str) -> None:
        """End `holder`'s hold of `host`, if it still has it."""
        ...

    async def renew(self, holders: Iterable[str]) -> None:
        """Extend the holds of `holders` to `HOLD_LEASE` from now."""
        ...


class Admit(Protocol):
    """Waits until the site's rate admits one more request, records it and answers True; answers False, recording
    nothing, when that turn is too far off to wait for in place. `after` is a pause the site asked for (a 503's
    `backoff`): the site is paused for it first, and the turn comes no sooner."""

    def __call__(self, *, after: timedelta = ...) -> Awaitable[bool]: ...


async def refuse(*, after: timedelta = timedelta(0)) -> bool:
    """The `Admit` of a fetch that may send no further request: robots.txt disallows the page."""
    return False


def backoff(attempt: AttemptRecord, tries: int = 1) -> timedelta | None:
    """The one back-off of a host that answered `attempt` with a 429 or 503 on try `tries` of the work: the pause its
    `Retry-After` asks for, else the queue's backoff for that try (`backoff_delay`), at most
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
    goes to its endpoint, whose host's rate it is admitted at and adapts."""
    return tuple(attempt for attempt in attempts if attempt.method != "api")


def interval(robots_delay: timedelta | None) -> timedelta:
    """The time between two requests to a site: the default, and never shorter than the `Crawl-delay` its robots.txt
    asks for (`None` when robots are not consulted)."""
    return DEFAULT_INTERVAL if robots_delay is None else max(DEFAULT_INTERVAL, robots_delay)


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
    interval, or longer while the host's answers asked for fewer requests (`observe`). With `shared`, the turns and
    holds are every process's (module docstring)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, shared: SharedTurns | None = None) -> None:
        self._clock = clock
        self._shared = shared
        self._next: dict[str, float] = {}  # host -> when its next request may go, on `clock`
        self._adapted: dict[str, timedelta] = {}  # host -> its spacing, while longer than its interval
        self._ok_run: dict[str, int] = {}  # host -> `ok` answers since its spacing last changed
        self._held: dict[str, asyncio.Task[object]] = {}  # host -> the task whose request to it is in flight
        # (host, task) -> the token of the task's `holding` block on the host: the holder's name in the shared store.
        self._scopes: dict[tuple[str, asyncio.Task[object]], str] = {}
        self._leases: dict[str, tuple[str, asyncio.Task[object]]] = {}  # token -> its host and task, held in `shared`
        self._renewing: asyncio.Task[None] | None = None
        self._tokens = (f"{secrets.token_hex(6)}:{n}" for n in itertools.count())

    async def admit(self, host: str, interval: timedelta) -> timedelta:
        """Zero, recording a request to `host` now, when one may go; otherwise how long until one may: while another
        task's request to `host` is in flight, the spacing, after which the caller asks again. Inside the task's
        `holding` block on `host`, the request takes the host's hold. Raises `CancelledError` in a task being
        cancelled (module docstring)."""
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
        token = None if current is None else self._scopes.get((host, current))
        shared = self._shared
        if shared is not None and (wait := await self._take(shared, host, interval, token, current)) > timedelta(0):
            return wait
        self._next[host] = self._clock() + self.spacing(host, interval).total_seconds()
        if token is not None and current is not None:
            self._held[host] = current
        return timedelta(0)

    async def _take(
        self,
        shared: SharedTurns,
        host: str,
        interval: timedelta,
        token: str | None,
        current: asyncio.Task[object] | None,
    ) -> timedelta:
        """The shared store's answer (`SharedTurns.take`). The hold is counted as the task's before the statement, so
        a hold taken by a statement whose answer the task did not live to read is given up all the same (`_renew`)."""
        first = token is not None and token not in self._leases
        if token is not None and current is not None:
            self._leases[token] = (host, current)
            if self._renewing is None or self._renewing.done():
                self._renewing = asyncio.create_task(self._renew(shared))
        wait = await shared.take(host, self.spacing(host, interval), token)
        if wait > timedelta(0) and first and token is not None:
            del self._leases[token]
        return wait

    @asynccontextmanager
    async def holding(self, host: str) -> AsyncIterator[None]:
        """The current task's hold of `host` while the block runs (a fetch, its requests in flight): the request `admit`
        admits inside it holds the host, and no other task's request goes to it until the block ends or the task is
        being cancelled. A block the task is already in on `host` is kept (an adapter's request to the page's host
        within the page's fetch)."""
        current = _current()
        if current is None or (host, current) in self._scopes:
            yield
            return
        token = next(self._tokens)
        self._scopes[host, current] = token
        try:
            yield
        finally:
            del self._scopes[host, current]
            if self._held.get(host) is current:
                del self._held[host]
            await self._give_up(token)

    async def _give_up(self, token: str) -> None:
        """End `token`'s hold in the shared store; one the store did not end lapses with its lease."""
        if self._shared is None or (lease := self._leases.get(token)) is None:
            return
        # Given up here either way: a hold not released is not renewed, and lapses with its lease.
        del self._leases[token]
        try:
            await self._shared.release(lease[0], token)
        except Exception:
            log.warning("host hold: not released; it lapses with its lease", exc_info=True)

    async def _renew(self, shared: SharedTurns) -> None:
        """While this process holds hosts in the shared store: every `RENEW_EVERY`, give up the holds of tasks that
        ended or are being cancelled (they hold nothing) and renew the rest."""
        while self._leases:
            await asyncio.sleep(RENEW_EVERY.total_seconds())
            try:
                ended = [token for token, (_, task) in self._leases.items() if task.done() or task.cancelling()]
                for token in ended:
                    await self._give_up(token)
                await shared.renew(tuple(self._leases))
            except Exception:
                log.warning("host holds: not renewed", exc_info=True)

    def holds(self, host: str) -> bool:
        """Whether the current task took a turn of `host` in its `holding` block on it, and holds the host."""
        current = _current()
        return current is not None and self._held.get(host) is current

    def _busy(self, host: str, current: asyncio.Task[object] | None) -> bool:
        holder = self._held.get(host)
        return holder is not None and holder is not current and not holder.done() and not holder.cancelling()

    def spacing(self, host: str, interval: timedelta) -> timedelta:
        """The time between two requests to `host` now: its `interval`, or the adapted spacing while longer."""
        adapted = self._adapted.get(host)
        return interval if adapted is None else max(interval, adapted)

    async def observe(self, host: str, interval: timedelta, attempts: Iterable[AttemptRecord]) -> None:
        """Adapt `host`'s spacing to the answers of a fetch's `attempts` (module docstring)."""
        for attempt in attempts:
            if attempt.status in SLOW_DOWN or attempt.challenge is not None:
                await self._slowed(host, interval)
            elif attempt.block_class == "ok":
                self._answered(host, interval)

    async def _slowed(self, host: str, interval: timedelta) -> None:
        self._adapted[host] = min(self.spacing(host, interval) * 2, max(BACKOFF_MAX, interval))
        self._ok_run[host] = 0
        # The turn `admit` reserved used the old spacing; push it so the new spacing holds from this answer on.
        await self.pause(host, self.spacing(host, interval))

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
            await self.pause(host, after)
        give_up = self._clock() + bound.total_seconds()
        while wait := await self.admit(host, interval):
            if self._clock() + wait.total_seconds() > give_up:
                return False
            await asyncio.sleep(wait.total_seconds())
        return True

    async def pause(self, host: str, after: timedelta) -> None:
        """Admit nothing to `host` for `after`, unless a longer wait is already due."""
        self._next[host] = max(self._next.get(host, 0.0), self._clock() + after.total_seconds())
        if self._shared is not None:
            await self._shared.pause(host, after)
