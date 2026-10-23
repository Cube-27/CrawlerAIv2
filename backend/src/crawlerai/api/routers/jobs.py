"""`GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/outcomes` and `GET /v1/jobs/{id}/results`:
the jobs a page at a time, a job's summary and outcomes, its cancel, and its records or page outputs a page at a
time."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import conflict, format_unavailable, not_found
from crawlerai.config_ir.exporters.files import FileFormat, FormatUnavailable
from crawlerai.db.models import JobId
from crawlerai.services import exports, jobs
from crawlerai.services.fetching import Fetching
from crawlerai.services.job_outcomes import JobOutcomes, job_outcomes
from crawlerai.services.jobs import (
    FILE_FORMATS,
    ExportPage,
    JobEnded,
    JobListQuery,
    JobNotFound,
    JobPage,
    JobSummary,
    JsonValuesPage,
    NotExportable,
    PageOutputPage,
    ResultsQuery,
)
from crawlerai.services.records import RecordPage
from crawlerai.services.webhook_deliveries import DeliveryListQuery, DeliveryPage, list_deliveries

router = APIRouter(
    prefix="/v1/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
    responses={401: PROBLEM_RESPONSE, 404: PROBLEM_RESPONSE, 422: PROBLEM_RESPONSE, 429: PROBLEM_RESPONSE},
)


@router.get("")
async def list_jobs(query: Annotated[JobListQuery, Query()], request: Request) -> JobPage:
    """The jobs, newest first, each with the summary `GET /v1/jobs/{id}` answers; only those of `kind` and `status`
    when given. Pass a page's `next_cursor` as `cursor` for the page after it."""
    engine = database(request)
    async with engine.connect() as conn:
        return await jobs.list_jobs(conn, query)


@router.get("/{job_id}")
async def get_job(job_id: JobId, request: Request) -> JobSummary:
    """The job's status, its task counts by status and by outcome, and its usage."""
    engine = database(request)
    async with engine.connect() as conn:
        try:
            return await jobs.get_job(conn, job_id)
        except JobNotFound as e:
            raise not_found(str(e)) from e


@router.get("/{job_id}/outcomes")
async def get_job_outcomes(job_id: JobId, request: Request) -> JobOutcomes:
    """The job's pages by outcome, and the fields of its records by status with the reasons the unpublished ones give:
    counted from what the job stored."""
    async with database(request).connect() as conn:
        try:
            return await job_outcomes(conn, job_id)
        except JobNotFound as e:
            raise not_found(str(e)) from e


@router.get("/{job_id}/request")
async def get_job_request(job_id: JobId, request: Request) -> dict[str, Any]:
    """The request the job was submitted with, as the server validated and stored it (defaults filled in)."""
    engine = database(request)
    async with engine.connect() as conn:
        try:
            return await jobs.job_request(conn, job_id)
        except JobNotFound as e:
            raise not_found(str(e)) from e


@router.get("/{job_id}/webhook-deliveries")
async def job_webhook_deliveries(
    job_id: JobId, query: Annotated[DeliveryListQuery, Query()], request: Request
) -> DeliveryPage:
    """The job's webhook deliveries, newest first, for debugging a receiver: each one's status (`pending`, `delivered`
    or `failed`), attempts, the last attempt's error and the HTTP status the target answered with, and how many events
    it carries. Ended deliveries are kept 30 days. Pass a page's `next_cursor` as `cursor` for the page after it."""
    async with database(request).connect() as conn:
        try:
            return await list_deliveries(conn, job_id, query)
        except JobNotFound as e:
            raise not_found(str(e)) from e


@router.delete("/{job_id}", responses={409: PROBLEM_RESPONSE})
async def cancel_job(job_id: JobId, request: Request) -> JobSummary:
    """Cancel the job: its queued tasks are not run, and it is `cancelled` once no task is running. 409: it already
    completed or failed."""
    engine = database(request)
    try:
        async with engine.begin() as conn:
            return await jobs.cancel_job(conn, job_id)
    except JobNotFound as e:
        raise not_found(str(e)) from e
    except JobEnded as e:
        raise conflict(str(e)) from e


@router.get(
    "/{job_id}/results",
    response_model=RecordPage | ExportPage | PageOutputPage | JsonValuesPage,
    responses={409: PROBLEM_RESPONSE, 503: PROBLEM_RESPONSE},
)
async def job_results(
    job_id: JobId, query: Annotated[ResultsQuery, Query()], request: Request
) -> RecordPage | ExportPage | PageOutputPage | JsonValuesPage | Response:
    """The job's records, newest first: in the field shape of `/v1/records` (`format=json`), or as `json_records`,
    `csv_records`, `markdown` or `jsonl` (JSON Lines) text in the schema's columns, or all of them as one file,
    `xlsx` (Excel) or `parquet` (Apache Parquet, 503 `format_unavailable` where pyarrow is not installed), which take no
    `cursor` or `limit`. A job without a schema answers `format=json` with its
    tasks, oldest first, each with the content formats the job asked for once its page was reached, and its fetch (the
    attempts made, as a scrape answers them). Any job
    answers `format=json_values` with its tasks, oldest first, each with its URL, outcome and clean records (the
    schema's fields in name order, each its published value or null); `include=metadata`, accepted with `json_values`
    only, adds a reached page's metadata while its capture is kept, and `include=fetch` its fetch. `csv_safe=true`,
    accepted with `csv_records` only, prefixes `'` to each cell starting with `=`, `+`, `-`, `@`, a tab or a carriage
    return, so a spreadsheet shows it as text (OWASP CSV Injection); without it the export is the published values
    unchanged. Pass a page's `next_cursor` as `cursor` for the page after it. 409: an export other than `json_values`
    of a job without a schema."""
    engine = database(request)
    fetching: Fetching = request.app.state.fetching
    if query.format in FILE_FORMATS:
        return await _results_file(job_id, query, request)
    async with engine.connect() as conn:
        try:
            return await jobs.job_results(conn, job_id, query, store=fetching.store, adapters=fetching.rungs.adapters)
        except JobNotFound as e:
            raise not_found(str(e)) from e
        except NotExportable as e:
            raise conflict(str(e)) from e


async def _results_file(job_id: JobId, query: ResultsQuery, request: Request) -> Response:
    fmt: FileFormat = "xlsx" if query.format == "xlsx" else "parquet"
    async with database(request).connect() as conn:
        try:
            made = await exports.export_job_file(conn, job_id, fmt)
        except JobNotFound as e:
            raise not_found(str(e)) from e
        except NotExportable as e:
            raise conflict(str(e)) from e
        except FormatUnavailable as e:
            raise format_unavailable(str(e)) from e
    headers = {"Content-Disposition": f'attachment; filename="{made.filename}"'}
    return Response(made.data, media_type=made.media_type, headers=headers)


_TEXT: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/plain": {"schema": {"type": "string"}}}},
    409: PROBLEM_RESPONSE,
}


@router.get("/{job_id}/llms.txt", response_class=Response, responses=_TEXT)
async def job_llms_txt(job_id: JobId, request: Request) -> Response:
    """The job's pages as an `llms.txt` (llmstxt.org): the site's name and summary from its first page, then links to
    the pages it reached, each with its title and description, in sections by the first segment of their paths. Made
    from the captures, for any job that reached pages (a crawl, batch or extract), up to 5000 pages. 409: no page."""
    return await _llms(job_id, request, full=False)


@router.get("/{job_id}/llms-full.txt", response_class=Response, responses=_TEXT)
async def job_llms_full_txt(job_id: JobId, request: Request) -> Response:
    """The job's pages as an `llms-full.txt`: the opening of `llms.txt`, then each page's Markdown under its title, up
    to 1000 pages. 409: no page."""
    return await _llms(job_id, request, full=True)


async def _llms(job_id: JobId, request: Request, *, full: bool) -> Response:
    fetching: Fetching = request.app.state.fetching
    async with database(request).connect() as conn:
        try:
            text = await exports.job_llms_txt(conn, fetching.store, job_id, full=full)
        except JobNotFound as e:
            raise not_found(str(e)) from e
        except NotExportable as e:
            raise conflict(str(e)) from e
    return Response(text, media_type="text/plain; charset=utf-8")
