"""The handler of `crawl` tasks (SPEC-10 §4.5, ARCHITECTURE §13.2): fetch the task's page as a batch task does
(`crawlerai.worker.handlers.steps`), settle it, and add the URLs it leads to to the frontier
(`crawlerai.crawl.frontier`).

A reached page contributes its links and next-page candidates at its depth plus one. The start URL's task also reads
the site's sitemaps (`crawlerai.crawl.sitemaps`: robots.txt `Sitemap:` lines, else `/sitemap.xml`) and adds their
URLs as seeds, at depth 0, even when its own page was not reached. Sitemaps are fetched over HTTP, politely: the
worker waits for the site's rate in place, within `SITEMAP_TIMEOUT_S`, past which the seeds read so far are kept; a
sitemap the SSRF guard refused ends the reading the same way (INV-16: it is never fetched).

A page whose URL matched a page-kind rule (`url_task.page_kind`) is extracted: its formats, or its record, as a
crawl-discovered page (`no_match` when incomplete, ARCHITECTURE §10). A page no rule matched, in a crawl with rules,
ends `links_only` and is never extracted (§13.2, §23). URLs are added after the page is settled, so the job's row is
locked (`Frontier.enqueue`) only for the rest of the task's transaction.
"""

import asyncio
from contextlib import aclosing, suppress
from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.robots import site_robots
from crawlerai.acquire.types import AttemptRecord
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.content.page import ParsedPage
from crawlerai.crawl.frontier import Frontier, discovered
from crawlerai.crawl.sitemaps import SitemapReader, roots
from crawlerai.db.queue import ClaimedTask
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.fetching import Fetching, PoliteHttp, TargetRejected, recording
from crawlerai.services.map import TIMEOUT_S
from crawlerai.services.scrape_steps import fetch_policy, record_fetch_usage, site_row
from crawlerai.worker.handlers.steps import FetchedPage, Records, extract_records, fetch_page, load_job, unreached
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskHandler, TaskResult

SITEMAP_TIMEOUT_S: Final = TIMEOUT_S  # as long as a `map` reads a site's sitemaps (§4.4)


@dataclass(frozen=True)
class _Crawl:
    """A task of a crawl: the request, its frontier, and what the task extracts records with (None: formats)."""

    task: ClaimedTask
    request: CrawlRequest
    frontier: Frontier
    records: Records | None


def crawl_handler(fetching: Fetching, data: EngineData | None, margins: DriftMargins | None) -> TaskHandler:
    """The `crawl` handler of a worker that fetches with `fetching`; `data` is None in a worker without the engine's
    data files, whose records tasks then fail. `margins` decide drift suspensions (SPEC-08 §4.9)."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = CrawlRequest.model_validate(job[0]), job[1]
        return await _run(conn, fetching, _Crawl(task, request, request.frontier(), records))

    return handle


async def _run(conn: AsyncConnection, fetching: Fetching, crawl: _Crawl) -> TaskResult:
    task = crawl.task
    page = await fetch_page(conn, fetching, task, crawl.request.fetch, crawl.request.locale)
    if isinstance(page, (Failed, Postpone)):  # the task runs again: what it adds, it adds then
        return page
    seeds = await _sitemap_seeds(conn, fetching, crawl) if task.canonical_url == crawl.request.start else []
    result, found = (page, ()) if isinstance(page, Finished) else await _visit(conn, crawl, page)
    await crawl.frontier.enqueue(conn, task.job_id, seeds, depth=0, parent=None)
    await crawl.frontier.enqueue(conn, task.job_id, found, depth=task.depth + 1, parent=task.id)
    return result


async def _visit(conn: AsyncConnection, crawl: _Crawl, page: FetchedPage) -> tuple[TaskResult, tuple[str, ...]]:
    """The result of the fetched page, and the URLs it leads to (none when it was not reached)."""
    ended = unreached(page)
    if ended is not None:
        return ended, ()
    bundle = page.result.bundle
    parsed = ParsedPage.of(bundle)
    found: tuple[str, ...] = ()
    # A page at `max_depth` leads nowhere the crawl goes, so its links are not read.
    if crawl.task.depth < crawl.frontier.max_depth:
        # One parse serves the links and the extraction (INV-26); parsing is CPU work, so it runs in a thread.
        found = await asyncio.to_thread(discovered, parsed, bundle.manifest.final_url)
    if crawl.task.page_kind is None and crawl.request.page_kind_rules:
        return Finished("links_only", capture_id=page.capture_id), found
    if crawl.records is None:
        return Finished("extracted", capture_id=page.capture_id), found
    result = await extract_records(conn, crawl.task, page, crawl.records, caller_supplied=False, parsed=parsed)
    return result, found


async def _sitemap_seeds(conn: AsyncConnection, fetching: Fetching, crawl: _Crawl) -> list[str]:
    """The URLs of the site's sitemaps the crawl takes, in the order read, up to its `limit`. The fetches count as
    the job's usage."""
    task, frontier = crawl.task, crawl.frontier
    site = await site_row(conn, frontier.scope.host)
    policy = fetch_policy(crawl.request.fetch, crawl.request.locale, site.proxy_pool)
    attempts: list[AttemptRecord] = []
    robots = None
    if policy.respect_robots:
        # The page's fetch has just stored a fresh snapshot, so this reads it rather than fetching.
        fetch_robots = recording(fetching.rungs.http, policy, attempts)
        robots = await site_robots(conn, site.id, site.robots_snapshot, task.url, fetch_robots)
        if robots is None:
            return []
    polite = PoliteHttp(fetching, frontier.scope.host, site.crawl_delay_ms, robots, policy, attempts)
    reader = SitemapReader(polite.sitemap_body, frontier.scope.host)
    start = roots(task.canonical_url, () if robots is None else robots.sitemaps)
    seeds: dict[str, None] = {}
    with suppress(TimeoutError, TargetRejected):
        async with asyncio.timeout(SITEMAP_TIMEOUT_S), aclosing(reader.urls(start)) as urls:
            async for url in urls:
                if frontier.admits(url):
                    seeds[url] = None
                if len(seeds) >= frontier.limit:
                    break
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    return list(seeds)
