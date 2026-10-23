"""What the handlers of page tasks (`batch_scrape`, `extract`, `crawl`) do the same way before the page's run
(`page_run`): the task's job, and the records the task extracts with as the job pinned them; fetching
its page politely, or reading its stored capture (`fetch.cache`, as a scrape does); and counting its fetches as the
job's usage.

The task's page is fetched before the worker's transaction for the task opens (`fetch_page`, through the one page-task
fetch, `services.page_task`, as a queued task: `QUEUED`): the site's row, its robots.txt, its adapter declines and what
the fetch taught its memory (`acquire.memory`) are each read or written in a short transaction of their own, so no task
holds a site's rows while it fetches or extracts, and the tasks of one site run side by side. The page's run
(`page_run`: its capture, extraction and records) writes in the worker's transaction for the task, so a task that
raises rolls back alone; site memory only is learned beside it. The task's fetch attempts are counted as the job's
usage at its end (`count_fetch`): that write locks the job's row until the task commits.
"""

import time
from collections.abc import Sequence
from typing import Final
from urllib.parse import urlsplit

from pydantic import TypeAdapter
from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.ssrf import SsrfRejected
from crawlerai.config_ir.active import config_by_id
from crawlerai.config_ir.api_recipe.execute import MAX_PAGES
from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.models import Job, SchemaId
from crawlerai.db.queue import TASK_DEADLINE, ClaimedTask, Failed
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.types import Probability
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.batch import JobPins
from crawlerai.services.fetch_options import FetchOptions
from crawlerai.services.fetching import Fetching
from crawlerai.services.page_run import Page, Records
from crawlerai.services.page_store import record_fetch_usage, site_row
from crawlerai.services.page_task import NotReached, PageTask, fetch_task
from crawlerai.services.polite import QUEUED
from crawlerai.services.scrape_request import PageFormat, RenderOptions
from crawlerai.services.stored_captures import NOT_CACHED, NotCached

# The `last_error` of a records task in a worker that has not loaded the engine's data files.
RECORDS_UNAVAILABLE: Final = "records_unavailable"

# The request's `min_confidence`, as the job row stores it.
_MIN_CONFIDENCE: Final = TypeAdapter(Probability)
_JobRow = Row[dict[str, object], SchemaId | None, dict[str, object] | None]


async def load_job(
    conn: AsyncConnection, task: ClaimedTask, data: EngineData | None, margins: DriftMargins | None
) -> tuple[dict[str, object], Records | None] | Failed:
    """The task's job request, and what the task extracts records with from the job's schema and pins (`JobPins`):
    None for a job without records. The pinned config is read and bound once, whatever its status now. A
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
    are drafted off the request path (`s_labels.with_labels`), and are no part of the document the job pins, so they
    apply while the row still holds that document."""
    if pinned.labels is not None:
        return pinned
    stored = await registry.get_by_id(conn, schema_id)
    if stored.labels is None or document_digest(stored) != document_digest(pinned):
        return pinned
    return pinned.model_copy(update={"labels": stored.labels})


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
) -> Page | NotReached:
    """The task's page fetched as a queued task (`page_task.fetch_task`, `QUEUED`), or how the task ends this run
    without one. Neither writes the job's usage. A request the SSRF guard refused fails the task at once: the task's
    URL is checked before anything, as the services that fetch while the caller waits check theirs (`check_target`),
    since a crawl's URLs were never checked at submit.

    With `served`, the records the task extracts with when they are all it reads of the page, the config they name
    serves the page through its API recipe when it has one; a listing's recipe with pagination serves up to
    `listing_pages` pages of it, the first the task's capture and record, each further one stored under the task as a
    listing's further kept state is (`store_further`).

    `formats` are those the task's page is read for: a screenshot or PDF among them is made in the browser
    (`fetch_policy`).

    With `planned`, the records the task extracts with, the page is fetched by the plan its config's field sources and
    its surface's render mode dictate (`surface_plan`)."""
    try:
        await fetching.connector.check(task.url)
    except SsrfRejected as e:
        return NotReached(Failed(str(e), transient=False))
    # A new host's site row is committed at once, so the other tasks of the host do not wait on it.
    async with engine.begin() as conn:
        site = await site_row(conn, urlsplit(task.url).hostname or "", task.page_kind)
    page_task = PageTask(
        task,
        options,
        locale,
        # The task's deadline runs from its claim, a moment before this (`worker.loop`).
        time.monotonic() + TASK_DEADLINE.total_seconds(),
        formats,
        records=planned or served,
        served=served is not None,
        planned=planned is not None,
        listing_pages=listing_pages,
    )
    try:
        return await fetch_task(engine, fetching, site, page_task, QUEUED)
    except NotCached:  # a job has no `max_age`: `cache: only` reads a stored capture of any age
        return NotReached(Failed(NOT_CACHED, transient=False))


async def count_fetch(conn: AsyncConnection, task: ClaimedTask, page: Page | NotReached) -> None:
    """Count the task's fetch attempts as the job's usage. A handler counts them at the task's end, as its last write
    but the frontier's: the job's row stays locked from this write until the task commits, and role C's client, which
    updates the job's usage on a connection of its own, would wait on it, as would a cancel."""
    await record_fetch_usage(conn, task.job_id, page.attempts, page.proxy_pool)
