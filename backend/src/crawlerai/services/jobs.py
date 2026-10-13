"""The jobs service (SPEC-10 §4.2, ARCHITECTURE §13.1): a job's summary, its cancel, and its results a page at a time.
`GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results` and the MCP status tools answer with these."""

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.exporters.records import RecordFormat, export_records
from crawlerai.db.jobs import JOB_TRANSITIONS, transition_job
from crawlerai.db.models import Job, JobId, JobKind, JobStatus, RecordId, TaskOutcome, TaskStatus, UrlTask
from crawlerai.db.queue import settle_job
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.schemas import registry
from crawlerai.services.records import MAX_PAGE, RecordFilter, RecordPage, StoredRecord, list_records

ResultFormat = Literal["json", RecordFormat]


class JobNotFound(LookupError):
    pass


class JobEnded(Exception):
    """The job completed or failed before its cancel was asked for."""


class NotExportable(Exception):
    """The job has no schema, so its records have no columns to export."""


class TaskCounts(BaseModel):
    """How many of the job's tasks are in each status (SPEC-01 §4.3)."""

    model_config = ConfigDict(frozen=True)

    queued: int
    claimed: int
    done: int
    failed: int
    cancelled: int


class OutcomeCounts(BaseModel):
    """How many of the job's tasks ended with each outcome (`url_task.outcome`, ARCHITECTURE §6)."""

    model_config = ConfigDict(frozen=True)

    extracted: int
    partial: int
    unchanged: int
    links_only: int
    blocked: int
    shell: int
    not_found: int
    no_match: int
    failed: int


class JobSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: JobId
    kind: JobKind
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    counts: TaskCounts
    outcomes: OutcomeCounts
    usage: dict[str, int]  # per `usage_event.resource` (SPEC-01 §4.6)
    webhook_url: str | None
    engine_version: str


class ExportPage(BaseModel):
    """One page of a job's records in an export format (SPEC-08 §4.11); `next_cursor` as in `RecordPage`."""

    model_config = ConfigDict(frozen=True)

    format: RecordFormat
    content: str
    next_cursor: RecordId | None


class ResultsQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: RecordId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)
    format: ResultFormat = "json"


_JOB_COLUMNS = (
    Job.id,
    Job.kind,
    Job.status,
    Job.created_at,
    Job.started_at,
    Job.finished_at,
    Job.usage,
    Job.webhook_url,
    Job.engine_version,
)


async def get_job(conn: AsyncConnection, job_id: JobId) -> JobSummary:
    job = (await conn.execute(select(*_JOB_COLUMNS).where(Job.id == job_id))).mappings().one_or_none()
    if job is None:
        raise JobNotFound(f"no job {job_id}")
    rows = await conn.execute(
        select(UrlTask.status, UrlTask.outcome, func.count())
        .where(UrlTask.job_id == job_id)
        .group_by(UrlTask.status, UrlTask.outcome)
    )
    statuses: dict[str, int] = dict.fromkeys(get_args(TaskStatus), 0)
    outcomes: dict[str, int] = dict.fromkeys(get_args(TaskOutcome), 0)
    for status, outcome, n in rows.all():
        statuses[status] += n
        if outcome is not None:
            outcomes[outcome] += n
    return JobSummary(**job, counts=TaskCounts(**statuses), outcomes=OutcomeCounts(**outcomes))


async def cancel_job(conn: AsyncConnection, job_id: JobId) -> JobSummary:
    """Ask the job to stop (SPEC-10 §4.2): its queued tasks are cancelled at once, its claimed ones as their workers
    finish, and the job is `cancelled` once none is claimed. Cancelling a cancelled job again changes nothing; a job
    that completed or failed cannot be cancelled (`JobEnded`)."""
    status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one_or_none()
    if status is None:
        raise JobNotFound(f"no job {job_id}")
    if status in ("completed", "failed"):
        raise JobEnded(f"job {job_id} already {status}")
    if status != "cancelled":
        await _cancel(conn, job_id)
    return await get_job(conn, job_id)


async def _cancel(conn: AsyncConnection, job_id: JobId) -> None:
    # Tasks first, then the job row: the order a finishing worker locks them in (`crawlerai.db.queue`), so the two
    # never wait on each other. A claim that starts the job locks its tasks before the job too.
    await conn.execute(
        update(UrlTask).where(UrlTask.job_id == job_id, UrlTask.status == "queued").values(status="cancelled")
    )
    locked = select(Job.status).where(Job.id == job_id).with_for_update()
    status = (await conn.execute(locked)).scalar_one()
    if not JOB_TRANSITIONS[status]:
        return  # it ended while its tasks were cancelled
    await conn.execute(update(Job).where(Job.id == job_id).values(cancel_requested=True))
    if status == "queued":
        # No task of it was ever claimed: a claim starts its job in the same transaction.
        await transition_job(conn, job_id, "cancelled")
    else:
        await settle_job(conn, job_id)


async def job_results(conn: AsyncConnection, job_id: JobId, query: ResultsQuery) -> RecordPage | ExportPage:
    """The job's records after `query.cursor`, newest first, in the field shape of `/v1/records` (`json`) or exported
    in the schema's columns. Values are the stored published values, unchanged (INV-27)."""
    job = (await conn.execute(select(Job.schema_id).where(Job.id == job_id))).one_or_none()
    if job is None:
        raise JobNotFound(f"no job {job_id}")
    page = await list_records(conn, RecordFilter(job_id=job_id, cursor=query.cursor, limit=query.limit))
    if query.format == "json":
        return page
    if job.schema_id is None:
        raise NotExportable(f"job {job_id} has no schema, so it has no records to export")
    schema = await registry.get_by_id(conn, job.schema_id)
    content = export_records(query.format, schema, [_content(record) for record in page.items])
    return ExportPage(format=query.format, content=content, next_cursor=page.next_cursor)


def _content(record: StoredRecord) -> RecordContent:
    meta = {name: FieldMeta(**field.model_dump(exclude={"value"})) for name, field in record.fields.items()}
    data = {name: field.value for name, field in record.fields.items() if field.status == "published"}
    return RecordContent(data=data, field_meta=meta, complete=record.complete)
