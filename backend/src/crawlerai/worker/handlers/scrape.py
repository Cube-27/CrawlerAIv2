"""The handler of `batch_scrape` tasks (SPEC-10 §4.3): a scrape's steps (`crawlerai.services.scrape_steps`), run by a
worker instead of while a caller waits.

The page is fetched politely (`crawlerai.worker.polite`): robots.txt over HTTP, the site's rate, backoff through the
queue. Its capture is stored, and for `records` it is extracted with what the job pinned when it was submitted
(INV-28): the schema version, the precedence orders and calibration, and the site's active config then, if it had one
(`config` mode; the page joins the config's drift window, as a scrape's does). Its record is stored. Page outputs are
not stored: `/v1/jobs/{id}/results` makes them from the capture.

A records task is how a recurring run sees a page again (SPEC-11 §4.2, §4.3). When a record already stands for the
page (`crawlerai.recurring.state.standing_record`), the page is fetched with the validators it last answered with,
and a 304 ends the task `unchanged` with no capture. A page fetched whole whose visible text is within a few SimHash
bits of the last ends `unchanged` with its capture, and is not extracted. Only records tasks read or write
`url_state`: a fingerprint or validators stored without the record made from that content would let a stale record
stand.

Everything is written in the worker's transaction for the task, so a task that raises rolls back alone and fails no
other (INV-31). A page that was not reached ends with its outcome (`blocked`, `shell`, `not_found`); a fetch error is a
transient failure, retried by the queue and `failed` once attempts run out; a redirect the SSRF guard refused fails
the task at once (INV-16).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.rungs import acquire
from crawlerai.acquire.types import AttemptRecord, FetchResult, Validators
from crawlerai.config_ir.active import config_by_id
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import CaptureId, ExtractionConfig, ExtractionConfigId, Job, RecordId, SchemaId, SiteId
from crawlerai.db.queue import ClaimedTask
from crawlerai.recurring.conditional import Unchanged, fetch_unless_unchanged
from crawlerai.recurring.simhash import simhash64
from crawlerai.recurring.state import record_content, record_fetch, standing_record, stored_validators
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.schemas.registry import get_by_id
from crawlerai.services.batch import BatchScrapeRequest, JobPins
from crawlerai.services.fetching import Fetching, refusal
from crawlerai.services.scrape_steps import (
    BLOCK_OUTCOMES,
    EXTRACTION_ERROR,
    fetch_policy,
    new_capture,
    record_fetch_usage,
    record_outcome,
    site_row,
    store_page_record,
)
from crawlerai.worker.loop import Failed, Finished, TaskHandler, TaskResult
from crawlerai.worker.polite import fetch_politely

log = logging.getLogger(__name__)

# The `last_error` of a records task in a worker that has not loaded the engine's data files (D-0492).
RECORDS_UNAVAILABLE: Final = "records_unavailable"

_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


@dataclass(frozen=True)
class _Records:
    """What a records task extracts with: the job's schema version, the engine data its pins give, the config they
    name for the task's host (None: cold), and the drift margins of this worker."""

    schema_id: SchemaId
    data: EngineData
    config_id: ExtractionConfigId | None
    margins: DriftMargins | None


def scrape_handler(fetching: Fetching, data: EngineData | None, margins: DriftMargins | None) -> TaskHandler:
    """The `batch_scrape` handler of a worker that fetches with `fetching`; `data` is None in a worker without the
    engine's data files, whose records tasks then fail. `margins` decide drift suspensions (SPEC-08 §4.9)."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job: _JobRow = (
            await conn.execute(select(Job.request, Job.schema_id, Job.pinned).where(Job.id == task.job_id))
        ).one()
        records = None
        if job.schema_id is not None:
            if data is None:
                return Failed(RECORDS_UNAVAILABLE, transient=False)
            pins = JobPins.model_validate(job.pinned)
            config_id = pins.configs.get(urlsplit(task.url).hostname or "")
            records = _Records(job.schema_id, data.pinned(pins.engine_data), config_id, margins)
        return await _scrape(conn, fetching, task, BatchScrapeRequest.model_validate(job.request), records)

    return handle


async def _scrape(
    conn: AsyncConnection, fetching: Fetching, task: ClaimedTask, request: BatchScrapeRequest, records: _Records | None
) -> TaskResult:
    site = await site_row(conn, urlsplit(task.url).hostname or "")
    policy = fetch_policy(request.fetch, request.locale, site.proxy_pool)
    standing = None if records is None else await _standing(conn, task, site.id, records)
    # Validators go only where a record stands for a 304; without one, a 304 is fetched again whole (§4.6).
    validators = None if standing is None else await stored_validators(conn, site.id, task.canonical_url)
    attempts: list[AttemptRecord] = []

    async def robots(url: str) -> FetchResult:
        result = await fetching.rungs.http(url, policy)
        attempts.extend(result.attempts)
        return result

    async def page(url: str) -> FetchResult | Unchanged:
        async def fetch(sent: Validators | None) -> FetchResult:
            result = await acquire(url, policy, site.fetch_method, fetching.rungs, validators=sent)
            attempts.extend(result.attempts)
            return result

        return await fetch_unless_unchanged(fetch, validators, has_record=standing is not None)

    fetched = await fetch_politely(conn, task, site.id, policy, page, fetching.limiter, fetch_robots=robots)
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    if isinstance(fetched, Unchanged):
        await record_fetch(conn, site.id, task.canonical_url, fetched)
        return Finished("unchanged")
    if not isinstance(fetched, FetchResult):
        return fetched
    if (refused := refusal(fetched)) is not None:
        return Failed(refused, transient=False)
    capture_id = await new_capture(conn, fetching.store, site.id, fetched)
    return await _settle(conn, task, site.id, fetched, capture_id, records, standing)


async def _standing(conn: AsyncConnection, task: ClaimedTask, site_id: SiteId, records: _Records) -> RecordId | None:
    """The record that stands for the page while it is unchanged (`standing_record`), for the config the job pinned
    (None: `adhoc`). Only the config's version is read here: the page may never be extracted."""
    version = None
    if records.config_id is not None:
        query = select(ExtractionConfig.version).where(ExtractionConfig.id == records.config_id)
        version = (await conn.execute(query)).scalar_one()
    return await standing_record(conn, site_id, task.canonical_url, records.schema_id, version)


async def _settle(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    fetched: FetchResult,
    capture_id: CaptureId,
    records: _Records | None,
    standing: RecordId | None,
) -> TaskResult:
    outcome = BLOCK_OUTCOMES[fetched.block_class]
    if outcome == "failed":
        return Failed(fetched.attempts[-1].error or outcome, transient=True, capture_id=capture_id)
    if records is None or outcome != "extracted":
        return Finished(outcome, capture_id=capture_id)
    parsed = ParsedPage.of(fetched.bundle)
    changed = await _content_changed(conn, site_id, task.canonical_url, parsed)
    if not changed and standing is not None:
        await record_fetch(conn, site_id, task.canonical_url, fetched)
        return Finished("unchanged", capture_id=capture_id)
    schema = await get_by_id(conn, records.schema_id)
    config = None
    if records.config_id is not None:
        config = await config_by_id(conn, records.config_id, records.data.vocabulary)
    executor = None if config is None else config.executor
    extraction = await extract_page(fetched.bundle, schema, executor, None, data=records.data, parsed=parsed)
    stored = await store_page_record(
        conn,
        task,
        extraction,
        capture_id=capture_id,
        site_id=site_id,
        schema=schema,
        config=config,
        margins=records.margins,
    )
    if stored is None:
        return Failed(EXTRACTION_ERROR, transient=False, capture_id=capture_id)
    # The validators are stored with the record made from the content they describe, never without it.
    await record_fetch(conn, site_id, task.canonical_url, fetched)
    return Finished(record_outcome(stored), capture_id=capture_id)


async def _content_changed(conn: AsyncConnection, site_id: SiteId, canonical_url: str, parsed: ParsedPage) -> bool:
    """Whether the page's visible text changed since it was last fingerprinted (`record_content`). A page without
    words, or one whose fingerprint fails, counts as changed and is extracted: an error never skips extraction
    (§4.6)."""
    try:
        # Rendering the text is CPU work, as resolution is: a thread keeps the event loop serving other tasks.
        fingerprint = await asyncio.to_thread(lambda: simhash64(parsed.cleaned_text.text))
    except Exception:
        log.exception("the content fingerprint failed; the page is extracted")
        return True
    return fingerprint is None or await record_content(conn, site_id, canonical_url, fingerprint)
