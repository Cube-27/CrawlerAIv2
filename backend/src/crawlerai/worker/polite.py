"""Fetch a task's page politely (SPEC-02 §4.6), for the handlers of job kinds that fetch pages.

The order: robots.txt (unless the job's operator override says otherwise), then the site's rate, then the fetch.
A wait never sleeps in the worker: the task goes back to the queue, and the worker moves on to other sites.
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import BACKOFF_MAX, SLOW_DOWN, HostLimiter, backoff, interval
from crawlerai.acquire.robots import Fetch, site_robots
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Site, SiteId
from crawlerai.db.queue import ClaimedTask
from crawlerai.worker.loop import Failed, Finished, Postpone, Retry, TaskResult


async def fetch_politely(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    policy: FetchPolicy,
    fetch: Fetch,
    limiter: HostLimiter,
) -> FetchResult | TaskResult:
    """The fetched page, or the result the task ends this run with:
    - a robots.txt disallow: `blocked`, reason `robots`, without fetching the page;
    - robots.txt unreachable: a transient failure (RFC 9309 §2.3.1.4 allows nothing until it can be read);
    - the site not admitted yet: postponed until it is;
    - a 429 or 503: retried after the backoff, then `blocked` once attempts run out or when the server asks for
      more than the longest backoff."""
    robots = None
    if policy.respect_robots:
        robots = await site_robots(conn, site_id, task.url, fetch)
        if robots is None:
            return Failed("robots_unreachable", transient=True)
        if not robots.allows(task.url):
            return Finished("blocked", reason="robots")
    crawl_delay_ms = (await conn.execute(select(Site.crawl_delay_ms).where(Site.id == site_id))).scalar_one()
    host = urlsplit(task.url).hostname or ""
    wait = limiter.admit(host, interval(crawl_delay_ms, None if robots is None else robots.crawl_delay))
    if wait:
        return Postpone(wait)

    result = await fetch(task.url)
    manifest = result.bundle.manifest
    if manifest.status_code not in SLOW_DOWN:
        return result
    error = f"http {manifest.status_code}"
    after = backoff(manifest.headers.response, task.attempts, datetime.now(UTC))
    limiter.pause(host, BACKOFF_MAX if after is None else after)
    if after is None:
        return Finished("blocked", reason=error)
    return Retry(after, error, exhausted="blocked")
