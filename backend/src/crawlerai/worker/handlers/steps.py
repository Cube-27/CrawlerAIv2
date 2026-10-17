"""What the handlers of page tasks (`batch_scrape`, `crawl`) do the same way: the task's job, and the records the task
extracts with as the job pinned them (INV-28); fetching its page politely and storing the capture; the result a page
that was not reached ends with; and extracting and storing a reached page's record.

A listing whose records the job reads, on a site whose pinned config has a listing recipe (one with pagination,
Appendix A #59), is served by the recipe page after page (`RecipeRung.pages`) up to the job's page bound
(`listing_pages`); the first page is the task's capture and record, and each further page is stored under the task as a
listing's further kept state is (`scrape_steps.store_further`). When the recipe does not serve the first page, the page
is fetched by the rungs as any page is.

Every step writes in the worker's transaction for the task, so a task that raises rolls back alone (INV-31). The
task's fetch attempts are counted as the job's usage at its end (`count_fetch`): that write locks the job's row until
the task commits.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import Admit
from crawlerai.acquire.robots import Fetch
from crawlerai.acquire.rungs import acquire
from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult, Validators
from crawlerai.config_ir.active import config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES, RecipeRung
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import CaptureId, Job, RecordId, SchemaId, SiteId
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.recurring.conditional import Unchanged, fetch_unless_unchanged
from crawlerai.recurring.state import record_fetch, standing_listing, standing_record, stored_validators
from crawlerai.recurring.versions import link_records
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.task import ActiveConfig
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.batch import JobPins
from crawlerai.services.fetching import (
    Fetching,
    adapter_send,
    endpoint_rules,
    page_host_first,
    recipe_rung,
    recording,
    refusal,
    site_rungs,
    store_declines,
)
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    EXTRACTION_ERROR,
    ContentCheck,
    FetchOptions,
    SiteRow,
    checked_extraction,
    content_check,
    extract_further,
    fetch_policy,
    new_capture,
    parsed_page,
    record_fetch_usage,
    site_row,
    store_further,
    store_page_record,
)
from crawlerai.storage.base import ObjectStore
from crawlerai.worker.loop import Failed, Finished, TaskResult
from crawlerai.worker.polite import HostRules, fetch_politely

# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"

_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


@dataclass(frozen=True)
class Records:
    """What a records task extracts with: the job's schema, the engine data and the config for the task's host its
    pins give, the config bound to its executor (None: cold), and the drift margins of this worker."""

    schema: SchemaDef
    data: EngineData
    config: ActiveConfig | None
    margins: DriftMargins | None


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
    pinned = data.pinned(pins.engine_data)
    config_id = pins.configs.get(urlsplit(task.url).hostname or "")
    config = None if config_id is None else await config_by_id(conn, config_id, pinned.vocabulary)
    return job.request, Records(pins.schema_, pinned, config, margins)


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
    check: ContentCheck | None = None
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
) -> FetchedPage | Ended:
    """Fetch the task's page politely (`fetch_politely`: robots.txt over HTTP, the page through `acquire`) and store
    its capture, or the result the task ends this run with. Neither writes the job's usage. A request the SSRF
    guard refused fails the task at once (INV-16): the task's URL is checked before anything, as the services that
    fetch while the caller waits check theirs (`check_target`), since a crawl's URLs were never checked at submit.

    With `recurring`, the records the task extracts with, a page records already stand for (`_standing`) is
    fetched with the validators it last answered with, and a 304 ends the task `unchanged` with no capture (SPEC-11
    §4.2).

    With `served`, the records the task extracts with when they are all it reads of the page, the config they name
    serves the page through its API recipe when it has one (SPEC-09 §4.8, `recipe_rung`), and an HTTP page that lacks
    the offer data or the rows their schema reads is rendered once more (`ContentCheck`, owner #49, #54), with role C
    on `llm`, charged to the task's job. A listing's recipe with pagination serves up to
    `listing_pages` pages of it (module docstring)."""
    try:
        await fetching.connector.check(task.url)
    except SsrfRejected as e:
        return Ended(Failed(str(e), transient=False))
    host = urlsplit(task.url).hostname or ""
    site = await site_row(conn, host, task.page_kind)
    rungs = site_rungs(fetching, host, site)
    policy = fetch_policy(options, locale, site.proxy_pool, page_kind=task.page_kind)
    standing = () if recurring is None else await _standing(conn, task, site.id, recurring)
    # Validators go only where a record stands for a 304; without one, a 304 is fetched again whole (§4.6).
    validators = await stored_validators(conn, site.id, task.canonical_url) if standing else None
    attempts: list[AttemptRecord] = []
    robots = recording(fetching.rungs.http, policy, attempts)
    recipe = await _recipe(conn, fetching, task, served, robots)
    check = None if served is None else content_check(served.schema, served.data, served.config, _role_c(task, llm))
    paged = recipe if served is not None and served.schema.page_kind == "listing" else None
    further: list[FetchResult] = []

    async def page(url: str, admit_next: Admit, known: HostRules) -> FetchResult | Unchanged:
        # An adapter's endpoint goes by its host's robots.txt, read in the task's transaction (SPEC-15 §4.6); the
        # page's own host by the rules already read for the page (D-1384).
        rules = page_host_first(host, known, partial(endpoint_rules, conn, fetch_robots=robots))
        send = adapter_send(fetching, host, rules)

        async def fetch(sent: Validators | None) -> FetchResult:
            pages = await _recipe_pages(paged, url, policy, listing_pages, admit_next)
            attempts.extend(attempt for served_page in pages for attempt in served_page.attempts)
            if pages:
                further[:] = _until_refused(pages[1:])
                return pages[0]
            result = await acquire(
                url,
                policy,
                site.fetch_method,
                rungs,
                recipe=recipe,
                validators=sent,
                admit_next=admit_next,
                send=send,
                needs_render=check,
            )
            attempts.extend(result.attempts)
            return result

        return await fetch_unless_unchanged(fetch, validators, has_record=bool(standing))

    by_adapter = rungs.adapters.would_serve(task.url)
    fetched = await fetch_politely(
        conn, task, site.id, policy, page, fetching.limiter, fetch_robots=robots, by_adapter=by_adapter
    )
    await store_declines(conn, site, host, rungs)
    if isinstance(fetched, FetchResult):
        if (refused := refusal(fetched)) is None:
            capture_id = await new_capture(conn, fetching.store, site.id, fetched)
            pages = tuple(further)
            return FetchedPage(site, fetched, capture_id, standing, tuple(attempts), policy.proxy_pool, check, pages)
        fetched = Failed(refused, transient=False)
    if isinstance(fetched, Unchanged):
        await record_fetch(conn, site.id, task.canonical_url, fetched)
        # The task stands for the records that stood for the 304 (`fetch_unless_unchanged` takes none without one).
        await link_records(conn, task.id, standing)
        fetched = Finished("unchanged")
    return Ended(fetched, tuple(attempts), policy.proxy_pool)


async def _recipe(
    conn: AsyncConnection, fetching: Fetching, task: ClaimedTask, served: Records | None, robots: Fetch
) -> RecipeRung | None:
    """The API recipe of the config `served` names, bound to fetch the task's page; robots.txt of its endpoint is
    fetched with `robots`, and read in the task's transaction."""
    recipe = None if served is None or served.config is None else recipe_of(served.config)
    if recipe is None:
        return None
    host = urlsplit(task.url).hostname or ""
    return recipe_rung(fetching, recipe, host, lambda url, policy: endpoint_rules(conn, url, policy, robots))


async def _recipe_pages(
    recipe: RecipeRung | None, url: str, policy: FetchPolicy, limit: int, admit_next: Admit
) -> list[FetchResult]:
    """The listing's pages as `recipe` serves them when it has pagination, up to `limit` requests; none when it
    served no first page (or has no pagination), after waiting for the turn of the request that follows. Each page
    request waits for its host's rate on its own (`recipe_rung`)."""
    if recipe is None or recipe.recipe.pagination is None:
        return []
    pages = [page async for page in recipe.pages(url, policy, records=None, limit=limit)]
    if pages and pages[0].block_class == "ok":
        return pages
    await admit_next()
    return []


def _until_refused(pages: Sequence[FetchResult]) -> list[FetchResult]:
    """The pages before the first one the SSRF guard refused a request of (INV-16): a refused page is never stored."""
    kept: list[FetchResult] = []
    for page in pages:
        if refusal(page) is not None:
            break
        kept.append(page)
    return kept


async def store_further_pages(
    conn: AsyncConnection,
    store: ObjectStore,
    task: ClaimedTask,
    page: FetchedPage,
    records: Records,
    *,
    caller_supplied: bool,
    llm: LLMClient | None,
) -> None:
    """Extract and store a listing recipe's further pages under the task, with what the job pinned."""
    if not page.further:
        return
    extracted = await extract_further(page.further, records.schema, records.config, records.data, _role_c(task, llm))
    await store_further(
        conn,
        store,
        task,
        page.site.id,
        records.schema,
        extracted,
        records.margins,
        caller_supplied=caller_supplied,
    )


async def count_fetch(conn: AsyncConnection, task: ClaimedTask, page: FetchedPage | Ended) -> None:
    """Count the task's fetch attempts as the job's usage. A handler counts them at the task's end, as its last write
    but the frontier's: the job's row stays locked from this write until the task commits, and role C's client, which
    updates the job's usage on a connection of its own, would wait on it (D-0346), as would a cancel."""
    await record_fetch_usage(conn, task.job_id, page.attempts, page.proxy_pool)


async def _standing(
    conn: AsyncConnection, task: ClaimedTask, site_id: SiteId, records: Records
) -> tuple[RecordId, ...]:
    """The records that stand for the page while it is unchanged, for the config the job pinned (None: `adhoc`): a
    listing's (`standing_listing`), or its detail page's one (`standing_record`)."""
    version = None if records.config is None else records.config.version
    if records.schema.page_kind == "listing":
        return await standing_listing(conn, site_id, task.canonical_url, records.schema, version)
    record = await standing_record(conn, site_id, task.canonical_url, records.schema, version)
    return () if record is None else (record,)


def unreached(page: FetchedPage) -> TaskResult | None:
    """The result of a page that was not reached: its outcome (`blocked`, `shell`, `not_found`), or a transient
    failure for a fetch error (D-0632); None for a reached page."""
    outcome = BLOCK_OUTCOMES[page.result.block_class]
    if outcome == "failed":
        return Failed(page.result.attempts[-1].error or outcome, transient=True, capture_id=page.capture_id)
    return None if outcome == "extracted" else Finished(outcome, capture_id=page.capture_id)


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
    pinned config, else cold. Role C on `llm`, charged to the job, fills required fields left missing (SPEC-05 §4.13).
    `parsed` is the page's parse when the handler already has one (INV-26); a listing its fetch's
    check extracted is not extracted again (owner #54). A crawl-discovered page may end `no_match`."""
    schema = records.schema
    config = None
    if records.config is not None:
        config = records.config.for_capture(page.result.bundle.manifest, records.data.adapters)
    executor = None if config is None else config.executor
    extraction = checked_extraction(page.result.bundle, page.check)
    if extraction is None:
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
    return Finished(stored.outcome, capture_id=page.capture_id)


def _role_c(task: ClaimedTask, llm: LLMClient) -> RoleC:
    """Role C on `llm`, charged to the task's job."""
    return role_c(llm, job_id=task.job_id)
