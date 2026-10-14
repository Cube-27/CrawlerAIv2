"""The handler of `batch_scrape` tasks (SPEC-10 §4.3): a scrape's steps (`crawlerai.services.scrape_steps`), run by a
worker instead of while a caller waits.

The page is fetched politely (`crawlerai.worker.polite`): robots.txt over HTTP, the site's rate, backoff through the
queue. Its capture is stored, and for `records` it is extracted with what the job pinned when it was submitted
(INV-28): the schema version, the precedence orders and calibration, and the site's active config then, if it had one
(`config` mode; the page joins the config's drift window, as a scrape's does). Its record is stored. Page outputs are
not stored: `/v1/jobs/{id}/results` makes them from the capture.

Everything is written in the worker's transaction for the task, so a task that raises rolls back alone and fails no
other (INV-31). A page that was not reached ends with its outcome (`blocked`, `shell`, `not_found`); a fetch error is a
transient failure, retried by the queue and `failed` once attempts run out; a redirect the SSRF guard refused fails
the task at once (INV-16).
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.rungs import acquire
from crawlerai.acquire.types import AttemptRecord, FetchResult
from crawlerai.config_ir.active import config_by_id
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.models import CaptureId, ExtractionConfigId, Job, SchemaId, SiteId
from crawlerai.db.queue import ClaimedTask
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
    attempts: list[AttemptRecord] = []

    async def robots(url: str) -> FetchResult:
        result = await fetching.rungs.http(url, policy)
        attempts.extend(result.attempts)
        return result

    async def page(url: str) -> FetchResult:
        result = await acquire(url, policy, site.fetch_method, fetching.rungs)
        attempts.extend(result.attempts)
        return result

    fetched = await fetch_politely(conn, task, site.id, policy, page, fetching.limiter, fetch_robots=robots)
    await record_fetch_usage(conn, task.job_id, attempts, policy.proxy_pool)
    if not isinstance(fetched, FetchResult):
        return fetched
    if (refused := refusal(fetched)) is not None:
        return Failed(refused, transient=False)
    capture_id = await new_capture(conn, fetching.store, site.id, fetched)
    return await _settle(conn, task, site.id, fetched, capture_id, records)


async def _settle(
    conn: AsyncConnection,
    task: ClaimedTask,
    site_id: SiteId,
    fetched: FetchResult,
    capture_id: CaptureId,
    records: _Records | None,
) -> TaskResult:
    outcome = BLOCK_OUTCOMES[fetched.block_class]
    if outcome == "failed":
        return Failed(fetched.attempts[-1].error or outcome, transient=True, capture_id=capture_id)
    if records is None or outcome != "extracted":
        return Finished(outcome, capture_id=capture_id)
    schema = await get_by_id(conn, records.schema_id)
    config = None
    if records.config_id is not None:
        config = await config_by_id(conn, records.config_id, records.data.vocabulary)
    executor = None if config is None else config.executor
    extraction = await extract_page(fetched.bundle, schema, executor, None, data=records.data)
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
    return Finished(record_outcome(stored), capture_id=capture_id)
