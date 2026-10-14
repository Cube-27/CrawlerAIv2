"""The jobs service (SPEC-10 §4.2, ARCHITECTURE §13.1): the jobs a page at a time, a job's summary, its cancel, and
its results a page at a time. `GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results` and the MCP
status tools answer with these.

The results of a job with a schema are its records. Those of a job without one are its page outputs: each task's
content formats, made from its capture when they are read. A format is a function of the capture alone (ARCHITECTURE
§15), so nothing else is stored, and a page's outputs go when its capture expires.
"""

import asyncio
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Row, RowMapping, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.exporters.records import RecordFormat, export_records
from crawlerai.config_ir.progressive import StateKey, learning_failed
from crawlerai.content.metadata import PageMetadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.db.jobs import JOB_TRANSITIONS, transition_job
from crawlerai.db.models import (
    Capture,
    CaptureId,
    Job,
    JobId,
    JobKind,
    JobStatus,
    RecordId,
    TaskOutcome,
    TaskStatus,
    UrlTask,
    UrlTaskId,
)
from crawlerai.db.queue import settle_job
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.schemas import registry
from crawlerai.services.records import MAX_PAGE, RecordFilter, RecordPage, StoredRecord, list_records
from crawlerai.services.scrape_steps import Formats, PageFormat, format_member, page_formats
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

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


class JobPage(BaseModel):
    """One page of jobs, newest first; `next_cursor` is the `cursor` of the page after it, None on the last."""

    model_config = ConfigDict(frozen=True)

    items: list[JobSummary]
    next_cursor: JobId | None


class JobListQuery(BaseModel):
    """The jobs to list: all of them, or those of a kind, of a status, or both."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: JobKind | None = None
    status: JobStatus | None = None
    cursor: JobId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


class ExportPage(BaseModel):
    """One page of a job's records in an export format (SPEC-08 §4.11); `next_cursor` as in `RecordPage`."""

    model_config = ConfigDict(frozen=True)

    format: RecordFormat
    content: str
    next_cursor: RecordId | None


class PageOutput(BaseModel):
    """A task of a job without a schema, with the content formats the job asked for (ARCHITECTURE §8.5). The formats
    are members only when the task reached its page and its capture is still kept."""

    task_id: UrlTaskId
    url: str
    status: TaskStatus
    outcome: TaskOutcome | None
    capture_id: CaptureId | None
    final_url: str | None
    fetched_at: datetime | None
    markdown: str | None = format_member()
    html: str | None = format_member()
    raw_html: str | None = format_member()
    links: list[str] | None = format_member()
    metadata: PageMetadata | None = format_member()


class PageOutputPage(BaseModel):
    """One page of a job's tasks, oldest first; `next_cursor` is the `cursor` of the page after it, None on the
    last."""

    model_config = ConfigDict(frozen=True)

    items: list[PageOutput]
    next_cursor: UrlTaskId | None


class ResultsQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: uuid.UUID | None = None  # a record's id; a task's for page outputs
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
    [summary] = await _summaries(conn, [job])
    return summary


async def list_jobs(conn: AsyncConnection, query: JobListQuery) -> JobPage:
    """The page of jobs after `query.cursor` (the first page without one) of its kind and status. Jobs are ordered by
    id, newest first (ids are UUIDv7, RFC 9562 §5.7, so their order is creation order)."""
    statement = select(*_JOB_COLUMNS).order_by(Job.id.desc()).limit(query.limit + 1)
    if query.kind is not None:
        statement = statement.where(Job.kind == query.kind)
    if query.status is not None:
        statement = statement.where(Job.status == query.status)
    if query.cursor is not None:
        statement = statement.where(Job.id < query.cursor)
    rows = (await conn.execute(statement)).mappings().all()
    items = await _summaries(conn, rows[: query.limit])
    return JobPage(items=items, next_cursor=items[-1].id if len(rows) > query.limit else None)


async def _summaries(conn: AsyncConnection, jobs: Sequence[RowMapping]) -> list[JobSummary]:
    """The summaries of `jobs` (rows of `_JOB_COLUMNS`), in their order, with their tasks counted in one query."""
    statuses = {job["id"]: dict.fromkeys(get_args(TaskStatus), 0) for job in jobs}
    outcomes = {job["id"]: dict.fromkeys(get_args(TaskOutcome), 0) for job in jobs}
    if jobs:
        rows = await conn.execute(
            select(UrlTask.job_id, UrlTask.status, UrlTask.outcome, func.count())
            .where(UrlTask.job_id.in_(list(statuses)))
            .group_by(UrlTask.job_id, UrlTask.status, UrlTask.outcome)
        )
        for job_id, status, outcome, n in rows.all():
            statuses[job_id][status] += n
            if outcome is not None:
                outcomes[job_id][outcome] += n
    return [
        JobSummary(**job, counts=TaskCounts(**statuses[job["id"]]), outcomes=OutcomeCounts(**outcomes[job["id"]]))
        for job in jobs
    ]


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
    locked = select(Job.status, Job.kind, Job.request).where(Job.id == job_id).with_for_update()
    job = (await conn.execute(locked)).one()
    if not JOB_TRANSITIONS[job.status]:
        return  # it ended while its tasks were cancelled
    await conn.execute(update(Job).where(Job.id == job_id).values(cancel_requested=True))
    if job.kind == "learn":
        # A learn job has no tasks. A started run ends itself on `cancel_requested` (`learning._finish`); one that
        # never started ends its state's run here, as a cancelled run does (D-0622).
        if job.status == "queued":
            await learning_failed(conn, StateKey.from_request(job.request))
            await transition_job(conn, job_id, "cancelled")
    elif job.status == "queued":
        # No task of it was ever claimed: a claim starts its job in the same transaction.
        await transition_job(conn, job_id, "cancelled")
    else:
        await settle_job(conn, job_id)


async def job_results(
    conn: AsyncConnection, job_id: JobId, query: ResultsQuery, *, store: ObjectStore
) -> RecordPage | ExportPage | PageOutputPage:
    """The job's records after `query.cursor`, newest first, in the field shape of `/v1/records` (`json`) or exported
    in the schema's columns. Values are the stored published values, unchanged (INV-27). A job without a schema
    answers `json` with its page outputs, made from the captures in `store`, and has nothing to export."""
    job = (await conn.execute(select(Job.schema_id, Job.request).where(Job.id == job_id))).one_or_none()
    if job is None:
        raise JobNotFound(f"no job {job_id}")
    if job.schema_id is None:
        if query.format != "json":
            raise NotExportable(f"job {job_id} has no schema, so it has no records to export")
        return await _page_outputs(conn, store, job_id, job.request.get("formats", []), query)
    cursor = None if query.cursor is None else RecordId(query.cursor)
    page = await list_records(conn, RecordFilter(job_id=job_id, cursor=cursor, limit=query.limit))
    if query.format == "json":
        return page
    schema = await registry.get_by_id(conn, job.schema_id)
    content = export_records(query.format, schema, [_content(record) for record in page.items])
    return ExportPage(format=query.format, content=content, next_cursor=page.next_cursor)


# A task with its capture's columns, None where it has none (`_page_outputs`).
_TaskRow = Row[
    UrlTaskId,
    str,
    TaskStatus,
    TaskOutcome | None,
    CaptureId | None,
    str | None,
    datetime | None,
    BlockClass | None,
    str | None,
]


async def _page_outputs(
    conn: AsyncConnection, store: ObjectStore, job_id: JobId, formats: list[PageFormat], query: ResultsQuery
) -> PageOutputPage:
    after = () if query.cursor is None else (UrlTask.id > query.cursor,)
    columns = (
        UrlTask.id,
        UrlTask.url,
        UrlTask.status,
        UrlTask.outcome,
        UrlTask.capture_id,
        Capture.final_url,
        Capture.fetched_at,
        Capture.block_class,
        Capture.object_key,
    )
    statement = (
        select(*columns)
        .outerjoin(Capture, Capture.id == UrlTask.capture_id)
        .where(UrlTask.job_id == job_id, *after)
        .order_by(UrlTask.id)
        .limit(query.limit + 1)
    )
    rows: list[_TaskRow] = list((await conn.execute(statement)).all())
    items = [await _page_output(store, row, formats) for row in rows[: query.limit]]
    return PageOutputPage(items=items, next_cursor=items[-1].task_id if len(rows) > query.limit else None)


async def _page_output(store: ObjectStore, row: _TaskRow, formats: list[PageFormat]) -> PageOutput:
    output = PageOutput(
        task_id=row.id,
        url=row.url,
        status=row.status,
        outcome=row.outcome,
        capture_id=row.capture_id,
        final_url=row.final_url,
        fetched_at=row.fetched_at,
    )
    # Only a page the task reached and extracted has formats (SPEC-07 §4.8): a crawl's `links_only` page was reached,
    # for its links, and is never extracted (ARCHITECTURE §13.2).
    if row.outcome != "extracted" or row.object_key is None or row.final_url is None:
        return output
    made = await asyncio.to_thread(_formats_of, store, row.object_key, row.final_url, formats)
    return output if made is None else output.model_copy(update=made)


def _formats_of(store: ObjectStore, object_key: str, final_url: str, formats: list[PageFormat]) -> Formats | None:
    """The formats of the capture at `object_key`, from one parse of it (INV-26); None once its bundle is gone."""
    try:
        bundle = decode(store.get(object_key))
    except ObjectNotFound:
        return None
    return page_formats(ParsedPage.of(bundle), final_url, formats)


def _content(record: StoredRecord) -> RecordContent:
    meta = {name: FieldMeta(**field.model_dump(exclude={"value"})) for name, field in record.fields.items()}
    data = {name: field.value for name, field in record.fields.items() if field.status == "published"}
    return RecordContent(data=data, field_meta=meta, complete=record.complete)
