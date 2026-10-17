"""`GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}` and `GET /v1/jobs/{id}/results` (SPEC-10 §4.2): the jobs a page at a
time, a job's summary, its cancel, and its records or page outputs a page at a time."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from crawlerai.api.auth import require_api_key
from crawlerai.api.database import database
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import conflict, not_found
from crawlerai.db.models import JobId
from crawlerai.services import jobs
from crawlerai.services.fetching import Fetching
from crawlerai.services.jobs import (
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


@router.get("/{job_id}/request")
async def get_job_request(job_id: JobId, request: Request) -> dict[str, Any]:
    """The request the job was submitted with, as the server validated and stored it (defaults filled in)."""
    engine = database(request)
    async with engine.connect() as conn:
        try:
            return await jobs.job_request(conn, job_id)
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


@router.get("/{job_id}/results", responses={409: PROBLEM_RESPONSE})
async def job_results(
    job_id: JobId, query: Annotated[ResultsQuery, Query()], request: Request
) -> RecordPage | ExportPage | PageOutputPage | JsonValuesPage:
    """The job's records, newest first: in the field shape of `/v1/records` (`format=json`), or as `json_records`,
    `csv_records` or `markdown` text in the schema's columns. A job without a schema answers `format=json` with its
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
    async with engine.connect() as conn:
        try:
            return await jobs.job_results(conn, job_id, query, store=fetching.store, adapters=fetching.rungs.adapters)
        except JobNotFound as e:
            raise not_found(str(e)) from e
        except NotExportable as e:
            raise conflict(str(e)) from e
