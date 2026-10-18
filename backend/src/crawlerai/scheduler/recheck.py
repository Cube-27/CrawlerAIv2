"""The scheduler's `recheck_fetch_method` (acquisition spec): a site's page kind remembered as
`browser` (`site_fetch_method`, D-1380) is tried over HTTP again every 7 days, and set back to `http` when HTTP passes.

The URL tried is the site's latest `ok` capture fetched as that kind (a fetch with no page kind counts as a detail
page's, `rungs.remembered_as`): a page known to exist, so a miss is evidence about the method, not the page. robots.txt
is honoured as for any fetch; a page it disallows, or a robots.txt that cannot be read, leaves the kind on `browser`
until the next turn.

A site with a proxy pool is re-checked through it, as its pages are fetched.

The rest of politeness (§4.6) holds by cadence: one page request per site per 7 days is inside any rate limit or
`Crawl-delay`, and a 429 or 503 is a failed re-check whose next try, a turn later, is longer than any backoff.
"""

from datetime import timedelta
from typing import Final

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.robots import site_robots
from crawlerai.acquire.rungs import Rung
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Capture, FetchMethod, PageKind, Site, SiteFetchMethod, SiteId

RECHECK_AFTER: Final = timedelta(days=7)  # acquisition spec (D-0009)
# One site per run: the fetch runs inside the run's transaction, so this bounds how long a site row stays locked,
# and the scheduler runs a full batch again at once, so a backlog still drains in one turn.
RECHECK_BATCH: Final = 1


async def recheck_fetch_method(conn: AsyncConnection, fetch: Rung, *, batch: int) -> int:
    """Re-check up to `batch` due (site, page kind) memories over HTTP, the longest unchecked first, and return how
    many. `fetch` is the HTTP rung."""
    due = (
        select(SiteFetchMethod.site_id, SiteFetchMethod.page_kind, Site.robots_snapshot, Site.proxy_pool)
        .join(Site, Site.id == SiteFetchMethod.site_id)
        .where(SiteFetchMethod.method == "browser", SiteFetchMethod.checked_at < func.now() - RECHECK_AFTER)
        .order_by(SiteFetchMethod.checked_at.asc())
        .limit(batch)
        .with_for_update(of=SiteFetchMethod, skip_locked=True)
    )
    memories = (await conn.execute(due)).all()
    for memory in memories:
        method = await _method(conn, memory.site_id, memory.page_kind, memory.robots_snapshot, memory.proxy_pool, fetch)
        await conn.execute(
            update(SiteFetchMethod)
            .where(SiteFetchMethod.site_id == memory.site_id, SiteFetchMethod.page_kind == memory.page_kind)
            .values(method=method, checked_at=func.now())
        )
    return len(memories)


def _fetched_as(kind: PageKind) -> ColumnElement[bool]:
    """The captures fetched as `kind`, under `remembered_as`: a capture fetched with no page kind is a detail page's."""
    stated = Capture.fetch_policy["page_kind"].astext
    return stated == kind if kind == "listing" else or_(stated.is_(None), stated == kind)


async def _method(
    conn: AsyncConnection,
    site_id: SiteId,
    kind: PageKind,
    robots_snapshot: str | None,
    proxy_pool: str | None,
    rung: Rung,
) -> FetchMethod:
    latest_ok = (
        select(Capture.url)
        .where(Capture.site_id == site_id, Capture.block_class == "ok", _fetched_as(kind))
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    url = (await conn.execute(latest_ok)).scalar_one_or_none()
    if url is None:
        return "browser"
    # The page kind `classify` reads: a listing without repeated items is a shell (acquisition spec).
    policy = FetchPolicy(proxy_pool=proxy_pool, page_kind=kind)

    async def fetch(page: str) -> FetchResult:
        return await rung(page, policy)

    robots = await site_robots(conn, site_id, robots_snapshot, url, fetch)
    if robots is None or not robots.allows(url):
        return "browser"
    # `ok` excludes `shell` and `blocked`: the outcomes that sent the site to the browser (§7.1).
    return "http" if (await fetch(url)).block_class == "ok" else "browser"
