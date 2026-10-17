"""The listing diff (SPEC-11 §4.5, ARCHITECTURE §14 row 4): which URLs of a site's catalog a recurring crawl no longer
finds.

A run is a records crawl that completed. A recurring crawl is the caller re-submitting the same request (§14), so the
runs of one crawl are the records crawls with the same scope: start URL, globs, depth, limit, page-kind rules and
schema. A run's listing is the URLs its frontier gave a page kind, on the host the start page is on
(`job.start_location`): every URL of the catalog the crawl found, whether or not its page was then reached; and, for a
listing schema, the row URLs of the records its pages stand for (`resolve.records.row_url_fields`), which no task
fetches.

`close_run` diffs a run as its job ends (the queue's `ending` hook), in that transaction and before the end event:
- each URL of the listing is seen: `missing_runs` 0, `gone_at` cleared, and the run noted as the last to hold it;
- each URL an earlier run of the crawl last held, and this one did not, has missed one more run, and once it missed
  `GONE_AFTER_RUNS` in a row gets `gone_at` and a `url_gone` event.
A run that saw part of its listing only marks nothing missing: one that reached its `limit`, where the frontier stopped
adding URLs; one with an empty listing, whose pages were not read; one with a page no rule matched (a navigation
page) that was not reached, as the crawl handler reads no links from a `blocked`, `shell` or failed page; and one whose
sitemap reading stopped at its time cap (`SITEMAPS_TIMED_OUT`), whose sitemaps' tail was not read. A navigation page
`not_found` is gone itself, and what only it listed is missing. A URL no listing held (one a scrape fetched) is
never missing.

The diffs of a site's runs take the site's row lock first, so two runs ending together never lock its `url_state` rows
in opposite orders.

New URLs are queued by the frontier, which takes every URL a run finds (SPEC-10 §4.5); nothing here adds tasks.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

from sqlalchemy import Row, case, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import record_event
from crawlerai.db.models import (
    Job,
    JobEvent,
    JobId,
    JobStatus,
    Record,
    SchemaId,
    Site,
    SiteId,
    TaskOutcome,
    TaskRecord,
    UrlState,
    UrlTask,
)
from crawlerai.normalize.url_key import canonicalize
from crawlerai.resolve.records import row_url_fields
from crawlerai.schemas import registry

__all__ = ["GONE_AFTER_RUNS", "SITEMAPS_TIMED_OUT", "URL_GONE", "close_run"]

# ARCHITECTURE §14 row 4: a URL missing from this many consecutive runs is gone.
GONE_AFTER_RUNS: Final = 2
URL_GONE: Final = "url_gone"
# The event of a crawl whose sitemap reading stopped at its time cap (`crawlerai.worker.handlers.crawl`).
SITEMAPS_TIMED_OUT: Final = "sitemaps_timed_out"

# The members of a crawl request that decide which URLs its runs can find (SPEC-10 §4.5). `formats`, `fetch`, `locale`
# and `webhook_url` change what is done with a page, not which pages are listed.
_SCOPE: Final = ("url", "include", "exclude", "max_depth", "limit", "page_kind_rules")

# The outcomes of a page the crawl handler read no links from (`crawlerai.worker.handlers.crawl`).
_UNREACHED: Final[frozenset[TaskOutcome]] = frozenset({"blocked", "shell", "failed"})

_JobRow = Row[str, SchemaId | None, dict[str, Any], str | None]


@dataclass(frozen=True)
class _Listing:
    """A run's listing: its URLs a page-kind rule matched, sorted (every run locks rows in one order); how many tasks
    the job has; and whether a page no rule matched was not reached."""

    urls: list[str]
    tasks: int
    unreached: bool


async def close_run(conn: AsyncConnection, job_id: JobId, status: JobStatus) -> None:
    """Diff the job's listing against the earlier runs of its crawl, as the job ends in `status`."""
    if status != "completed":
        return
    columns = (Job.kind, Job.schema_id, Job.request, Job.start_location)
    job: _JobRow = (await conn.execute(select(*columns).where(Job.id == job_id))).one()
    if job.kind != "crawl" or job.schema_id is None:
        return
    # The host the crawl's scope followed the start page to (D-1285), else the start URL's.
    host = urlsplit(job.start_location or job.request["url"]).hostname
    site = select(Site.id).where(Site.host == host).with_for_update()
    site_id = (await conn.execute(site)).scalar_one_or_none()
    if site_id is None:
        return
    listing = await _listing(conn, job_id, host, job.schema_id)
    if not listing.urls:
        return
    await _seen(conn, site_id, job_id, listing.urls)
    if listing.unreached or listing.tasks >= job.request["limit"] or await _sitemaps_timed_out(conn, job_id):
        return
    for url in await _missed(conn, site_id, job_id, job):
        await record_event(conn, job_id, URL_GONE, {"url": url})


async def _listing(conn: AsyncConnection, job_id: JobId, host: str | None, schema_id: SchemaId) -> _Listing:
    """The job's listing, of its URLs on `host`: its tasks' and its rows'."""
    query = select(UrlTask.canonical_url, UrlTask.page_kind, UrlTask.outcome).where(UrlTask.job_id == job_id)
    tasks = (await conn.execute(query)).all()
    listed = {url for url, page_kind, _ in tasks if page_kind is not None and urlsplit(url).hostname == host}
    listed.update(url for url in await _row_urls(conn, job_id, schema_id) if urlsplit(url).hostname == host)
    unreached = any(page_kind is None and outcome in _UNREACHED for _, page_kind, outcome in tasks)
    return _Listing(sorted(listed), len(tasks), unreached)


async def _row_urls(conn: AsyncConnection, job_id: JobId, schema_id: SchemaId) -> list[str]:
    """The canonical row URLs of the records the job's tasks stand for, found unchanged or stored: the first
    `row_url_fields` value a record publishes. None for a schema that is no listing or names no row URL."""
    schema = await registry.get_by_id(conn, schema_id)
    fields = row_url_fields(schema)
    if schema.page_kind != "listing" or not fields:
        return []
    row_url = func.coalesce(*(Record.data[name].astext for name in fields))
    of_job = (
        select(row_url)
        .join(TaskRecord, TaskRecord.record_id == Record.id)
        .join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
        .where(UrlTask.job_id == job_id)
        .distinct()
    )
    return [url for url in map(canonicalize, (await conn.execute(of_job)).scalars()) if url is not None]


async def _sitemaps_timed_out(conn: AsyncConnection, job_id: JobId) -> bool:
    timed_out = exists().where(JobEvent.job_id == job_id, JobEvent.kind == SITEMAPS_TIMED_OUT)
    return bool((await conn.execute(select(timed_out))).scalar_one())


async def _seen(conn: AsyncConnection, site_id: SiteId, job_id: JobId, urls: Sequence[str]) -> None:
    values = {"last_seen_at": func.now(), "missing_runs": 0, "gone_at": None, "last_seen_job_id": job_id}
    rows = [{"site_id": site_id, "canonical_url": url} | values for url in urls]
    insert = pg_insert(UrlState).values(rows)
    await conn.execute(
        insert.on_conflict_do_update(index_elements=[UrlState.site_id, UrlState.canonical_url], set_=values)
    )


async def _missed(conn: AsyncConnection, site_id: SiteId, job_id: JobId, job: _JobRow) -> list[str]:
    """Count a missed run for each URL an earlier run of the crawl last held, and return those now gone, sorted. The
    site's rows reach their last job by its key, so earlier jobs of other crawls are never scanned."""
    missing = UrlState.missing_runs + 1
    query = (
        update(UrlState)
        .where(
            UrlState.site_id == site_id,
            UrlState.gone_at.is_(None),
            UrlState.last_seen_job_id == Job.id,
            Job.id != job_id,
            Job.kind == "crawl",
            Job.schema_id == job.schema_id,
            *(Job.request[member] == literal(job.request[member], JSONB) for member in _SCOPE),
        )
        .values(missing_runs=missing, gone_at=case((missing >= GONE_AFTER_RUNS, func.now())))
        .returning(UrlState.canonical_url, UrlState.gone_at)
    )
    return sorted(url for url, gone_at in await conn.execute(query) if gone_at is not None)
