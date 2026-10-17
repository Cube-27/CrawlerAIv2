"""Fetch a task's page politely (SPEC-02 §4.6), for the handlers of job kinds that fetch pages.

The order: robots.txt (unless the job's operator override says otherwise), then the site's rate, then the fetch.
A wait for the page's first request never sleeps in the worker: the task goes back to the queue, and the worker moves
on to other sites. A further request the fetch makes, the browser retry, waits in place for its turn: the first
request is spent, and postponing would send it again. After a 503 interstitial, that turn comes no sooner than the
pause the site asked for (`Admit`). A turn more than `WAIT_MAX` away is not waited for, since the task's claim would
lapse (`LEASE`) and another worker send the first request again; the fetch keeps the outcome it has.
"""

from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import BACKOFF_MAX, Admit, HostLimiter, interval, page_requests, refuse, slowed_down
from crawlerai.acquire.robots import Fetch, Robots, site_robots
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Site, SiteId
from crawlerai.db.queue import LEASE, ClaimedTask, retry_delay
from crawlerai.recurring.conditional import Unchanged
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskResult

# The longest wait in place for a further request's turn: half the lease leaves the other half for the requests
# themselves (each within its policy's timeout) and the rest of the task.
WAIT_MAX: Final = LEASE / 2

# The rules the page's host goes by, as `fetch_politely` read them before the fetch: the site's interval setting and
# robots.txt (None when the policy does not respect it).
HostRules = tuple[int | None, Robots | None]
# A page fetch, which answers `Unchanged` when it sent validators the page still matches (SPEC-11 §4.2), admits each
# request after its first with the `Admit` it is given, and has the page host's `HostRules` (D-1384).
PageFetch = Callable[[str, Admit, HostRules], Awaitable[FetchResult | Unchanged]]


async def fetch_politely(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    policy: FetchPolicy,
    fetch: PageFetch,
    limiter: HostLimiter,
    *,
    fetch_robots: Fetch,
    by_adapter: bool = False,
) -> FetchResult | Unchanged | TaskResult:
    """The page as `fetch` fetched it, `Unchanged` included, or the result the task ends this run with. robots.txt is
    fetched with `fetch_robots`, a plain HTTP rung: through `acquire`, a robots.txt would classify as a shell and be
    fetched again in the browser. The task ends this run with:
    - a robots.txt disallow: `blocked`, reason `robots`, without fetching the page; or, `by_adapter` (an active
      adapter serves the URL first, SPEC-15 §4.6, from an API whose own robots.txt its requests go by), the adapter's
      answer when it is `ok`, else `blocked`, reason `robots`, with no fallback to the page rungs admitted;
    - robots.txt unreachable: a transient failure, `blocked` once attempts run out (RFC 9309 §2.3.1.4: unreachable
      allows nothing);
    - the site not admitted yet: postponed until it is;
    - a 429 or 503 to any request of the fetch, not only the one whose outcome it kept, unless the outcome kept is
      `ok` (the page an adapter's endpoint fell back to, SPEC-15 §4.9): a transient failure, retried after its
      `Retry-After` or the queue's backoff, then `blocked` once attempts run out; `blocked` at once when the server
      asks for more than the longest backoff.
    `fetch` admits each request after its first at the site's rate, waiting in place (`HostLimiter.wait`) up to
    `WAIT_MAX`."""
    site = (await conn.execute(select(Site.robots_snapshot, Site.crawl_delay_ms).where(Site.id == site_id))).one()
    robots = None
    if policy.respect_robots:
        robots = await site_robots(conn, site_id, site.robots_snapshot, task.url, fetch_robots)
    if policy.respect_robots and robots is None:
        return Failed("robots_unreachable", transient=True, exhausted="blocked")
    disallowed = robots is not None and not robots.allows(task.url)
    if disallowed and not by_adapter:
        return Finished("blocked", reason="robots")
    host = urlsplit(task.url).hostname or ""
    gap = interval(site.crawl_delay_ms, None if robots is None else robots.crawl_delay)
    if wait := limiter.admit(host, gap):
        return Postpone(wait)

    admit_next = refuse if disallowed else partial(limiter.wait, host, gap, WAIT_MAX)
    result = await fetch(task.url, admit_next, (site.crawl_delay_ms, robots))
    limiter.observe(host, gap, page_requests(result.attempts))
    if isinstance(result, Unchanged) or result.block_class == "ok":
        return result
    if disallowed:
        return Finished("blocked", reason="robots")
    return _backed_off(result, limiter, host, task)


def _backed_off(result: FetchResult, limiter: HostLimiter, host: str, task: ClaimedTask) -> FetchResult | TaskResult:
    """A fetch that kept no `ok` page: the result, or, after a 429 or 503 to any of its requests, the host paused and
    the task retried after the server's `Retry-After` or the queue's backoff (`fetch_politely`)."""
    slowed = slowed_down(result.attempts)
    if slowed is None:
        return result
    error = f"http {slowed.status}"
    asked = slowed.retry_after
    if asked is not None and asked > BACKOFF_MAX:
        # Retrying before the server allows breaks its request; waiting longer holds the job open without bound.
        limiter.pause(host, BACKOFF_MAX)
        return Finished("blocked", reason=error)
    limiter.pause(host, retry_delay(task.attempts) if asked is None else asked)
    return Failed(error, transient=True, after=asked, exhausted="blocked")
