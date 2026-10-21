"""The handler of `batch_scrape` and `extract` tasks (jobs spec): a scrape's page run (`page_run`),
run by a worker instead of while a caller waits. An `extract` job is a records job
whose URLs are all caller-supplied, as a batch's are, so its tasks run as a records batch's do.

The page is fetched politely (`crawlerai.services.polite`): robots.txt over HTTP, the site's rate, backoff through the
queue. Its capture is stored, and for `records` it is extracted with what the job pinned when it was submitted
(INV-28): the schema document, the precedence orders and calibration, and the site's active config then, if it had one
(`config` mode; the page joins the config's drift window, as a scrape's does). Its record is stored. Page outputs are
not stored: `/v1/jobs/{id}/results` makes them from the capture.

A records task fetches its page whole and extracts it fresh every run, a recurring run's too: no record stored by an
earlier run stands for it (jobs spec, "Fresh extraction"; `page_run.extract_run`).

The page is fetched before the worker's transaction for the task opens, site memory learned in short transactions of its
own (`steps.fetch_page`), and extracted before it opens; everything else is written in that transaction, so a task that
raises rolls back alone and fails no other (INV-31). A page that was not reached ends with its outcome (`blocked`,
`shell`, `not_found`); a fetch error is a transient failure, retried by the queue and `failed` once attempts run out; a
redirect the SSRF guard refused fails the task at once (INV-16).
"""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.config_ir.drift import DriftMargins
from crawlerai.config_ir.role_c import role_c
from crawlerai.db.queue import ClaimedTask, Failed
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetch_options import FetchOptions
from crawlerai.services.fetching import Fetching
from crawlerai.services.page_run import extract_run, page_run
from crawlerai.services.scrape_request import PageFormat
from crawlerai.worker.handlers.steps import Ended, count_fetch, fetch_page, load_job
from crawlerai.worker.loop import Settle, TaskHandler, TaskResult


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

    async def handle(task: ClaimedTask, engine: AsyncEngine) -> Settle | TaskResult:
        async with engine.connect() as conn:
            job = await load_job(conn, task, data, margins)
        if isinstance(job, Failed):
            return job
        request, records = _PageFetch.model_validate(job[0]), job[1]
        # A records job asks for nothing else of its pages (`BatchScrapeRequest`, `ExtractRequest`).
        fetched = await fetch_page(
            engine,
            fetching,
            task,
            request.fetch,
            request.locale,
            served=records,
            formats=request.formats,
            planned=records,
        )

        if isinstance(fetched, Ended):
            ended = fetched

            async def end(conn: AsyncConnection) -> TaskResult:
                await count_fetch(conn, task, ended)
                return ended.task_result

            return end
        page = fetched
        # The page resolves before the task's transaction opens (`page_run`).
        extracted = await extract_run(page, records, role_c(llm, job_id=task.job_id))

        async def settle(conn: AsyncConnection) -> TaskResult:
            run = await page_run(
                conn, engine, fetching.store, task, page, extracted, retryable=True, caller_supplied=True
            )
            await count_fetch(conn, task, page)
            return run.result

        return settle

    return handle
