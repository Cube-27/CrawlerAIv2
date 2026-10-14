"""What the handlers of page tasks (`batch_scrape`, `crawl`) do the same way: the task's job, and the records the task
extracts with as the job pinned them (INV-28); fetching its page politely and storing the capture; the result a page
that was not reached ends with; and extracting and storing a reached page's record.

Every step writes in the worker's transaction for the task, so a task that raises rolls back alone (INV-31). The fetch
of a reached page is counted as the job's usage after its extraction (`count_fetch`, D-0346).
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.rungs import acquire
from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.acquire.types import AttemptRecord, FetchResult, Validators
from crawlerai.config_ir.active import config_by_id
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import CaptureId, ExtractionConfig, ExtractionConfigId, Job, RecordId, SchemaId, SiteId
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.recurring.conditional import Unchanged, fetch_unless_unchanged
from crawlerai.recurring.state import record_fetch, standing_record, stored_validators
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.schemas.registry import get_by_id
from crawlerai.services.batch import JobPins
from crawlerai.services.fetching import Fetching, recording, refusal
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    EXTRACTION_ERROR,
    FetchOptions,
    SiteRow,
    fetch_policy,
    new_capture,
    record_fetch_usage,
    site_row,
    store_page_record,
)
from crawlerai.worker.loop import Failed, Finished, TaskResult
from crawlerai.worker.polite import fetch_politely

# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"

_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


@dataclass(frozen=True)
class Records:
    """What a records task extracts with: the job's schema version, the engine data its pins give, the config they
    name for the task's host (None: cold), and the drift margins of this worker."""

    schema_id: SchemaId
    data: EngineData
    config_id: ExtractionConfigId | None
    margins: DriftMargins | None


async def load_job(
    conn: AsyncConnection, task: ClaimedTask, data: EngineData | None, margins: DriftMargins | None
) -> tuple[dict[str, object], Records | None] | Failed:
    """The task's job request, and what the task extracts records with from the job's schema and pins (`JobPins`):
    None for a job without records. A records task fails in a worker without the engine's data (`data` None)."""
    job: _JobRow = (
        await conn.execute(select(Job.request, Job.schema_id, Job.pinned).where(Job.id == task.job_id))
    ).one()
    if job.schema_id is None:
        return job.request, None
    if data is None:
        return Failed(RECORDS_UNAVAILABLE, transient=False)
    pins = JobPins.model_validate(job.pinned)
    config_id = pins.configs.get(urlsplit(task.url).hostname or "")
    return job.request, Records(job.schema_id, data.pinned(pins.engine_data), config_id, margins)


@dataclass(frozen=True)
class FetchedPage:
    """The task's page as fetched, its site, its stored capture, the record that stands for it while it is unchanged
    (`fetch_page`'s `recurring`), and the fetch attempts, which `count_fetch` counts as the job's usage."""

    site: SiteRow
    result: FetchResult
    capture_id: CaptureId
    standing: RecordId | None
    attempts: tuple[AttemptRecord, ...]
    proxy_pool: str | None


async def fetch_page(
    conn: AsyncConnection,
    fetching: Fetching,
    task: ClaimedTask,
    options: FetchOptions,
    locale: str | None,
    *,
    recurring: Records | None = None,
) -> FetchedPage | TaskResult:
    """Fetch the task's page politely (`fetch_politely`: robots.txt over HTTP, the page through `acquire`) and store
    its capture, or the result the task ends this run with. The attempts count as the job's usage. A request the SSRF
    guard refused fails the task at once (INV-16): the task's URL is checked before anything, as the services that
    fetch while the caller waits check theirs (`check_target`), since a crawl's URLs were never checked at submit.

    With `recurring`, the records the task extracts with, a page a record already stands for (`standing_record`) is
    fetched with the validators it last answered with, and a 304 ends the task `unchanged` with no capture (SPEC-11
    §4.2)."""
    try:
        await fetching.connector.check(task.url)
    except SsrfRejected as e:
        return Failed(str(e), transient=False)
    site = await site_row(conn, urlsplit(task.url).hostname or "")
    policy = fetch_policy(options, locale, site.proxy_pool)
    standing = None if recurring is None else await _standing(conn, task, site.id, recurring)
    # Validators go only where a record stands for a 304; without one, a 304 is fetched again whole (§4.6).
    validators = None if standing is None else await stored_validators(conn, site.id, task.canonical_url)
    attempts: list[AttemptRecord] = []
    robots = recording(fetching.rungs.http, policy, attempts)

    async def page(url: str) -> FetchResult | Unchanged:
        async def fetch(sent: Validators | None) -> FetchResult:
            result = await acquire(url, policy, site.fetch_method, fetching.rungs, validators=sent)
            attempts.extend(result.attempts)
            return result

        return await fetch_unless_unchanged(fetch, validators, has_record=standing is not None)

    fetched = await fetch_politely(conn, task, site.id, policy, page, fetching.limiter, fetch_robots=robots)
    if isinstance(fetched, FetchResult):
        if (refused := refusal(fetched)) is None:
            capture_id = await new_capture(conn, fetching.store, site.id, fetched)
            return FetchedPage(site, fetched, capture_id, standing, tuple(attempts), policy.proxy_pool)
        fetched = Failed(refused, transient=False)
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    if isinstance(fetched, Unchanged):
        await record_fetch(conn, site.id, task.canonical_url, fetched)
        return Finished("unchanged")
    return fetched


async def count_fetch(conn: AsyncConnection, task: ClaimedTask, page: FetchedPage) -> None:
    """Count the page's fetch attempts as the job's usage. A handler counts them once it has extracted the page: role
    C's client updates the job's usage on a connection of its own, and would wait on this transaction's write to the
    job's row (D-0346)."""
    await record_fetch_usage(conn, task.job_id, page.attempts, page.proxy_pool)


async def _standing(conn: AsyncConnection, task: ClaimedTask, site_id: SiteId, records: Records) -> RecordId | None:
    """The record that stands for the page while it is unchanged (`standing_record`), for the config the job pinned
    (None: `adhoc`). Only the config's version is read here: the page may never be extracted."""
    version = None
    if records.config_id is not None:
        query = select(ExtractionConfig.version).where(ExtractionConfig.id == records.config_id)
        version = (await conn.execute(query)).scalar_one()
    return await standing_record(conn, site_id, task.canonical_url, records.schema_id, version)


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
    llm: LLMClient | None,
    parsed: ParsedPage | None = None,
) -> TaskResult:
    """Extract the reached page with what the job pinned and store it (`store_page_record`): `config` mode with the
    pinned config, else cold. Role C on `llm`, charged to the job, fills required fields left missing (SPEC-05 §4.13);
    None binds no role C. `parsed` is the page's parse when the handler already has one (INV-26). A crawl-discovered
    page may end `no_match`."""
    schema = await get_by_id(conn, records.schema_id)
    config = None
    if records.config_id is not None:
        config = await config_by_id(conn, records.config_id, records.data.vocabulary)
    executor = None if config is None else config.executor
    gap_fill = None if llm is None else role_c(llm, job_id=task.job_id)
    extraction = await extract_page(page.result.bundle, schema, executor, gap_fill, data=records.data, parsed=parsed)
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
