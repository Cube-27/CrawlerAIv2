"""The handler of `crawl` tasks (SPEC-10 §4.5, ARCHITECTURE §13.2): fetch the task's page as a batch task does
(`crawlerai.worker.handlers.steps`), settle it, and add the URLs it leads to to the frontier
(`crawlerai.crawl.frontier`).

A reached page contributes its links and next-page candidates at its depth plus one. The scope is on the host the start
page is on: when the site redirects the start URL to another host of the same site (its `www.` subdomain, or back), the
crawl follows it there (D-0991). The start task stores where its page is on the job (`job.start_location`), the way
every other task reads it, and the URL it was redirected to is never a task of its own: that page is the start task's
(D-1285).

The start URL's task also reads the site's sitemaps (`crawlerai.crawl.sitemaps`: robots.txt `Sitemap:` lines, else
`/sitemap.xml`) and adds their URLs as seeds, at depth 0, even when its own page was not reached, on the attempt that
ends the task: an attempt that is postponed or retried leaves them to the next, so they are read once. Sitemaps are
fetched over HTTP, politely: the worker waits for the site's rate in place, within `SITEMAP_TIMEOUT_S`, past which the
seeds read so far are kept and the job records `sitemaps_timed_out`, so that the listing diff counts the run as partial
(SPEC-11 §4.5); a sitemap the SSRF guard refused ends the reading the same way (INV-16: it is never fetched).

A page whose URL matched a page-kind rule (`url_task.page_kind`) is extracted: its formats, or its record, as a
crawl-discovered page (`no_match` when incomplete, ARCHITECTURE §10). A page no rule matched, in a crawl with rules,
ends `links_only` and is never extracted (§13.2, §23). URLs are added after the page is settled, so the job's row is
locked (`Frontier.enqueue`) only for the rest of the task's transaction.
"""

import asyncio
import logging
from contextlib import aclosing
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.robots import site_robots
from crawlerai.acquire.types import AttemptRecord
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.crawl.frontier import Frontier, discovered
from crawlerai.crawl.rules import located
from crawlerai.crawl.sitemaps import SitemapReader, roots
from crawlerai.db.jobs import record_event
from crawlerai.db.models import Job
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.recurring.listing_diff import SITEMAPS_TIMED_OUT
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.fetching import Fetching, PoliteHttp, TargetRejected, recording
from crawlerai.services.map import TIMEOUT_S
from crawlerai.services.scrape_steps import fetch_policy, record_fetch_usage, site_row
from crawlerai.worker.handlers.steps import (
    Ended,
    FetchedPage,
    Records,
    count_fetch,
    extract_records,
    fetch_page,
    load_job,
    unreached,
)
from crawlerai.worker.loop import Failed, Finished, TaskHandler, TaskResult, ends_task

log = logging.getLogger(__name__)

SITEMAP_TIMEOUT_S: Final = TIMEOUT_S  # as long as a `map` reads a site's sitemaps (§4.4)


@dataclass(frozen=True)
class _Crawl:
    """A task of a crawl: the request, what the task extracts records with (None: formats), and the client role C runs
    on (None: no role C)."""

    task: ClaimedTask
    request: CrawlRequest
    records: Records | None
    llm: LLMClient | None


def crawl_handler(
    fetching: Fetching, data: EngineData | None, margins: DriftMargins | None, *, llm: LLMClient | None
) -> TaskHandler:
    """The `crawl` handler of a worker that fetches with `fetching`; `data` is None in a worker without the engine's
    data files, whose records tasks then fail. `margins` decide drift suspensions (SPEC-08 §4.9); role C runs on `llm`
    (None: no role C)."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = CrawlRequest.model_validate(job[0]), job[1]
        return await _run(conn, fetching, _Crawl(task, request, records, llm))

    return handle


async def _run(conn: AsyncConnection, fetching: Fetching, crawl: _Crawl) -> TaskResult:
    task = crawl.task
    # A page whose links the crawl reads is fetched itself: an API recipe's JSON has none (SPEC-09 §4.8).
    reads_links = task.depth < crawl.request.max_depth or task.page_kind is None
    served = None if reads_links else crawl.records
    page = await fetch_page(
        conn, fetching, task, crawl.request.fetch, crawl.request.locale, served=served, llm=crawl.llm
    )
    result, found = (page.task_result, ()) if isinstance(page, Ended) else await _visit(conn, crawl, page)
    is_start = task.canonical_url == crawl.request.start
    # The sitemaps are read before the task writes its job's row (usage, the frontier), which stays locked until the
    # task commits: a cancel, which locks that row, never waits for the reading (up to `SITEMAP_TIMEOUT_S`).
    reads_sitemaps = is_start and ends_task(task, result)
    # Where the start page is decides what the crawl takes; a task that adds nothing does not look it up.
    adds_urls = bool(found) or reads_sitemaps
    site_url = await _site_url(conn, crawl, page) if adds_urls else crawl.request.start
    frontier = crawl.request.frontier(site_url)
    seeds = await _sitemap_seeds(conn, fetching, crawl, frontier, site_url) if reads_sitemaps else []
    if is_start and adds_urls:
        await conn.execute(update(Job).where(Job.id == task.job_id).values(start_location=site_url))
    await count_fetch(conn, task, page)  # after the extraction, as role C needs (D-0346)
    await frontier.enqueue(conn, task.job_id, seeds, depth=0, parent=None)
    await frontier.enqueue(conn, task.job_id, found, depth=task.depth + 1, parent=task.id)
    return result


async def _site_url(conn: AsyncConnection, crawl: _Crawl, page: FetchedPage | Ended) -> str:
    """Where the crawl's start page is (`rules.located`), which its scope follows: for the start task, from its own
    page's capture; for every other, as the start task stored it on the job (D-1285)."""
    request = crawl.request
    if crawl.task.canonical_url == request.start:
        manifest = None if isinstance(page, Ended) else page.result.bundle.manifest
        return located(request.start, None if manifest is None else (manifest.method, manifest.final_url))
    stored = (await conn.execute(select(Job.start_location).where(Job.id == crawl.task.job_id))).scalar_one()
    return stored or request.start


async def _visit(conn: AsyncConnection, crawl: _Crawl, page: FetchedPage) -> tuple[TaskResult, tuple[str, ...]]:
    """The result of the fetched page, and the URLs it leads to (none when it was not reached)."""
    ended = unreached(page)
    if ended is not None:
        return ended, ()
    bundle = page.result.bundle
    parsed = page.parsed
    found: tuple[str, ...] = ()
    # A page at `max_depth` leads nowhere the crawl goes, so its links are not read.
    if crawl.task.depth < crawl.request.max_depth:
        # One parse serves the links and the extraction (INV-26); parsing is CPU work, so it runs in a thread.
        found = await asyncio.to_thread(discovered, parsed, bundle.manifest.final_url)
    if crawl.task.page_kind is None and crawl.request.page_kind_rules:
        return Finished("links_only", capture_id=page.capture_id), found
    if crawl.records is None:
        return Finished("extracted", capture_id=page.capture_id), found
    result = await extract_records(
        conn, crawl.task, page, crawl.records, caller_supplied=False, llm=crawl.llm, parsed=parsed
    )
    return result, found


async def _sitemap_seeds(
    conn: AsyncConnection, fetching: Fetching, crawl: _Crawl, frontier: Frontier, site_url: str
) -> list[str]:
    """The URLs of the sitemaps of the site the start page is on, `site_url` there, that the crawl takes, in the order
    read, up to its `limit`. The fetches count as the job's usage."""
    task = crawl.task
    site = await site_row(conn, frontier.scope.host)
    policy = fetch_policy(crawl.request.fetch, crawl.request.locale, site.proxy_pool)
    attempts: list[AttemptRecord] = []
    robots = None
    if policy.respect_robots:
        # The page's fetch has just stored a fresh snapshot, so this reads it rather than fetching, unless the page
        # redirected to another host.
        fetch_robots = recording(fetching.rungs.http, policy, attempts)
        robots = await site_robots(conn, site.id, site.robots_snapshot, site_url, fetch_robots)
        if robots is None:
            return []
    polite = PoliteHttp(fetching, frontier.scope.host, site.crawl_delay_ms, robots, policy, attempts)
    reader = SitemapReader(polite.sitemap_body, frontier.scope.host)
    start = roots(site_url, () if robots is None else robots.sitemaps)
    seeds: dict[str, None] = {}
    capped = False
    try:
        async with asyncio.timeout(SITEMAP_TIMEOUT_S), aclosing(reader.urls(start)) as urls:
            async for url in urls:
                if frontier.admits(url):
                    seeds[url] = None
                if len(seeds) >= frontier.limit:
                    break
    except TimeoutError:
        capped = True
    except TargetRejected:
        pass  # a refused sitemap ends the reading: it is never fetched (INV-16)
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    if capped:  # the run saw part of its listing only (SPEC-11 §4.5)
        await record_event(conn, task.job_id, SITEMAPS_TIMED_OUT, {"url": task.url, "seeds": len(seeds)})
    # The task's id and job, never a URL, which `CRAWLERAI_LOG_REDACT_URLS` may keep out of the logs.
    stop = f"; stopped at the {SITEMAP_TIMEOUT_S:g} s time cap" if capped else ""
    log.info("url_task %s: sitemaps of job %s: %d seeds%s", task.id, task.job_id, len(seeds), stop)
    return list(seeds)
