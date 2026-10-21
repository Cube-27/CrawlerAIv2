"""The handler of `batch_scrape` and `extract` tasks (jobs spec): a scrape's steps
(`crawlerai.services.scrape_steps`), run by a worker instead of while a caller waits. An `extract` job is a records job
whose URLs are all caller-supplied, as a batch's are, so its tasks run as a records batch's do.

The page is fetched politely (`crawlerai.services.polite`): robots.txt over HTTP, the site's rate, backoff through the
queue. Its capture is stored, and for `records` it is extracted with what the job pinned when it was submitted
(INV-28): the schema document, the precedence orders and calibration, and the site's active config then, if it had one
(`config` mode; the page joins the config's drift window, as a scrape's does). Its record is stored. Page outputs are
not stored: `/v1/jobs/{id}/results` makes them from the capture.

A records task fetches its page whole and extracts it fresh every run, a recurring run's too: no record stored by an
earlier run stands for it (jobs spec, "Fresh extraction"; `steps.extract_records`).

Everything is written in the worker's transaction for the task, so a task that raises rolls back alone and fails no
other (INV-31). A page that was not reached ends with its outcome (`blocked`, `shell`, `not_found`); a fetch error is a
transient failure, retried by the queue and `failed` once attempts run out; a redirect the SSRF guard refused fails
the task at once (INV-16).
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.queue import ClaimedTask
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape_steps import FetchOptions, PageFormat
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
from crawlerai.worker.loop import Failed, Finished, TaskHandler, TaskResult


class _PageFetch(BaseModel):
    """How the job's request asks its pages to be fetched: the members a batch and an extract request share."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    fetch: FetchOptions
    locale: str | None
    formats: list[PageFormat] = Field(default_factory=list)  # an extract job's request has none


def scrape_handler(
    fetching: Fetching, data: EngineData | None, margins: DriftMargins | None, *, llm: LLMClient
) -> TaskHandler:
    """The `batch_scrape` and `extract` handler of a worker that fetches with `fetching`; `data` is None in a worker
    without the engine's data files, whose records tasks then fail. `margins` decide drift suspensions (learning-configs
    spec); role C runs on `llm`."""

    async def handle(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = _PageFetch.model_validate(job[0]), job[1]
        # A records job asks for nothing else of its pages (`BatchScrapeRequest`, `ExtractRequest`).
        page = await fetch_page(
            conn,
            fetching,
            task,
            request.fetch,
            request.locale,
            served=records,
            formats=request.formats,
            planned=records,
        )
        result = (
            page.task_result if isinstance(page, Ended) else await _settle(conn, fetching, task, page, records, llm)
        )
        await count_fetch(conn, task, page)
        return result

    return handle


async def _settle(
    conn: AsyncConnection,
    fetching: Fetching,
    task: ClaimedTask,
    page: FetchedPage,
    records: Records | None,
    llm: LLMClient,
) -> TaskResult:
    """The fetched page's result: its outcome when it was not reached or the job has no records, else its record's."""
    ended = unreached(page, task)
    if ended is not None:
        return ended
    if records is None:
        return Finished("extracted", capture_id=page.capture_id)
    parsed = page.parsed
    result = await extract_records(conn, task, page, records, caller_supplied=True, llm=llm, parsed=parsed)
    if isinstance(result, Finished):
        result = await store_further_pages(
            conn, fetching.store, task, page, records, caller_supplied=True, llm=llm, result=result
        )
    return result
