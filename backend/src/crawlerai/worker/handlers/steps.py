"""What the handlers of page tasks (`batch_scrape`, `crawl`) do the same way: the task's job, and the records the task
extracts with as the job pinned them (INV-28); fetching its page politely and storing the capture; the result a page
that was not reached ends with; and extracting and storing a reached page's record (jobs spec, "Fresh extraction").

A listing whose records the job reads, on a site whose pinned config has a listing recipe (one with pagination,
Appendix A #59), is served by the recipe page after page (`RecipeRung.pages`) up to the job's page bound
(`listing_pages`); the first page is the task's capture and record, and each further page is stored under the task as a
listing's further kept state is (`store_further`). When the recipe does not serve the first page, the page
is fetched by the rungs as any page is.

The task's page is fetched before the worker's transaction for the task opens (`fetch_page`): the site's row, its
robots.txt, its adapter declines and what the fetch taught its memory (`acquire.memory`) are each read or written in a
short transaction of their own, so no task holds a site's rows while it fetches or extracts, and the tasks of one site
run side by side. Every later step (`keep_page`, the extraction) writes in the worker's transaction for the task, so a
task that raises rolls back alone (INV-31); site memory only is learned beside it. The task's fetch attempts are
counted as the job's usage at its end (`count_fetch`): that write locks the job's row until the task commits.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from http import HTTPStatus
from typing import Final
from urllib.parse import urlsplit

from pydantic import TypeAdapter
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.challenge import vendor_block
from crawlerai.acquire.memory import learn_fetch
from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.politeness import Admit, HostLimiter, backoff, slowed_down
from crawlerai.acquire.rungs import NO_PLAN
from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.config_ir.active import config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.core.retry import backoff_delay
from crawlerai.db.models import CaptureId, Job, SchemaId
from crawlerai.db.queue import LEASE, TASK_DEADLINE, ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.task import ActiveConfig
from crawlerai.resolve.types import Probability
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.batch import JobPins
from crawlerai.services.fetching import (
    Fetching,
    PagePlan,
    RecipePages,
    page_fetch,
    refusal,
    site_rungs,
    store_declines,
)
from crawlerai.services.polite import (
    QUEUED,
    ROBOTS_UNREACHABLE,
    HostRules,
    Later,
    PageFetch,
    ReadRules,
    Refused,
    Turns,
    polite_fetch,
    rules_of,
)
from crawlerai.services.scrape_steps import (
    EXTRACTION_ERROR,
    FetchOptions,
    PageFormat,
    RenderOptions,
    SiteRow,
    blocked_reason,
    extract_further,
    fetch_failure,
    fetch_policy,
    reached_outcome,
    record_fetch_usage,
    site_row,
    store_further,
    store_page_record,
    surface_plan,
)
from crawlerai.services.stored_captures import NOT_CACHED, recent_capture, reread
from crawlerai.storage.base import ObjectStore
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskResult

log = logging.getLogger(__name__)

# A listing recipe's page requests start within this share of the task's lease (`LEASE`): each waits in place for its
# turn at most `QUEUED.bound` (half the lease), so the last one ends inside the lease, its timeout and the extraction
# after it included, and no other worker claims the task and sends its requests again.
RECIPE_PAGES_SHARE: Final = LEASE / 4
# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"
# A page a vendor's challenge kept out is fetched at most this many times (master plan 2026-10-18 §3.1), and only once
# when the browser rung met that challenge itself: a retry sends the same rungs to the same challenge.
_VENDOR_TRIES: Final = 2
# A page a 429 kept out (RFC 6585 §4) is fetched at most this many times: one retry after the back-off, from the
# pool's next address, then `blocked`.
_TOO_MANY_TRIES: Final = 2

# The request's `min_confidence`, as the job row stores it.
_MIN_CONFIDENCE: Final = TypeAdapter(Probability)
_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


@dataclass(frozen=True)
class Records:
    """What a records task extracts with: the job's schema, the engine data and the config for the task's host its
    pins give, the config bound to its executor (None: cold), the drift margins of this worker, and the job's pinned
    `render` (None: the job inherits its surface's, rest-api spec "Render mode")."""

    schema: SchemaDef
    data: EngineData
    config: ActiveConfig | None
    margins: DriftMargins | None
    render: RenderOptions | None = None


async def load_job(
    conn: AsyncConnection, task: ClaimedTask, data: EngineData | None, margins: DriftMargins | None
) -> tuple[dict[str, object], Records | None] | Failed:
    """The task's job request, and what the task extracts records with from the job's schema and pins (`JobPins`):
    None for a job without records. The pinned config is read and bound once, whatever its status now (INV-28). A
    records task fails in a worker without the engine's data (`data` None)."""
    job: _JobRow = (
        await conn.execute(select(Job.request, Job.schema_id, Job.pinned).where(Job.id == task.job_id))
    ).one()
    if job.schema_id is None:
        return job.request, None
    if data is None:
        return Failed(RECORDS_UNAVAILABLE, transient=False)
    pins = JobPins.model_validate(job.pinned)
    floor = job.request.get("min_confidence")
    pinned = data.pinned(pins.engine_data).with_min_confidence(
        None if floor is None else _MIN_CONFIDENCE.validate_python(floor)
    )
    config_id = pins.configs.get(urlsplit(task.url).hostname or "")
    config = None if config_id is None else await config_by_id(conn, config_id, pinned.vocabulary)
    render = job.request.get("render")
    pinned_render = None if render is None else RenderOptions.model_validate(render)
    schema = await _with_drafted_labels(conn, job.schema_id, pins.schema_)
    return job.request, Records(schema, pinned, config, margins, pinned_render)


async def _with_drafted_labels(conn: AsyncConnection, schema_id: SchemaId, pinned: SchemaDef) -> SchemaDef:
    """The pinned schema, with the label synonyms stored since the job was submitted when it was pinned without: they
    are drafted off the request path (`s_labels.with_labels`), and are no part of the document the job pins (schemas
    spec, "Label synonyms"), so they apply while the row still holds that document."""
    if pinned.labels is not None:
        return pinned
    stored = await registry.get_by_id(conn, schema_id)
    if stored.labels is None or document_digest(stored) != document_digest(pinned):
        return pinned
    return pinned.model_copy(update={"labels": stored.labels})


@dataclass(frozen=True)
class Fetched:
    """The task's page as fetched, before the task's transaction: its site, the fetch, its stored capture when it was
    read from one (`cache: only`), else None until `keep_page` stores it, and the fetch attempts."""

    site: SiteRow
    result: FetchResult
    capture_id: CaptureId | None
    attempts: tuple[AttemptRecord, ...]
    proxy_pool: str | None
    further: tuple[FetchResult, ...] = ()  # a listing recipe's further pages, in order


@dataclass(frozen=True)
class FetchedPage:
    """The task's page as fetched, its site, its stored capture, and the fetch attempts, which `count_fetch` counts as
    the job's usage."""

    site: SiteRow
    result: FetchResult
    capture_id: CaptureId
    attempts: tuple[AttemptRecord, ...]
    proxy_pool: str | None
    further: tuple[FetchResult, ...] = ()  # a listing recipe's further pages, in order

    @property
    def parsed(self) -> ParsedPage:
        """The page's one parse (INV-26)."""
        return ParsedPage.of(self.result.bundle)


@dataclass(frozen=True)
class Ended:
    """A task that ends this run without a page to extract, with what it ends with, and the fetch attempts it made,
    which `count_fetch` counts as the job's usage."""

    task_result: TaskResult
    attempts: tuple[AttemptRecord, ...] = ()
    proxy_pool: str | None = None


async def fetch_page(
    engine: AsyncEngine,
    fetching: Fetching,
    task: ClaimedTask,
    options: FetchOptions,
    locale: str | None,
    *,
    served: Records | None = None,
    listing_pages: int = MAX_PAGES,
    formats: Sequence[PageFormat] = (),
    planned: Records | None = None,
) -> Fetched | Ended:
    """Fetch the task's page politely (`fetch_queued`: robots.txt over HTTP, the page through `acquire`), outside any
    transaction of the task, each read and write through `engine` in a short transaction of its own (module
    docstring), or the result the task ends this run with. Neither writes the job's usage. A request the SSRF
    guard refused fails the task at once (INV-16): the task's URL is checked before anything, as the services that
    fetch while the caller waits check theirs (`check_target`), since a crawl's URLs were never checked at submit.

    With `served`, the records the task extracts with when they are all it reads of the page, the config they name
    serves the page through its API recipe when it has one (adapters spec, `recipe_rung`). A listing's recipe with
    pagination serves up to
    `listing_pages` pages of it (module docstring).

    `formats` are those the task's page is read for: a screenshot or PDF among them is made in the browser
    (`fetch_policy`).

    With `planned`, the records the task extracts with, the page is fetched by the plan its config's field sources and
    its surface's render mode dictate (`surface_plan`)."""
    try:
        await fetching.connector.check(task.url)
    except SsrfRejected as e:
        return Ended(Failed(str(e), transient=False))
    host = urlsplit(task.url).hostname or ""
    read_with = planned or served
    policy = fetch_policy(
        options,
        locale,
        page_kind=task.page_kind,
        schema=None if read_with is None else read_with.schema,
        formats=formats,
    )
    # A new host's site row is committed at once, so the other tasks of the host do not wait on it.
    async with engine.begin() as conn:
        site = await site_row(conn, host, task.page_kind)
    if options.cache == "only":
        # A page the config's API recipe serves was stored as its JSON, as a scrape reads it.
        api = served is not None and served.config is not None and recipe_of(served.config) is not None
        return await _stored_page(engine, fetching, task, site, policy, formats, api=api)
    # The task's deadline runs from its claim, a moment before this (`worker.loop`).
    deadline = time.monotonic() + TASK_DEADLINE.total_seconds()
    by_sources = NO_PLAN
    if planned is not None:
        async with engine.connect() as conn:
            by_sources = await surface_plan(conn, site.id, planned.schema, planned.config, planned.render)
    rungs = site_rungs(fetching, host, site)
    plain = PagePlan(rungs, site, policy, [], deadline=deadline, fetch=by_sources)
    plan = _plan(served, listing_pages, plain)
    rules = rules_of(engine, fetching.rungs.http, plan.attempts, Turns(fetching.limiter, QUEUED))
    fetch = page_fetch(fetching, plan, rules, QUEUED)
    by_adapter = rungs.adapters.would_serve(task.url)
    fetched = await fetch_queued(task, policy, rules, fetch, fetching.limiter, by_adapter=by_adapter)
    await store_declines(engine, site, host, rungs)
    return await _learned(engine, plan, fetched)


def _plan(served: Records | None, listing_pages: int, plan: PagePlan) -> PagePlan:
    """`plan` with what `served` adds: the config's API recipe, serving a listing in pages when it has pagination."""
    if served is None:
        return plan
    recipe = None if served.config is None else recipe_of(served.config)
    lists = served.schema.page_kind == "listing" and recipe is not None and recipe.pagination is not None
    deadline = time.monotonic() + RECIPE_PAGES_SHARE.total_seconds()
    pages = RecipePages(listing_pages, plan.attempts, deadline=deadline) if lists else None
    return replace(plan, recipe=recipe, pages=pages)


async def _learned(engine: AsyncEngine, plan: PagePlan, fetched: FetchResult | TaskResult) -> Fetched | Ended:
    """The fetched page, with what its fetch taught remembered on its site (`acquire.memory.learn_fetch`), or how the
    task ends: a refused request, a listing recipe's further page's too, fails it (INV-16)."""
    site, attempts, pool = plan.site, tuple(plan.attempts), plan.policy.proxy_pool
    if isinstance(fetched, FetchResult):
        further_refused = None if plan.pages is None else plan.pages.refused
        if (refused := refusal(fetched) or further_refused) is None:
            await learn_fetch(engine, site.id, fetched)
            further = () if plan.pages is None else tuple(plan.pages.further)
            return Fetched(site, fetched, None, attempts, pool, further)
        fetched = Failed(refused, transient=False)
    return Ended(fetched, attempts, pool)


async def keep_page(conn: AsyncConnection, store: ObjectStore, page: Fetched | Ended) -> FetchedPage | Ended:
    """The fetched page with its capture stored in the task's transaction (`acquire.persist.store_capture`), unless it
    was read from a stored one; a task that ends without a page, as it ends."""
    if isinstance(page, Ended):
        return page
    capture_id = page.capture_id
    if capture_id is None:
        capture_id = await store_capture(conn, store, page.result, page.site.id)
    return FetchedPage(page.site, page.result, capture_id, page.attempts, page.proxy_pool, page.further)


async def fetch_queued(
    task: ClaimedTask,
    policy: FetchPolicy,
    rules: ReadRules,
    fetch: PageFetch,
    limiter: HostLimiter,
    *,
    by_adapter: bool = False,
) -> FetchResult | TaskResult:
    """The task's page through the polite fetch (`polite_fetch`, `QUEUED`), or the result the task ends this run with:
    - a robots.txt disallow: `blocked`, reason `robots`, without fetching the page; or, `by_adapter` (an active adapter
      serves the URL first, adapters spec, from an API whose own robots.txt its requests go by), its answer when it is
      `ok`, else `blocked`, reason `robots`, with no fallback to the page rungs admitted;
    - robots.txt unreachable: a transient failure, `blocked` once attempts run out (RFC 9309 §2.3.1.4: unreachable
      allows nothing);
    - the site not admitted yet, or the host's turn for a further request further off than the worker waits:
      postponed until it is, or `blocked`;
    - a 429 or 503 to any request of the fetch, unless the outcome kept is `ok` (the page an adapter's endpoint fell
      back to, adapters spec): a transient failure, retried after the back-off (`politeness.backoff`), `blocked` once
      attempts run out (a 429's after one retry), and at once when the server asks for more than the longest backoff.
    The task is logged as running once the site admits its fetch: a postponed task did not run."""

    async def admitted(url: str, admit: Admit, known: HostRules) -> FetchResult:
        log.info("url_task %s of job %s: running", task.id, task.job_id)
        return await fetch(url, admit, known)

    result = await polite_fetch(
        task.url, policy, rules, limiter, QUEUED, admitted, by_adapter=by_adapter, tries=task.attempts
    )
    match result:
        case Later(wait=wait):
            return Postpone(wait)
        case Refused(reason=reason) if reason == ROBOTS_UNREACHABLE:
            return Failed(reason, transient=True, exhausted="blocked")
        case Refused(reason=reason):
            return Finished("blocked", reason=reason)
    return result if result.block_class == "ok" else _backed_off(result, task)


def _backed_off(result: FetchResult, task: ClaimedTask) -> FetchResult | TaskResult:
    """A fetch that kept no `ok` page: the result, or, after a 429 or 503 to any of its requests, the task retried
    after the back-off of its try (`politeness.backoff`), or `blocked` when the server asks for longer than the longest
    backoff (the polite fetch paused the host) or a 429 came on the retry (`_TOO_MANY_TRIES`)."""
    slowed = slowed_down(result.attempts)
    if slowed is None:
        return result
    error = f"http {slowed.status}"
    after = backoff(slowed, task.attempts)
    if after is None or (slowed.status == HTTPStatus.TOO_MANY_REQUESTS and task.attempts >= _TOO_MANY_TRIES):
        return Finished("blocked", reason=error)
    return Failed(error, transient=True, after=after, exhausted="blocked")


async def _stored_page(
    engine: AsyncEngine,
    fetching: Fetching,
    task: ClaimedTask,
    site: SiteRow,
    policy: FetchPolicy,
    formats: Sequence[PageFormat],
    *,
    api: bool,
) -> Fetched | Ended:
    """The task's page from the latest stored capture made with `policy`'s steps and context (`cache: only`, D-1435),
    an API recipe's too with `api` (`recent_capture`), with no fetch; without one the task fails `not_cached`."""
    async with engine.connect() as conn:
        row = await recent_capture(conn, site.id, task.canonical_url, policy, max_age=None, api=api)
    recent = None if row is None else await reread(fetching.store, row, formats)
    if recent is None:
        return Ended(Failed(NOT_CACHED, transient=False))
    return Fetched(site, recent.result, recent.capture_id, (), policy.proxy_pool)


async def store_further_pages(
    conn: AsyncConnection,
    engine: AsyncEngine,
    store: ObjectStore,
    task: ClaimedTask,
    page: FetchedPage,
    records: Records,
    *,
    caller_supplied: bool,
    llm: LLMClient,
    result: Finished,
) -> Finished:
    """Extract and store a listing recipe's further pages under the task, with what the job pinned: the first page's
    `result`, `partial` when a further page's extraction failed, as a scrape's is."""
    if not page.further:
        return result
    extracted = await extract_further(page.further, records.schema, records.config, records.data, _role_c(task, llm))
    stored = await store_further(
        conn,
        engine,
        store,
        task,
        page.site.id,
        records.schema,
        extracted,
        records.margins,
        caller_supplied=caller_supplied,
    )
    return replace(result, outcome="partial") if stored.failed else result


async def count_fetch(conn: AsyncConnection, task: ClaimedTask, page: FetchedPage | Ended) -> None:
    """Count the task's fetch attempts as the job's usage. A handler counts them at the task's end, as its last write
    but the frontier's: the job's row stays locked from this write until the task commits, and role C's client, which
    updates the job's usage on a connection of its own, would wait on it (D-0346), as would a cancel."""
    await record_fetch_usage(conn, task.job_id, page.attempts, page.proxy_pool)


def unreached(page: FetchedPage, task: ClaimedTask) -> TaskResult | None:
    """The result of a page that was not reached: its outcome (`blocked`, `shell`, `not_found`), or a transient
    failure for a fetch error (D-0632); None for a reached page. A page a vendor's challenge kept out ends `blocked`
    naming the vendor (`blocked_reason`), after at most one retry, once the back-off of its first try is over, and with
    none when the browser rung met that vendor's challenge itself."""
    capture_id = page.capture_id
    failure = fetch_failure(page.result)
    if failure is not None:
        return Failed(
            page.result.attempts[-1].error or failure, transient=True, exhausted=failure, capture_id=capture_id
        )
    outcome = reached_outcome(page.result)
    if outcome == "extracted":
        return None
    reason = blocked_reason(page.result)
    if reason is not None and task.attempts < _VENDOR_TRIES and not _browser_met(page.result):
        return Failed(
            reason, transient=True, after=backoff_delay(task.attempts), exhausted="blocked", capture_id=capture_id
        )
    return Finished(outcome, reason=reason, capture_id=capture_id)


def _browser_met(result: FetchResult) -> bool:
    """Whether a browser attempt of the fetch met the challenge of the vendor that kept the page out."""
    vendor = vendor_block(result)
    return any(a.method == "browser" and a.challenge == vendor for a in result.attempts)


async def extract_records(
    conn: AsyncConnection,
    engine: AsyncEngine,
    task: ClaimedTask,
    page: FetchedPage,
    records: Records,
    *,
    caller_supplied: bool,
    llm: LLMClient,
    parsed: ParsedPage | None = None,
) -> TaskResult:
    """Extract the reached page with what the job pinned and store it (`store_page_record`): `config` mode with the
    pinned config, else cold. Role C on `llm`, charged to the job, fills required fields left missing (extraction spec).
    `parsed` is the page's parse when the handler already has one (INV-26). A crawl-discovered page may end
    `no_match`. A listing without rows ends with the reason (`ExtractionResult.reason`)."""
    schema = records.schema
    parsed = page.parsed if parsed is None else parsed
    config = None
    if records.config is not None:
        config = records.config.for_capture(page.result.bundle.manifest, records.data.adapters)
    executor = None if config is None else config.executor
    bundle, gap_fill = page.result.bundle, _role_c(task, llm)
    extraction = await extract_page(bundle, schema, executor, gap_fill, data=records.data, parsed=parsed)
    stored = await store_page_record(
        conn,
        engine,
        task,
        extraction,
        capture_id=page.capture_id,
        site_id=page.site.id,
        schema=schema,
        config=config,
        margins=records.margins,
        caller_supplied=caller_supplied,
        render=records.render,
    )
    if stored.outcome == "failed":
        return Failed(EXTRACTION_ERROR, transient=False, capture_id=page.capture_id)
    # A listing without rows says why in the task's `last_error` (D-1475).
    return Finished(stored.outcome, reason=extraction.reason, capture_id=page.capture_id)


def _role_c(task: ClaimedTask, llm: LLMClient) -> RoleC:
    """Role C on `llm`, charged to the task's job."""
    return role_c(llm, job_id=task.job_id)
