"""The listing diff (SPEC-11 §4.5, ARCHITECTURE §14 row 4): which URLs of a site's catalog a recurring crawl no longer
finds.

A run is a records crawl that completed. A recurring crawl is the caller re-submitting the same request (§14), so the
runs of one crawl are the records crawls with the same scope: start URL, globs, depth, limit, page-kind rules and
schema. A run's listing is the URLs its frontier gave a page kind, on the start URL's host: every URL of the catalog the
crawl found, whether or not its page was then reached.

`close_run` diffs a run as its job ends (the queue's `ending` hook), in that transaction and before the end event:
- each URL of the listing is seen: `missing_runs` 0, `gone_at` cleared, and the run noted as the last to hold it;
- each URL an earlier run of the crawl last held, and this one did not, has missed one more run, and once it missed
  `GONE_AFTER_RUNS` in a row gets `gone_at` and a `url_gone` event.
A run that reached its `limit` saw part of its listing only, and marks nothing missing; nor does one with an empty
listing, whose pages were not read. A URL no listing held (one a scrape fetched) is never missing.

New URLs are queued by the frontier, which takes every URL a run finds (SPEC-10 §4.5); nothing here adds tasks.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final
from urllib.parse import urlsplit

from sqlalchemy import Row, case, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import record_event
from crawlerai.db.models import Job, JobId, JobStatus, SchemaId, Site, SiteId, UrlState, UrlTask

__all__ = ["GONE_AFTER_RUNS", "URL_GONE", "close_run"]

# ARCHITECTURE §14 row 4: a URL missing from this many consecutive runs is gone.
GONE_AFTER_RUNS: Final = 2
URL_GONE: Final = "url_gone"

# The members of a crawl request that decide which URLs its runs can find (SPEC-10 §4.5). `formats`, `fetch`, `locale`
# and `webhook_url` change what is done with a page, not which pages are listed.
_SCOPE: Final = ("url", "include", "exclude", "max_depth", "limit", "page_kind_rules")

_JobRow = Row[str, SchemaId | None, dict[str, Any]]


async def close_run(conn: AsyncConnection, job_id: JobId, status: JobStatus) -> None:
    """Diff the job's listing against the earlier runs of its crawl, as the job ends in `status`."""
    if status != "completed":
        return
    job: _JobRow = (await conn.execute(select(Job.kind, Job.schema_id, Job.request).where(Job.id == job_id))).one()
    if job.kind != "crawl" or job.schema_id is None:
        return
    host = urlsplit(job.request["url"]).hostname
    site_id = (await conn.execute(select(Site.id).where(Site.host == host))).scalar_one_or_none()
    listing = await _listing(conn, job_id, host)
    if site_id is None or not listing:
        return
    await _seen(conn, site_id, job_id, listing)
    tasks = (await conn.execute(select(func.count()).where(UrlTask.job_id == job_id))).scalar_one()
    if tasks >= job.request["limit"]:
        return
    for url in await _missed(conn, site_id, job_id, job.schema_id, job.request):
        await record_event(conn, job_id, URL_GONE, {"url": url})


async def _listing(conn: AsyncConnection, job_id: JobId, host: str | None) -> list[str]:
    """The job's URLs a page-kind rule matched, on `host`, sorted: rows are locked in one order by every run."""
    query = select(UrlTask.canonical_url).where(UrlTask.job_id == job_id, UrlTask.page_kind.is_not(None))
    urls = (await conn.execute(query)).scalars()
    return sorted(url for url in urls if urlsplit(url).hostname == host)


async def _seen(conn: AsyncConnection, site_id: SiteId, job_id: JobId, urls: Sequence[str]) -> None:
    values = {"last_seen_at": func.now(), "missing_runs": 0, "gone_at": None, "last_seen_job_id": job_id}
    rows = [{"site_id": site_id, "canonical_url": url} | values for url in urls]
    insert = pg_insert(UrlState).values(rows)
    await conn.execute(
        insert.on_conflict_do_update(index_elements=[UrlState.site_id, UrlState.canonical_url], set_=values)
    )


async def _missed(
    conn: AsyncConnection, site_id: SiteId, job_id: JobId, schema_id: SchemaId, request: Mapping[str, Any]
) -> list[str]:
    """Count a missed run for each URL an earlier run of the crawl last held, and return those now gone, sorted."""
    earlier = select(Job.id).where(
        Job.kind == "crawl",
        Job.schema_id == schema_id,
        Job.id != job_id,
        *(Job.request[member] == literal(request[member], JSONB) for member in _SCOPE),
    )
    missing = UrlState.missing_runs + 1
    query = (
        update(UrlState)
        .where(UrlState.site_id == site_id, UrlState.gone_at.is_(None), UrlState.last_seen_job_id.in_(earlier))
        .values(missing_runs=missing, gone_at=case((missing >= GONE_AFTER_RUNS, func.now())))
        .returning(UrlState.canonical_url, UrlState.gone_at)
    )
    return sorted(url for url, gone_at in await conn.execute(query) if gone_at is not None)
