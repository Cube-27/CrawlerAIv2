"""One polite fetch (SPEC-02 §4.6): the way every caller sends a request to a site, whether its caller waits for the
answer (`scrape`, `map`, `extract`, the eval import) or it runs in a worker (`batch_scrape`, `crawl`), for a page, an
API endpoint an adapter or recipe asks, or a sitemap.

The steps, in order: the host's rules (its interval setting and robots.txt, `ReadRules`), a turn at the host's rate,
the fetch, then the host's rate adapted to every answer of the fetch (D-1327) and, when the fetch kept no `ok`
answer after a 429 or 503, the host paused by the one back-off rule (`politeness.backoff`). A caller that waits for
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

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
from crawlerai.db.queue import LEASE
from crawlerai.recurring.conditional import Unchanged
from crawlerai.services.scrape_steps import site_row

__all__ = [
    "IN_PLACE",
    "QUEUED",
    "HostRules",
    "Later",
    "PageFetch",
    "ReadRules",
    "Refused",
    "Waiting",
    "page_first",
    "polite_fetch",
    "recording",
    "rules_in",
    "rules_of",
]

# Why a polite fetch sent nothing: robots.txt disallows the URL or could not be read (RFC 9309 §2.3.1.4: then nothing
# is allowed), or the host's turn is further off than the caller waits in place.
ROBOTS: Final = "robots"
ROBOTS_UNREACHABLE: Final = "robots_unreachable"
SLOW_DOWN: Final = "slow_down"


@dataclass(frozen=True)
class HostRules:
    """The rules a request to a host goes by: the site's interval setting and its robots.txt (None when the policy does
    not respect it)."""

    crawl_delay_ms: int | None
    robots: Robots | None = None

    @property
    def gap(self) -> timedelta:
        return interval(self.crawl_delay_ms, None if self.robots is None else self.robots.crawl_delay)

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
# Half the lease leaves the other half for the requests themselves (each within its policy's timeout) and the rest of
# the task; a longer wait would let the claim lapse and another worker send the first request again.
QUEUED: Final = Waiting(postpone=True, bound=LEASE / 2)


class Refused(NamedTuple):
    """Nothing was sent: `ROBOTS`, `ROBOTS_UNREACHABLE` or `SLOW_DOWN`."""

    reason: str


class Later(NamedTuple):
    """The first request's turn is `wait` away: the task is postponed (`QUEUED`)."""

    wait: timedelta


# A page fetch through the polite step: given the URL, the `Admit` each request after its first waits for, and the
# host's rules (D-1384: what it asks of the same host goes by them), the page or a 304 that stands for it (SPEC-11
# §4.2).
PageFetch = Callable[[str, Admit, HostRules], Awaitable[FetchResult | Unchanged]]


async def polite_fetch[R: (FetchResult, FetchResult | Unchanged)](
    url: str,
    policy: FetchPolicy,
    rules: ReadRules,
    limiter: HostLimiter,
    waiting: Waiting,
    fetch: Callable[[str, Admit, HostRules], Awaitable[R]],
    *,
    by_adapter: bool = False,
    turn_taken: bool = False,
    endpoint: bool = False,
    tries: int = 1,
) -> R | Refused | Later:
    """`url` fetched with `fetch` politely (module docstring), or why nothing was sent. `by_adapter`: an active adapter
    serves the URL first (SPEC-15 §4.6) from an API whose own robots.txt its requests go by, so a robots.txt disallow
    of the page admits no fallback to the page rungs, and a fetch that does not keep `ok` is `ROBOTS`. `turn_taken`:
    the caller already holds the host's turn for this request. `endpoint`: every request of the fetch goes to the URL's
    host (an API request); a page fetch's `api` attempts went to other hosts, which their own polite fetch observed.
    `tries` counts this fetch among the work's tries, which the back-off doubles with."""
    known = await rules(url, policy)
    if known is None:
        return Refused(ROBOTS_UNREACHABLE)
    disallowed = not known.allows(url)
    if disallowed and not by_adapter:
        return Refused(ROBOTS)
    host = urlsplit(url).hostname or ""
    if not turn_taken and (unsent := await _first_turn(limiter, host, known.gap, waiting)) is not None:
        return unsent
    admit_next: Admit = refuse if disallowed else partial(limiter.wait, host, known.gap, waiting.bound)
    result = await fetch(url, admit_next, known)
    attempts = result.attempts if endpoint else page_requests(result.attempts)
    limiter.observe(host, known.gap, attempts)
    if isinstance(result, Unchanged) or result.block_class == "ok":
        return result
    pause_host(limiter, host, attempts, tries)
    return Refused(ROBOTS) if disallowed else result


async def _first_turn(limiter: HostLimiter, host: str, gap: timedelta, waiting: Waiting) -> Later | Refused | None:
    if waiting.postpone:
        wait = limiter.admit(host, gap)
        return Later(wait) if wait else None
    return None if await limiter.wait(host, gap, waiting.bound) else Refused(SLOW_DOWN)


def pause_host(limiter: HostLimiter, host: str, attempts: Iterable[AttemptRecord], tries: int) -> None:
    """After a 429 or 503 to a request of a fetch that kept no `ok` answer, admit nothing more to `host` until the
    back-off is over (`politeness.backoff`; the longest backoff when the server asked for longer)."""
    slowed = slowed_down(attempts)
    if slowed is not None:
        limiter.pause(host, backoff(slowed, tries) or BACKOFF_MAX)


def rules_in(conn: AsyncConnection, http: Rung, attempts: list[AttemptRecord]) -> ReadRules:
    """`ReadRules` read in `conn`: the host's site, created on first use as a page's is, and its robots.txt, fetched
    over `http` when the site's snapshot is stale, with the attempts of that fetch added to `attempts`."""

    async def read(url: str, policy: FetchPolicy) -> HostRules | None:
        site = await site_row(conn, urlsplit(url).hostname or "")
        if not policy.respect_robots:
            return HostRules(site.crawl_delay_ms)
        robots = await site_robots(conn, site.id, site.robots_snapshot, url, recording(http, policy, attempts))
        return None if robots is None else HostRules(site.crawl_delay_ms, robots)

    return read


def rules_of(engine: AsyncEngine, http: Rung, attempts: list[AttemptRecord]) -> ReadRules:
    """`rules_in`, each read in a transaction of its own: for a caller that holds no connection while it fetches."""

    async def read(url: str, policy: FetchPolicy) -> HostRules | None:
        async with engine.begin() as conn:
            return await rules_in(conn, http, attempts)(url, policy)

    return read


def page_first(page_host: str, known: HostRules, rules: ReadRules) -> ReadRules:
    """`rules`, except for a URL on `page_host`, whose rules the caller read before fetching its page (`known`) and
    which are not read again (D-1384)."""

    async def first(url: str, policy: FetchPolicy) -> HostRules | None:
        return known if (urlsplit(url).hostname or "") == page_host else await rules(url, policy)

    return first


def recording(rung: Rung, policy: FetchPolicy, attempts: list[AttemptRecord]) -> Fetch:
    """A fetch of robots.txt through `rung` with `policy` that adds the attempts of each fetch to `attempts`. The
    caller's request context and page steps are the page's, not robots.txt's (D-1432): it goes without them."""
    policy = policy.model_copy(update={"context": None, "steps": ()})

    async def fetch(url: str) -> FetchResult:
        result = await rung(url, policy)
        attempts.extend(result.attempts)
        return result

    return fetch
