"""The scheduler's `recheck_fetch_method`: a site's page kind whose contract says `browser`
(`site_contract`, `acquire.memory`) is tried over HTTP again every 7 days, and set back to `http` when HTTP passes.

The URL tried is the site's latest `ok` capture fetched as that kind (a fetch with no page kind counts as a detail
page's, `memory.remembered_as`): a page known to exist, so a miss is evidence about the method, not the page. The
fetch goes with the default policy, which does not read robots.txt.

A site with a proxy pool is re-checked through it, as its pages are fetched.

The rest of politeness holds by cadence: one page request per site per 7 days is inside any rate limit or
`Crawl-delay`, and a 429 or 503 is a failed re-check whose next try, a turn later, is longer than any backoff.
"""

from datetime import timedelta
from typing import Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.rungs import Rung
from crawlerai.acquire.stored_fetch import fetched_as_kind
from crawlerai.acquire.types import FetchPolicy
from crawlerai.db.models import Capture, FetchMethod, PageKind, SiteContract, SiteId

# A contract set back to `http` forgets the browser engine that taught it and its handoff (`acquire.memory`).
_HTTP: Final = {"engine": None, "handoff": False}
RECHECK_AFTER: Final = timedelta(days=7)
# One site per run: the fetch runs inside the run's transaction, so this bounds how long a site row stays locked,
# and the scheduler runs a full batch again at once, so a backlog still drains in one turn.
RECHECK_BATCH: Final = 1


async def recheck_fetch_method(conn: AsyncConnection, fetch: Rung, *, batch: int) -> int:
    """Re-check up to `batch` due (site, page kind) memories over HTTP, the longest unchecked first, and return how
    many. `fetch` is the HTTP rung."""
    due = (
        select(SiteContract.site_id, SiteContract.page_kind)
        .where(SiteContract.method == "browser", SiteContract.checked_at < func.now() - RECHECK_AFTER)
        .order_by(SiteContract.checked_at.asc())
        .limit(batch)
        .with_for_update(of=SiteContract, skip_locked=True)
    )
    memories = (await conn.execute(due)).all()
    for memory in memories:
        method = await _method(conn, memory.site_id, memory.page_kind, fetch)
        await conn.execute(
            update(SiteContract)
            .where(SiteContract.site_id == memory.site_id, SiteContract.page_kind == memory.page_kind)
            .values(method=method, checked_at=func.now(), **({} if method == "browser" else _HTTP))
        )
    return len(memories)


async def _method(
    conn: AsyncConnection,
    site_id: SiteId,
    kind: PageKind,
    rung: Rung,
) -> FetchMethod:
    latest_ok = (
        select(Capture.url)
        .where(Capture.site_id == site_id, Capture.block_class == "ok", fetched_as_kind(kind))
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    url = (await conn.execute(latest_ok)).scalar_one_or_none()
    if url is None:
        return "browser"
    # The page kind `classify` reads: a listing without repeated items is a shell.
    policy = FetchPolicy(page_kind=kind)
    # `ok` excludes `shell` and `blocked`: the outcomes that sent the site to the browser.
    return "http" if (await rung(url, policy)).block_class == "ok" else "browser"
