"""The handler of `crawl` tasks (jobs spec): fetch the task's page as a batch task does
(`crawlerai.worker.handlers.steps`), settle it, and add the URLs it leads to to the frontier
(`crawlerai.crawl.frontier`).

A reached page contributes its links and next-page candidates at its depth plus one. The scope is on the host the start
page is on: when the site redirects the start URL to another host of the same site (its `www.` subdomain, or back), the
crawl follows it there (D-0991). The start task stores where its page is on the job (`job.start_location`), the way
every other task reads it. Every task stores where its page was fetched (`url_task.final_url`), and once it is stored,
the URL the task was redirected to is not added as a task of its own: that page is the redirected task's (jobs spec,
"Crawl frontier and page-kind rules"). A task queued for that URL before then stays a task.

The start URL's task also reads the site's sitemaps (`crawlerai.crawl.sitemaps`: robots.txt `Sitemap:` lines, else
`/sitemap.xml`) and adds their URLs as seeds, at depth 0, even when its own page was not reached, on the attempt that
ends the task: an attempt that is postponed or retried leaves them to the next, so they are read once. Sitemaps are
fetched over HTTP, politely: the worker waits for the site's rate in place, within `SITEMAP_TIMEOUT_S`, past which the
seeds read so far are kept and the job records `sitemaps_timed_out`, so that the listing diff counts the run as partial
(jobs spec); a sitemap the SSRF guard refused ends the reading the same way (INV-16: it is never fetched).

A page whose URL matched a page-kind rule (`url_task.page_kind`) is extracted: its formats, or its record, as a
crawl-discovered page (`no_match` when incomplete). A page no rule matched, in a crawl with rules,
ends `links_only` and is never extracted (§13.2, §23). URLs are added after the page is settled, so the job's row is
locked (`Frontier.enqueue`) only for the rest of the task's transaction.
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Final

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import AttemptRecord
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.crawl.frontier import Frontier, Links, read_links
from crawlerai.crawl.rules import located
from crawlerai.crawl.sitemaps import SitemapReader, roots
from crawlerai.db.jobs import record_event
from crawlerai.db.models import Job, UrlTask
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.normalize.url_key import canonicalize
from crawlerai.recurring.listing_diff import SITEMAPS_TIMED_OUT
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.crawl import CrawlRequest
from crawlerai.services.fetching import Fetching, SiteHttp, TargetRejected
from crawlerai.services.map import TIMEOUT_S
from crawlerai.services.polite import QUEUED, NoTurn, Turns, rules_in
from crawlerai.services.scrape_steps import PageFormat, fetch_policy, record_fetch_usage
from crawlerai.storage.base import ObjectStore
from crawlerai.worker.handlers.steps import (
    Ended,
    FetchedPage,
    Records,
    count_fetch,
    extract_records,
    fetch_page,
    load_job,
    store_further_pages,
    unreached,
)
from crawlerai.worker.loop import Failed, Finished, Postpone, Skipped, TaskHandler, TaskResult, ends_task

log = logging.getLogger(__name__)

SITEMAP_TIMEOUT_S: Final = TIMEOUT_S  # as long as a `map` reads a site's sitemaps (§4.4)


@dataclass(frozen=True)
class _Crawl:
    """A task of a crawl: the request, what the task extracts records with (None: formats), and the client role C runs
    on."""

    task: ClaimedTask
    request: CrawlRequest
    records: Records | None
    llm: LLMClient


def crawl_handler(
    fetching: Fetching, data: EngineData | None, margins: DriftMargins | None, *, llm: LLMClient
) -> TaskHandler:
    """The `crawl` handler of a worker that fetches with `fetching`; `data` is None in a worker without the engine's
    data files, whose records tasks then fail. `margins` decide drift suspensions (learning-configs spec); role C
    runs on `llm`."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = CrawlRequest.model_validate(job[0]), job[1]
        return await _run(conn, fetching, _Crawl(task, request, records, llm))

    return handle


async def _run(conn: AsyncConnection, fetching: Fetching, crawl: _Crawl) -> TaskResult:
    task = crawl.task
    own = crawl.request.frontier()
    if own.strategy != "bfs" and await own.over_limit(conn, task):
        return Skipped()  # leased with the candidates before the pages that spent the limit settled
    if own.strategy == "best_first" and await own.outranked(conn, task):
        return Postpone(timedelta(0))  # a page fetched since it was leased found a better candidate
    # A page whose links the crawl reads is fetched itself: an API recipe's JSON has none (adapters spec).
    reads_links = task.depth < crawl.request.max_depth or task.page_kind is None
    served = None if reads_links else crawl.records
    # A listing recipe's pages count toward the crawl's page bound as its tasks do.
    pages = min(MAX_PAGES, crawl.request.limit)
    page = await fetch_page(
        conn,
        fetching,
        task,
        crawl.request.fetch,
        crawl.request.locale,
        served=served,
        llm=crawl.llm,
        listing_pages=pages,
        formats=_formats_of(task, crawl.request),
    )
    if not isinstance(page, Ended):
        await _record_final_url(conn, task, page)
    result, links = (
        (page.task_result, Links()) if isinstance(page, Ended) else await _visit(conn, fetching.store, crawl, page)
    )
    is_start = task.canonical_url == crawl.request.start
    # The sitemaps are read before the task writes its job's row (usage, the frontier), which stays locked until the
    # task commits: a cancel, which locks that row, never waits for the reading (up to `SITEMAP_TIMEOUT_S`).
    reads_sitemaps = is_start and ends_task(task, result)
    # Where the start page is decides what the crawl takes; a task that adds nothing does not look it up.
    adds_urls = bool(links.urls) or reads_sitemaps
    site_url = await _site_url(conn, crawl, page) if adds_urls else crawl.request.start
    frontier = crawl.request.frontier(site_url)
    seeds, priorities = await _sitemap_seeds(conn, fetching, crawl, frontier, site_url) if reads_sitemaps else ([], {})
    if is_start and adds_urls:
        await conn.execute(update(Job).where(Job.id == task.job_id).values(start_location=site_url))
    await count_fetch(conn, task, page)  # after the extraction, as role C needs (D-0346)
    await frontier.enqueue(conn, task.job_id, seeds, depth=0, parent=None, priorities=priorities)
    await frontier.enqueue(
        conn,
        task.job_id,
        links.urls,
        depth=task.depth + 1,
        parent=task.id,
        anchor_text=links.texts,
        inherited=links.relevance,
    )
    await frontier.close_if_spent(conn, task)
    return result


def _formats_of(task: ClaimedTask, request: CrawlRequest) -> Sequence[PageFormat]:
    """The formats the task's page is fetched for: a page no rule matched is read for its links only, so it needs no
    file made of it."""
    extracted = task.page_kind is not None or not request.page_kind_rules
    return request.formats if extracted else ()


async def _record_final_url(conn: AsyncConnection, task: ClaimedTask, page: FetchedPage) -> None:
    """Store where the task's page was fetched, in canonical form, before the task adds any URL (jobs spec, "Crawl
    frontier and page-kind rules"). An adapter's or API recipe's capture (method `api`) stands for the page it was asked
    for: its final URL is the endpoint, which is no page of the crawl (as `rules.located` reads it)."""
    manifest = page.result.bundle.manifest
    final_url = canonicalize(manifest.url if manifest.method == "api" else manifest.final_url)
    await conn.execute(update(UrlTask).where(UrlTask.id == task.id).values(final_url=final_url))


async def _site_url(conn: AsyncConnection, crawl: _Crawl, page: FetchedPage | Ended) -> str:
    """Where the crawl's start page is (`rules.located`), which its scope follows: for the start task, from its own
    page's capture; for every other, as the start task stored it on the job (D-1285)."""
    request = crawl.request
    if crawl.task.canonical_url == request.start:
        manifest = None if isinstance(page, Ended) else page.result.bundle.manifest
        return located(request.start, None if manifest is None else (manifest.method, manifest.final_url))
    stored = (await conn.execute(select(Job.start_location).where(Job.id == crawl.task.job_id))).scalar_one()
    return stored or request.start


async def _visit(
    conn: AsyncConnection, store: ObjectStore, crawl: _Crawl, page: FetchedPage
) -> tuple[TaskResult, Links]:
    """The result of the fetched page and the links it contributes (none when it was not reached)."""
    ended = unreached(page, crawl.task)
    if ended is not None:
        return ended, Links()
    bundle = page.result.bundle
    parsed = page.parsed
    links = Links()
    # A page at `max_depth` leads nowhere the crawl goes, so its links are not read.
    if crawl.task.depth < crawl.request.max_depth:
        # One parse serves the links and the extraction (INV-26); parsing is CPU work, so it runs in a thread.
        wanted = crawl.request.frontier().wanted if crawl.request.strategy == "best_first" else None
        links = await asyncio.to_thread(read_links, parsed, bundle.manifest.final_url, wanted)
    if crawl.task.page_kind is None and crawl.request.page_kind_rules:
        return Finished("links_only", capture_id=page.capture_id), links
    if crawl.records is None:
        return Finished("extracted", capture_id=page.capture_id), links
    result = await extract_records(
        conn, crawl.task, page, crawl.records, caller_supplied=False, llm=crawl.llm, parsed=parsed
    )
    if isinstance(result, Finished):
        result = await store_further_pages(
            conn, store, crawl.task, page, crawl.records, caller_supplied=False, llm=crawl.llm, result=result
        )
    return result, links


async def _sitemap_seeds(
    conn: AsyncConnection, fetching: Fetching, crawl: _Crawl, frontier: Frontier, site_url: str
) -> tuple[list[str], dict[str, float]]:
    """The URLs of the sitemaps of the site the start page is on, `site_url` there, that the crawl takes, in the order
    read, up to its capacity, with the priorities the sitemaps state for them. The fetches count as the job's usage."""
    task = crawl.task
    policy = fetch_policy(crawl.request.fetch, crawl.request.locale, scope=str(task.job_id))
    attempts: list[AttemptRecord] = []
    # The page's fetch has just stored a fresh snapshot, so this reads it rather than fetching, unless the page
    # redirected to another host.
    # The reading waits in place for the host's turns, as a further request of a task does.
    waiting = replace(QUEUED, postpone=False)
    try:
        rules = await rules_in(conn, fetching.rungs.http, attempts, Turns(fetching.limiter, waiting))(site_url, policy)
    except NoTurn:
        rules = None
    if rules is None:
        return [], {}
    polite = SiteHttp(fetching, rules, policy, attempts, waiting)
    reader = SitemapReader(polite.sitemap_body, frontier.scope.host)
    start = roots(site_url, () if rules.robots is None else rules.robots.sitemaps)
    seeds: dict[str, None] = {}
    capped = False
    try:
        async with asyncio.timeout(SITEMAP_TIMEOUT_S), aclosing(reader.urls(start)) as urls:
            async for url in urls:
                if frontier.admits(url):
                    seeds[url] = None
                if len(seeds) >= frontier.capacity:
                    break
    except TimeoutError:
        capped = True
    except TargetRejected:
        pass  # a refused sitemap ends the reading: it is never fetched (INV-16)
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    if capped:  # the run saw part of its listing only (jobs spec)
        await record_event(conn, task.job_id, SITEMAPS_TIMED_OUT, {"url": task.url, "seeds": len(seeds)})
    # The task's id and job, never a URL, which `CRAWLERAI_LOG_REDACT_URLS` may keep out of the logs.
    stop = f"; stopped at the {SITEMAP_TIMEOUT_S:g} s time cap" if capped else ""
    log.info("url_task %s: sitemaps of job %s: %d seeds%s", task.id, task.job_id, len(seeds), stop)
    return list(seeds), {url: reader.priorities[url] for url in seeds if url in reader.priorities}
