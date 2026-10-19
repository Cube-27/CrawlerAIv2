"""What the handlers of page tasks (`batch_scrape`, `crawl`) do the same way: the task's job, and the records the task
extracts with as the job pinned them (INV-28); fetching its page politely and storing the capture; the result a page
that was not reached ends with; and extracting and storing a reached page's record.

A listing whose records the job reads, on a site whose pinned config has a listing recipe (one with pagination,
Appendix A #59), is served by the recipe page after page (`RecipeRung.pages`) up to the job's page bound
(`listing_pages`); the first page is the task's capture and record, and each further page is stored under the task as a
listing's further kept state is (`store_further`). When the recipe does not serve the first page, the page
is fetched by the rungs as any page is.

Every step writes in the worker's transaction for the task, so a task that raises rolls back alone (INV-31). The
task's fetch attempts are counted as the job's usage at its end (`count_fetch`): that write locks the job's row until
the task commits.
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import urlsplit

from pydantic import TypeAdapter
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import HostLimiter, backoff, slowed_down
from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.config_ir.active import config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.core.retry import backoff_delay
from crawlerai.db.models import CaptureId, Job, RecordId, SchemaId, SiteId
from crawlerai.db.queue import LEASE, TASK_DEADLINE, ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.recurring.conditional import Unchanged
from crawlerai.recurring.state import record_fetch, standing_listing, standing_record, stored_validators
from crawlerai.recurring.versions import link_records
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.task import ActiveConfig
from crawlerai.resolve.types import Probability
from crawlerai.schemas.types import SchemaDef
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
    Later,
    PageFetch,
    ReadRules,
    Refused,
    Turns,
    polite_fetch,
    rules_in,
)
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    EXTRACTION_ERROR,
    FetchOptions,
    PageFormat,
    RenderNeed,
    SiteRow,
    blocked_reason,
    extract_further,
    fetch_policy,
    new_capture,
    parsed_page,
    record_fetch_usage,
    render_need,
    site_row,
    store_further,
    store_page_record,
)
from crawlerai.services.stored_captures import NOT_CACHED, recent_capture, reread
from crawlerai.storage.base import ObjectStore
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskResult

# A listing recipe's page requests start within this share of the task's lease (`LEASE`): each waits in place for its
# turn at most `QUEUED.bound` (half the lease), so the last one ends inside the lease, its timeout and the extraction
# after it included, and no other worker claims the task and sends its requests again.
RECIPE_PAGES_SHARE: Final = LEASE / 4
# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"
# A page a vendor's challenge kept out is fetched at most this many times (master plan 2026-10-18 §3.1).
_VENDOR_TRIES: Final = 2

# The request's `min_confidence`, as the job row stores it.
_MIN_CONFIDENCE: Final = TypeAdapter(Probability)
# The request's `render_fields`, as the job row stores them (absent from a job a schedule or a learning run submitted).
_RENDER_FIELDS: Final = TypeAdapter(tuple[str, ...])
_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


@dataclass(frozen=True)
class Records:
    """What a records task extracts with: the job's schema, the engine data and the config for the task's host its
    pins give, the config bound to its executor (None: cold), and the drift margins of this worker."""

    schema: SchemaDef
    data: EngineData
    config: ActiveConfig | None
    margins: DriftMargins | None
    render_fields: tuple[str, ...] = ()  # the request's (`RenderNeed`)


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
    render_fields = _RENDER_FIELDS.validate_python(job.request.get("render_fields", []))
    return job.request, Records(pins.schema_, pinned, config, margins, render_fields)


@dataclass(frozen=True)
class FetchedPage:
    """The task's page as fetched, its site, its stored capture, the record that stands for it while it is unchanged
    (`fetch_page`'s `recurring`), and the fetch attempts, which `count_fetch` counts as the job's usage."""

    site: SiteRow
    result: FetchResult
    capture_id: CaptureId
    standing: tuple[RecordId, ...]
    attempts: tuple[AttemptRecord, ...]
    proxy_pool: str | None
    check: RenderNeed | None = None
    further: tuple[FetchResult, ...] = ()  # a listing recipe's further pages, in order

    @property
    def parsed(self) -> ParsedPage:
        """The page's one parse (INV-26): the one its fetch's content check read, when it read this capture."""
        return parsed_page(self.result.bundle, self.check)


@dataclass(frozen=True)
class Ended:
    """A task that ends this run without a page to extract, with what it ends with, and the fetch attempts it made,
    which `count_fetch` counts as the job's usage."""

    task_result: TaskResult
    attempts: tuple[AttemptRecord, ...] = ()
    proxy_pool: str | None = None


async def fetch_page(
    conn: AsyncConnection,
    fetching: Fetching,
    task: ClaimedTask,
    options: FetchOptions,
    locale: str | None,
    *,
    recurring: Records | None = None,
    served: Records | None = None,
    llm: LLMClient,
    listing_pages: int = MAX_PAGES,
    formats: Sequence[PageFormat] = (),
) -> FetchedPage | Ended:
    """Fetch the task's page politely (`fetch_queued`: robots.txt over HTTP, the page through `acquire`) and store
    its capture, or the result the task ends this run with. Neither writes the job's usage. A request the SSRF
    guard refused fails the task at once (INV-16): the task's URL is checked before anything, as the services that
    fetch while the caller waits check theirs (`check_target`), since a crawl's URLs were never checked at submit.

    With `recurring`, the records the task extracts with, a page records already stand for (`_standing`) is
    fetched with the validators it last answered with, and a 304 ends the task `unchanged` with no capture (jobs spec
    §4.2).

    With `served`, the records the task extracts with when they are all it reads of the page, the config they name
    serves the page through its API recipe when it has one (adapters spec, `recipe_rung`), and an HTTP page that lacks
    the offer data or the items their schema reads is rendered once more (`RenderNeed`, owner #49, #54). A listing's
    recipe with pagination serves up to
    `listing_pages` pages of it (module docstring).

    `formats` are those the task's page is read for: a screenshot or PDF among them is made in the browser
    (`fetch_policy`)."""
    try:
        await fetching.connector.check(task.url)
    except SsrfRejected as e:
        return Ended(Failed(str(e), transient=False))
    host = urlsplit(task.url).hostname or ""
    site = await site_row(conn, host, task.page_kind)
    rungs = site_rungs(fetching, host, site)
    all_resources = site.load_all_resources
    policy = fetch_policy(
        options, locale, site.proxy_pool, page_kind=task.page_kind, formats=formats, all_resources=all_resources
    )
    if options.cache == "only":
        # A page the config's API recipe serves was stored as its JSON, as a scrape reads it.
        api = served is not None and served.config is not None and recipe_of(served.config) is not None
        return await _stored_page(conn, fetching, task, site, policy, formats, api=api)
    standing = () if recurring is None else await _standing(conn, task, site.id, recurring)
    # Validators go only where a record stands for a 304; without one, a 304 is fetched again whole (§4.6). A fetch
    # that bypasses what is stored sends none (D-1435).
    sends_validators = bool(standing) and options.cache != "bypass"
    validators = await stored_validators(conn, site.id, task.canonical_url) if sends_validators else None
    # The task's deadline runs from its claim, a moment before this (`worker.loop`).
    deadline = time.monotonic() + TASK_DEADLINE.total_seconds()
    plain = PagePlan(rungs, site, policy, [], validators=validators, has_record=bool(standing), deadline=deadline)
    plan = _plan(task, served, llm, listing_pages, plain)
    rules = rules_in(conn, fetching.rungs.http, plan.attempts, Turns(fetching.limiter, QUEUED))
    fetch = page_fetch(fetching, plan, rules, QUEUED)
    by_adapter = rungs.adapters.would_serve(task.url)
    fetched = await fetch_queued(task, policy, rules, fetch, fetching.limiter, by_adapter=by_adapter)
    await store_declines(conn, site, host, rungs)
    return await _kept(conn, fetching, task, plan, fetched, standing)


def _plan(task: ClaimedTask, served: Records | None, llm: LLMClient, listing_pages: int, plan: PagePlan) -> PagePlan:
    """`plan` with what `served` adds: the config's API recipe (serving a listing in pages when it has pagination) and
    the check that renders an HTTP page lacking what the records read, with role C charged to the task's job."""
    if served is None:
        return plan
    recipe = None if served.config is None else recipe_of(served.config)
    lists = served.schema.page_kind == "listing" and recipe is not None and recipe.pagination is not None
    check = render_need(served.schema, served.data, served.render_fields)
    deadline = time.monotonic() + RECIPE_PAGES_SHARE.total_seconds()
    pages = RecipePages(listing_pages, plan.attempts, deadline=deadline) if lists else None
    return replace(plan, recipe=recipe, pages=pages, needs_render=check)


async def _kept(
    conn: AsyncConnection,
    fetching: Fetching,
    task: ClaimedTask,
    plan: PagePlan,
    fetched: FetchResult | Unchanged | TaskResult,
    standing: tuple[RecordId, ...],
) -> FetchedPage | Ended:
    """The fetched page with its capture stored, or how the task ends: a refused request, a listing recipe's further
    page's too, fails it (INV-16), and a 304 that a record stands for ends it `unchanged`, linked to those records."""
    site, attempts, pool = plan.site, tuple(plan.attempts), plan.policy.proxy_pool
    if isinstance(fetched, FetchResult):
        further_refused = None if plan.pages is None else plan.pages.refused
        if (refused := refusal(fetched) or further_refused) is None:
            check = plan.needs_render if isinstance(plan.needs_render, RenderNeed) else None
            capture_id = await new_capture(conn, fetching.store, site.id, fetched, check)
            further = () if plan.pages is None else tuple(plan.pages.further)
            return FetchedPage(site, fetched, capture_id, standing, attempts, pool, check, further)
        fetched = Failed(refused, transient=False)
    if isinstance(fetched, Unchanged):
        await record_fetch(conn, site.id, task.canonical_url, fetched)
        # The task stands for the records that stood for the 304 (`fetch_unless_unchanged` takes none without one).
        await link_records(conn, task.id, standing)
        fetched = Finished("unchanged")
    return Ended(fetched, attempts, pool)


async def fetch_queued(
    task: ClaimedTask,
    policy: FetchPolicy,
    rules: ReadRules,
    fetch: PageFetch,
    limiter: HostLimiter,
    *,
    by_adapter: bool = False,
) -> FetchResult | Unchanged | TaskResult:
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
      attempts run out, and at once when the server asks for more than the longest backoff."""
    result = await polite_fetch(
        task.url, policy, rules, limiter, QUEUED, fetch, by_adapter=by_adapter, tries=task.attempts
    )
    match result:
        case Later(wait=wait):
            return Postpone(wait)
        case Refused(reason=reason) if reason == ROBOTS_UNREACHABLE:
            return Failed(reason, transient=True, exhausted="blocked")
        case Refused(reason=reason):
            return Finished("blocked", reason=reason)
        case Unchanged():
            return result
    return result if result.block_class == "ok" else _backed_off(result, task)


def _backed_off(result: FetchResult, task: ClaimedTask) -> FetchResult | TaskResult:
    """A fetch that kept no `ok` page: the result, or, after a 429 or 503 to any of its requests, the task retried
    after the back-off of its try (`politeness.backoff`), or `blocked` when the server asks for longer than the longest
    backoff (the polite fetch paused the host)."""
    slowed = slowed_down(result.attempts)
    if slowed is None:
        return result
    error = f"http {slowed.status}"
    after = backoff(slowed, task.attempts)
    if after is None:
        return Finished("blocked", reason=error)
    return Failed(error, transient=True, after=after, exhausted="blocked")


async def _stored_page(
    conn: AsyncConnection,
    fetching: Fetching,
    task: ClaimedTask,
    site: SiteRow,
    policy: FetchPolicy,
    formats: Sequence[PageFormat],
    *,
    api: bool,
) -> FetchedPage | Ended:
    """The task's page from the latest stored capture made with `policy`'s steps and context (`cache: only`, D-1435),
    an API recipe's too with `api` (`recent_capture`), with no fetch; without one the task fails `not_cached`."""
    row = await recent_capture(conn, site.id, task.canonical_url, policy, max_age=None, api=api)
    recent = None if row is None else await reread(fetching.store, row, formats)
    if recent is None:
        return Ended(Failed(NOT_CACHED, transient=False))
    return FetchedPage(site, recent.result, recent.capture_id, (), (), policy.proxy_pool)


async def store_further_pages(
    conn: AsyncConnection,
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


async def _standing(
    conn: AsyncConnection, task: ClaimedTask, site_id: SiteId, records: Records
) -> tuple[RecordId, ...]:
    """The records that stand for the page while it is unchanged, for the config the job pinned (None: `adhoc`): a
    listing's (`standing_listing`), or its detail page's one (`standing_record`). None stand for a job with a
    `min_confidence`: the minimum changes which values a record holds, so another job's record is not its answer."""
    if records.data.min_confidence is not None:
        return ()
    version = None if records.config is None else records.config.version
    if records.schema.page_kind == "listing":
        return await standing_listing(conn, site_id, task.canonical_url, records.schema, version)
    record = await standing_record(conn, site_id, task.canonical_url, records.schema, version)
    return () if record is None else (record,)


def unreached(page: FetchedPage, task: ClaimedTask) -> TaskResult | None:
    """The result of a page that was not reached: its outcome (`blocked`, `shell`, `not_found`), or a transient
    failure for a fetch error (D-0632); None for a reached page. A page a vendor's challenge kept out ends `blocked`
    naming the vendor (`blocked_reason`), after at most one retry, once the back-off of its first try is over."""
    outcome = BLOCK_OUTCOMES[page.result.block_class]
    capture_id = page.capture_id
    if outcome == "failed":
        return Failed(page.result.attempts[-1].error or outcome, transient=True, capture_id=capture_id)
    if outcome == "extracted":
        return None
    reason = blocked_reason(page.result)
    if reason is not None and task.attempts < _VENDOR_TRIES:
        return Failed(
            reason, transient=True, after=backoff_delay(task.attempts), exhausted="blocked", capture_id=capture_id
        )
    return Finished(outcome, reason=reason, capture_id=capture_id)


async def extract_records(
    conn: AsyncConnection,
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
    config = None
    if records.config is not None:
        config = records.config.for_capture(page.result.bundle.manifest, records.data.adapters)
    executor = None if config is None else config.executor
    bundle, gap_fill = page.result.bundle, _role_c(task, llm)
    extraction = await extract_page(bundle, schema, executor, gap_fill, data=records.data, parsed=parsed)
    stored = await store_page_record(
        conn,
        task,
        extraction,
        capture_id=page.capture_id,
        site_id=page.site.id,
        schema=schema,
        config=config,
        margins=records.margins,
        caller_supplied=caller_supplied,
    )
    if stored.outcome == "failed":
        return Failed(EXTRACTION_ERROR, transient=False, capture_id=page.capture_id)
    # A listing without rows says why in the task's `last_error` (D-1475).
    return Finished(stored.outcome, reason=extraction.reason, capture_id=page.capture_id)


def _role_c(task: ClaimedTask, llm: LLMClient) -> RoleC:
    """Role C on `llm`, charged to the task's job."""
    return role_c(llm, job_id=task.job_id)
