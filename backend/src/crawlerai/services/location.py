"""A job's crawl location (jobs spec, "Crawl location pinned per job"): the one proxy pool every fetch of the job goes
through, and the egress country that gives records (`core.egress`).

A site may price by the visitor's country, so a job's pages must all be fetched from one place: the request's
`fetch.proxy_pool`, else the pool of the site of the job's first URL (`site.proxy_pool`), else none (a direct fetch).
It is chosen once, at submit, and stored in the job's request, which its workers read; they never fall back to a
site's own pool.
"""

from urllib.parse import urlsplit

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.core.egress import Egress, Egresses
from crawlerai.db.models import Site
from crawlerai.services.fetch_options import FetchOptions

__all__ = ["pin_location", "site_pool"]


async def site_pool(conn: AsyncConnection, url: str) -> str | None:
    """The proxy pool of the site `url` is on, `None` for a site without one or not yet known."""
    host = urlsplit(url).hostname or ""
    return (await conn.execute(select(Site.proxy_pool).where(Site.host == host))).scalar_one_or_none()


async def pin_location[R: BaseModel](
    engine: AsyncEngine, egresses: Egresses | None, request: R, fetch: FetchOptions, first_url: str
) -> tuple[R, Egress]:
    """`request` with the job's pool pinned in its `fetch` (the request's own pool, else `first_url`'s site's), and the
    egress that pool gives (`egresses`; none known: unknown)."""
    pool = fetch.proxy_pool
    if pool is None:
        async with engine.connect() as conn:
            pool = await site_pool(conn, first_url)
        if pool is not None and egresses is not None and pool not in egresses.pools:
            pool = None  # a site's stored pool this deployment no longer configures: a direct fetch, not a failing job
    pinned = request.model_copy(update={"fetch": fetch.model_copy(update={"proxy_pool": pool})})
    return pinned, (egresses or Egresses()).of(pool)
