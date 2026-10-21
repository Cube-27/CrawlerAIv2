"""One polite fetch (acquisition spec): the way every caller sends a request to a site, whether its caller waits for the
answer (`scrape`, `map`, `extract`) or it runs in a worker (`batch_scrape`, `crawl`), for a page, an
API endpoint an adapter or recipe asks, or a sitemap.

The steps, in order: the host's rules (its interval setting and robots.txt, `ReadRules`; a robots.txt request takes a
turn at the host's rate and holds the host as a page's does), a turn at the host's rate, the fetch, then the host's rate
adapted to every answer of the fetch (acquisition spec, Per-site rate and backoff) and, when the fetch kept no `ok`
answer after a 429 or 503, the host paused by the one back-off rule (`politeness.backoff`), the host held from the
first turn until then (no other task's request goes to it meanwhile). A caller that waits for
the answer waits in place for its turns, up to `IN_PLACE.bound`, and a turn further off is not taken (`Refused`,
`slow_down`). A worker postpones its task when the host's turn for the first request is not due (`Later`): the task
goes back to the queue, and the worker moves on to other sites; a further request of the fetch, the browser retry,
waits in place up to `QUEUED.bound`, since the first request is spent and postponing would send it again.
"""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Final, NamedTuple
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import (
    BACKOFF_MAX,
    Admit,
    HostLimiter,
    backoff,
    interval,
    page_requests,
    refuse,
    slowed_down,
)
from crawlerai.acquire.robots import Fetch, Robots, site_robots
from crawlerai.acquire.rungs import Rung
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.db.queue import TASK_DEADLINE
from crawlerai.services.scrape_steps import site_row

__all__ = [
    "IN_PLACE",
    "QUEUED",
    "HostRules",
    "Later",
    "NoTurn",
    "PageFetch",
    "ReadRules",
    "Refused",
    "Waiting",
    "listed_sitemaps",
    "page_first",
    "polite_fetch",
    "recording",
    "rules_of",
]

# Why a polite fetch sent nothing: robots.txt disallows the URL or could not be read (RFC 9309 §2.3.1.4: then nothing
# is allowed), or the host's turn is further off than the caller waits in place.
ROBOTS: Final = "robots"
ROBOTS_UNREACHABLE: Final = "robots_unreachable"
SLOW_DOWN: Final = "slow_down"


@dataclass(frozen=True)
class HostRules:
    """The rules a request to a host goes by: its robots.txt (None when the policy does not respect it)."""

    robots: Robots | None = None

    @property
    def gap(self) -> timedelta:
        return interval(None if self.robots is None else self.robots.crawl_delay)

    def allows(self, url: str) -> bool:
        return self.robots is None or self.robots.allows(url)


# The rules of the host of a URL, for a fetch with a policy; None when the policy respects robots.txt and it could not
# be read.
ReadRules = Callable[[str, FetchPolicy], Awaitable[HostRules | None]]


@dataclass(frozen=True)
class Waiting:
    """How a caller waits for a host's turn: `postpone` the first request's (a worker's task goes back to the queue) or
    wait for it in place, and wait in place for every other turn up to `bound`."""

    postpone: bool
    bound: timedelta


# D-1263: a caller waiting for the answer waits in place up to a minute for a turn.
IN_PLACE: Final = Waiting(postpone=False, bound=timedelta(minutes=1))
# A third of the task's deadline leaves the rest for the requests themselves (each within its policy's timeout) and the
# rest of the task; a longer wait would spend the deadline on turns and record the page as failed.
QUEUED: Final = Waiting(postpone=True, bound=TASK_DEADLINE / 3)


class Refused(NamedTuple):
    """Nothing was sent: `ROBOTS`, `ROBOTS_UNREACHABLE` or `SLOW_DOWN`."""

    reason: str


class Later(NamedTuple):
    """The first request's turn is `wait` away: the task is postponed (`QUEUED`)."""

    wait: timedelta


class NoTurn(Exception):
    """A rules reader sent no robots.txt request: its turn is further off than the caller waits (`unsent`)."""

    def __init__(self, unsent: "Later | Refused") -> None:
        super().__init__(unsent)
        self.unsent = unsent


# A page fetch through the polite step: given the URL, the `Admit` each request after its first waits for, and the
# host's rules (D-1384: what it asks of the same host goes by them), the page.
PageFetch = Callable[[str, Admit, HostRules], Awaitable[FetchResult]]


async def polite_fetch(
    url: str,
    policy: FetchPolicy,
    rules: ReadRules,
    limiter: HostLimiter,
    waiting: Waiting,
    fetch: PageFetch,
    *,
    by_adapter: bool = False,
    turn_taken: bool = False,
    endpoint: bool = False,
    tries: int = 1,
) -> FetchResult | Refused | Later:
    """`url` fetched with `fetch` politely (module docstring), or why nothing was sent. `by_adapter`: an active adapter
    serves the URL first (adapters spec) from an API whose own robots.txt its requests go by, so a robots.txt disallow
    of the page admits no fallback to the page rungs, and a fetch that does not keep `ok` is `ROBOTS`. `turn_taken`:
    the caller already holds the host's turn for this request. `endpoint`: every request of the fetch goes to the URL's
    host (an API request); a page fetch's `api` attempts went to other hosts, which their own polite fetch observed.
    `tries` counts this fetch among the work's tries, which the back-off doubles with."""
    host = urlsplit(url).hostname or ""
    # The host is held from the first turn the block takes (robots.txt's, or the fetch's) until the fetch's answers
    # are observed (`HostLimiter.holding`).
    async with limiter.holding(host):
        try:
            known = await rules(url, policy)
        except NoTurn as no_turn:
            return no_turn.unsent
        if known is None:
            return Refused(ROBOTS_UNREACHABLE)
        disallowed = not known.allows(url)
        if disallowed and not by_adapter:
            return Refused(ROBOTS)
        sent = limiter.holds(host)  # robots.txt was requested: the fetch's first request is spent
        if not turn_taken and (unsent := await _first_turn(limiter, host, known.gap, waiting, sent=sent)) is not None:
            return unsent
        admit_next: Admit = refuse if disallowed else partial(limiter.wait, host, known.gap, waiting.bound)
        result = await fetch(url, admit_next, known)
        # Observed, and the host paused, before the hold ends: no other process's turn comes before the back-off.
        attempts = result.attempts if endpoint else page_requests(result.attempts)
        await limiter.observe(host, known.gap, attempts)
        if result.block_class == "ok":
            return result
        await pause_host(limiter, host, attempts, tries)
    return Refused(ROBOTS) if disallowed else result


async def _first_turn(
    limiter: HostLimiter, host: str, gap: timedelta, waiting: Waiting, *, sent: bool = False
) -> Later | Refused | None:
    """The fetch's turn, or why it sends nothing. A worker postpones a fetch that has sent nothing; once a request
    went (`sent`: robots.txt's), it waits in place up to its bound, as for a further request, and postpones past it."""
    if waiting.postpone and not sent:
        wait = await limiter.admit(host, gap)
        return Later(wait) if wait else None
    if await limiter.wait(host, gap, waiting.bound):
        return None
    return Later(waiting.bound) if waiting.postpone else Refused(SLOW_DOWN)


async def pause_host(limiter: HostLimiter, host: str, attempts: Iterable[AttemptRecord], tries: int) -> None:
    """After a 429 or 503 to a request of a fetch that kept no `ok` answer, admit nothing more to `host` until the
    back-off is over (`politeness.backoff`; the longest backoff when the server asked for longer)."""
    slowed = slowed_down(attempts)
    if slowed is None:
        return
    pause = backoff(slowed, tries)
    await limiter.pause(host, BACKOFF_MAX if pause is None else pause)


@dataclass(frozen=True)
class Turns:
    """How a rules reader's robots.txt request gets its turn: at `limiter`'s rate, waiting for it as `waiting` says."""

    limiter: HostLimiter
    waiting: Waiting


def rules_of(engine: AsyncEngine, http: Rung, attempts: list[AttemptRecord], turns: Turns) -> ReadRules:
    """`ReadRules` for a caller that holds no transaction while it fetches: the host's site, created on first use as a
    page's is, in a short transaction of its own (a new host's row is committed at once, so no other fetch of the host
    waits on it), and its robots.txt, fetched over `http` when the site's snapshot is stale (`site_robots`), at the
    host's rate (`turns`; `NoTurn` when its turn is further off than the caller waits), with the attempts of that fetch
    added to `attempts`."""

    async def read(url: str, policy: FetchPolicy) -> HostRules | None:
        async with engine.begin() as conn:
            site = await site_row(conn, urlsplit(url).hostname or "")
        if not policy.respect_robots:
            return HostRules()
        fetch = recording(http, policy, attempts, turns, HostRules().gap)
        robots = await site_robots(engine, site.id, site.robots_snapshot, url, fetch)
        return None if robots is None else HostRules(robots)

    return read


async def listed_sitemaps(rules: ReadRules, url: str, policy: FetchPolicy, known: HostRules) -> tuple[str, ...]:
    """The sitemaps the robots.txt of `url`'s origin lists (`Sitemap:`), for a reading of the site's sitemaps: those of
    `known`, the rules read with `policy`; read through `rules` for their `Sitemap:` lines alone when `policy` does not
    obey robots.txt (owner decision #75). None when it is unreachable or its turn is further off than the caller
    waits."""
    if known.robots is None and not policy.respect_robots:
        try:
            known = await rules(url, policy.model_copy(update={"respect_robots": True})) or known
        except NoTurn:
            return ()
    return () if known.robots is None else known.robots.sitemaps


def page_first(page_host: str, known: HostRules, rules: ReadRules) -> ReadRules:
    """`rules`, except for a URL on `page_host`, whose rules the caller read before fetching its page (`known`) and
    which are not read again (D-1384)."""

    async def first(url: str, policy: FetchPolicy) -> HostRules | None:
        return known if (urlsplit(url).hostname or "") == page_host else await rules(url, policy)

    return first


def recording(rung: Rung, policy: FetchPolicy, attempts: list[AttemptRecord], turns: Turns, gap: timedelta) -> Fetch:
    """A fetch of robots.txt through `rung` with `policy` that adds the attempts of each fetch to `attempts`, sent as
    politely as a page's request (acquisition spec): a turn at its host's rate (`gap`, the site's interval: its
    `Crawl-delay` is what it reads) taken as `turns` waits, or `NoTurn`; the host held until its answers are
    observed, and a slow-down has paused the host. The caller's request context and page steps are the page's, not
    robots.txt's (D-1432): it goes without them."""
    policy = policy.model_copy(update={"context": None, "steps": ()})
    limiter = turns.limiter

    async def fetch(url: str) -> FetchResult:
        host = urlsplit(url).hostname or ""
        async with limiter.holding(host):
            if (unsent := await _first_turn(limiter, host, gap, turns.waiting)) is not None:
                raise NoTurn(unsent)
            result = await rung(url, policy)
            await limiter.observe(host, gap, result.attempts)
            if result.block_class != "ok":
                await pause_host(limiter, host, result.attempts, 1)
        attempts.extend(result.attempts)
        return result

    return fetch
