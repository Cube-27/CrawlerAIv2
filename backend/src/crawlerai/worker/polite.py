"""Fetch a task's page politely (SPEC-02 §4.6), for the handlers of job kinds that fetch pages.

The order: robots.txt (unless the job's operator override says otherwise), then the site's rate, then the fetch.
A wait never sleeps in the worker: the task goes back to the queue, and the worker moves on to other sites.
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import BACKOFF_MAX, SLOW_DOWN, HostLimiter, interval, retry_after
from crawlerai.acquire.robots import Fetch, site_robots
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Site, SiteId
from crawlerai.db.queue import ClaimedTask, retry_delay
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskResult


async def fetch_politely(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    policy: FetchPolicy,
    fetch: Fetch,
    limiter: HostLimiter,
    *,
    fetch_robots: Fetch,
) -> FetchResult | TaskResult:
    """The page as `fetch` fetched it, or the result the task ends this run with. robots.txt is fetched with
    `fetch_robots`, a plain HTTP rung: through `acquire`, a robots.txt would classify as a shell and be fetched again
    in the browser. The task ends this run with:
    - a robots.txt disallow: `blocked`, reason `robots`, without fetching the page;
    - robots.txt unreachable: a transient failure, `blocked` once attempts run out (RFC 9309 §2.3.1.4: unreachable
      allows nothing);
    - the site not admitted yet: postponed until it is;
    - a 429 or 503: a transient failure, retried after its `Retry-After` or the queue's backoff, then `blocked` once
      attempts run out; `blocked` at once when the server asks for more than the longest backoff."""
    site = (await conn.execute(select(Site.robots_snapshot, Site.crawl_delay_ms).where(Site.id == site_id))).one()
    robots = None
    if policy.respect_robots:
        robots = await site_robots(conn, site_id, site.robots_snapshot, task.url, fetch_robots)
        if robots is None:
            return Failed("robots_unreachable", transient=True, exhausted="blocked")
        if not robots.allows(task.url):
            return Finished("blocked", reason="robots")
    host = urlsplit(task.url).hostname or ""
    wait = limiter.admit(host, interval(site.crawl_delay_ms, None if robots is None else robots.crawl_delay))
    if wait:
        return Postpone(wait)

    result = await fetch(task.url)
    manifest = result.bundle.manifest
    if manifest.status_code not in SLOW_DOWN:
        return result
    error = f"http {manifest.status_code}"
    asked = retry_after(manifest.headers.response, datetime.now(UTC))
    if asked is not None and asked > BACKOFF_MAX:
        # Retrying before the server allows breaks its request; waiting longer holds the job open without bound.
        limiter.pause(host, BACKOFF_MAX)
        return Finished("blocked", reason=error)
    limiter.pause(host, retry_delay(task.attempts) if asked is None else asked)
    return Failed(error, transient=True, after=asked, exhausted="blocked")
