"""`GET/DELETE /v1/jobs/{id}` and `GET /v1/jobs/{id}/results` (SPEC-10 §4.2): a job's summary, its cancel, and its
records or page outputs a page at a time."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.auth import require_api_key
from crawlerai.api.dto import PROBLEM_RESPONSE
from crawlerai.api.problems import conflict, not_found
from crawlerai.db.models import JobId
from crawlerai.services import jobs
from crawlerai.services.fetching import Fetching
from crawlerai.services.jobs import (
    ExportPage,
    JobEnded,
    JobNotFound,
    JobSummary,
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


@router.get("/{job_id}")
async def get_job(job_id: JobId, request: Request) -> JobSummary:
    """The job's status, its task counts by status and by outcome, and its usage."""
    engine: AsyncEngine = request.app.state.database
    async with engine.connect() as conn:
        try:
            return await jobs.get_job(conn, job_id)
        except JobNotFound as e:
            raise not_found(str(e)) from e


@router.delete("/{job_id}", responses={409: PROBLEM_RESPONSE})
async def cancel_job(job_id: JobId, request: Request) -> JobSummary:
    """Cancel the job: its queued tasks are not run, and it is `cancelled` once no task is running. 409: it already
    completed or failed."""
    engine: AsyncEngine = request.app.state.database
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
) -> RecordPage | ExportPage | PageOutputPage:
    """The job's records, newest first: in the field shape of `/v1/records` (`format=json`), or as `json_records`,
    `csv_records` or `markdown` text in the schema's columns. A job without a schema answers `format=json` with its
    tasks, oldest first, each with the content formats the job asked for once its page was reached. Pass a page's
    `next_cursor` as `cursor` for the page after it. 409: an export of a job without a schema."""
    engine: AsyncEngine = request.app.state.database
    fetching: Fetching = request.app.state.fetching
    async with engine.connect() as conn:
        try:
            return await jobs.job_results(conn, job_id, query, store=fetching.store)
        except JobNotFound as e:
            raise not_found(str(e)) from e
        except NotExportable as e:
            raise conflict(str(e)) from e
