"""The scheduler's `recheck_fetch_method` (SPEC-02 §4.4, ARCHITECTURE §7.1): a site remembered as `browser` is
tried over HTTP again every 7 days, and set back to `http` when HTTP passes.

The URL tried is the site's latest `ok` capture: a page known to exist, so a miss is evidence about the method, not
the page. robots.txt is honoured as for any fetch; a page it disallows, or a robots.txt that cannot be read, leaves
the site on `browser` until the next turn.

A site with a proxy pool is re-checked through it, as its pages are fetched (ARCHITECTURE §7.1).

The rest of politeness (§4.6) holds by cadence: one page request per site per 7 days is inside any rate limit or
`Crawl-delay`, and a 429 or 503 is a failed re-check whose next try, a turn later, is longer than any backoff.
"""

from datetime import timedelta
from typing import Final

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.robots import site_robots
from crawlerai.acquire.rungs import Rung
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Capture, FetchMethod, Site, SiteId

RECHECK_AFTER: Final = timedelta(days=7)  # SPEC-02 §4.4 (D-0009)
# One site per run: the fetch runs inside the run's transaction, so this bounds how long a site row stays locked,
# and the scheduler runs a full batch again at once, so a backlog still drains in one turn.
RECHECK_BATCH: Final = 1


async def recheck_fetch_method(conn: AsyncConnection, fetch: Rung, *, batch: int) -> int:
    """Re-check up to `batch` due sites over HTTP, the longest unchecked first, and return how many. `fetch` is the
    HTTP rung."""
    due = (
        select(Site.id, Site.robots_snapshot, Site.proxy_pool)
        .where(
            Site.fetch_method == "browser",
            or_(Site.fetch_method_checked_at.is_(None), Site.fetch_method_checked_at < func.now() - RECHECK_AFTER),
        )
        .order_by(Site.fetch_method_checked_at.asc().nulls_first())
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    sites = (await conn.execute(due)).all()
    for site in sites:
        method = await _method(conn, site.id, site.robots_snapshot, site.proxy_pool, fetch)
        await conn.execute(
            update(Site).where(Site.id == site.id).values(fetch_method=method, fetch_method_checked_at=func.now())
        )
    return len(sites)


async def _method(
    conn: AsyncConnection, site_id: SiteId, robots_snapshot: str | None, proxy_pool: str | None, rung: Rung
) -> FetchMethod:
    latest_ok = (
        select(Capture.url)
        .where(Capture.site_id == site_id, Capture.block_class == "ok")
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    url = (await conn.execute(latest_ok)).scalar_one_or_none()
    if url is None:
        return "browser"
    policy = FetchPolicy(proxy_pool=proxy_pool)

    async def fetch(page: str) -> FetchResult:
        return await rung(page, policy)

    robots = await site_robots(conn, site_id, robots_snapshot, url, fetch)
    if robots is None or not robots.allows(url):
        return "browser"
    # `ok` excludes `shell` and `blocked`: the outcomes that sent the site to the browser (§7.1).
    return "http" if (await fetch(url)).block_class == "ok" else "browser"
