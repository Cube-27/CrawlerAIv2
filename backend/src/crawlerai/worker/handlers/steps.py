"""What the handlers of page tasks (`batch_scrape`, `extract`, `crawl`) do the same way before the page's run
(`page_run`): the task's job, and the records the task extracts with as the job pinned them (INV-28); fetching
its page politely, or reading its stored capture (`fetch.cache`, as a scrape does); and counting its fetches as the
job's usage.

A listing whose records the job reads, on a site whose pinned config has a listing recipe (one with pagination,
Appendix A #59), is served by the recipe page after page (`RecipeRung.pages`) up to the job's page bound
(`listing_pages`); the first page is the task's capture and record, and each further page is stored under the task as a
listing's further kept state is (`store_further`). When the recipe does not serve the first page, the page
is fetched by the rungs as any page is.

The task's page is fetched before the worker's transaction for the task opens (`fetch_page`): the site's row, its
robots.txt, its adapter declines and what the fetch taught its memory (`acquire.memory`) are each read or written in a
short transaction of their own, so no task holds a site's rows while it fetches or extracts, and the tasks of one site
run side by side. The page's run (`page_run`: its capture, extraction and records) writes in the worker's transaction
for the task, so a task that raises rolls back alone (INV-31); site memory only is learned beside it. The task's fetch
attempts are counted as the job's usage at its end (`count_fetch`): that write locks the job's row until the task
commits.
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

from crawlerai.acquire.memory import learn_fetch
from crawlerai.acquire.politeness import Admit, HostLimiter, backoff, slowed_down
from crawlerai.acquire.rungs import NO_PLAN
from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.config_ir.active import config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.models import Job, SchemaId
from crawlerai.db.queue import LEASE, TASK_DEADLINE, ClaimedTask, Failed, Finished
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.types import Probability
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.batch import JobPins
from crawlerai.services.fetch_options import FetchOptions, fetch_policy
from crawlerai.services.fetching import (
    Fetching,
    PagePlan,
    RecipePages,
    page_fetch,
    refusal,
    site_rungs,
    store_declines,
)
from crawlerai.services.page_run import Page, Records, read_stored
from crawlerai.services.page_store import record_fetch_usage, site_row, surface_plan
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
from crawlerai.services.scrape_request import PageFormat, RenderOptions
from crawlerai.services.stored_captures import NOT_CACHED, NotCached
from crawlerai.worker.loop import Postpone, TaskResult

log = logging.getLogger(__name__)

# A listing recipe's page requests start within this share of the task's lease (`LEASE`): each waits in place for its
# turn at most `QUEUED.bound` (half the lease), so the last one ends inside the lease, its timeout and the extraction
# after it included, and no other worker claims the task and sends its requests again.
RECIPE_PAGES_SHARE: Final = LEASE / 4
# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"
# A page a 429 kept out (RFC 6585 §4) is fetched at most this many times: one retry after the back-off, from the
# pool's next address, then `blocked`.
_TOO_MANY_TRIES: Final = 2

# The request's `min_confidence`, as the job row stores it.
_MIN_CONFIDENCE: Final = TypeAdapter(Probability)
_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


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
) -> Page | Ended:
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
        vocabulary=None if read_with is None else read_with.data.vocabulary,
        formats=formats,
    )
    # A new host's site row is committed at once, so the other tasks of the host do not wait on it.
    async with engine.begin() as conn:
        site = await site_row(conn, host, task.page_kind)
    # A page the config's API recipe serves was stored as its JSON, as a scrape reads it. A job has no `max_age`.
    api = served is not None and served.config is not None and recipe_of(served.config) is not None
    try:
        stored = await read_stored(
            engine,
            fetching.store,
            (site, task.canonical_url),
            policy,
            options.cache,
            max_age=0,
            formats=formats,
            api=api,
        )
    except NotCached:
        return Ended(Failed(NOT_CACHED, transient=False))
    if stored is not None:
        return stored
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


async def _learned(engine: AsyncEngine, plan: PagePlan, fetched: FetchResult | TaskResult) -> Page | Ended:
    """The fetched page, with what its fetch taught remembered on its site (`acquire.memory.learn_fetch`), or how the
    task ends: a refused request, a listing recipe's further page's too, fails it (INV-16)."""
    site, attempts, pool = plan.site, tuple(plan.attempts), plan.policy.proxy_pool
    if isinstance(fetched, FetchResult):
        further_refused = None if plan.pages is None else plan.pages.refused
        if (refused := refusal(fetched) or further_refused) is None:
            await learn_fetch(engine, site.id, fetched)
            further = () if plan.pages is None else tuple(plan.pages.further)
            return Page(site, fetched, attempts, pool, further)
        fetched = Failed(refused, transient=False)
    return Ended(fetched, attempts, pool)


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


async def count_fetch(conn: AsyncConnection, task: ClaimedTask, page: Page | Ended) -> None:
    """Count the task's fetch attempts as the job's usage. A handler counts them at the task's end, as its last write
    but the frontier's: the job's row stays locked from this write until the task commits, and role C's client, which
    updates the job's usage on a connection of its own, would wait on it (D-0346), as would a cancel."""
    await record_fetch_usage(conn, task.job_id, page.attempts, page.proxy_pool)
