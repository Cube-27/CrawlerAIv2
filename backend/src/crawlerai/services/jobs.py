"""The jobs service (SPEC-10 §4.2, ARCHITECTURE §13.1): the jobs a page at a time, a job's summary, its cancel, and
its results a page at a time. `GET /v1/jobs`, `GET/DELETE /v1/jobs/{id}`, `GET /v1/jobs/{id}/results` and the MCP
status tools answer with these.

The results of a job with a schema are its records. Those of a job without one are its page outputs: each task's
content formats, made from its capture when they are read. A format is a function of the capture alone (ARCHITECTURE
§15), so nothing else is stored, and a page's outputs go when its capture expires. Either kind of job also answers
`json_values` (SPEC-14 §4.4): each task with the clean records its page stands for.
"""

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, NamedTuple, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import RowMapping, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.exporters.records import RecordFormat, clean_record, export_records
from crawlerai.config_ir.progressive import StateKey, learning_failed
from crawlerai.content.metadata import PageMetadata
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.core.errors import Refusal
from crawlerai.db.jobs import JOB_TRANSITIONS, transition_job
from crawlerai.db.models import (
    Capture,
    CaptureId,
    Job,
    JobId,
    JobKind,
    JobStatus,
    Record,
    RecordId,
    SchemaId,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
    UrlTask,
    UrlTaskId,
)
from crawlerai.db.paging import keyset_page
from crawlerai.db.queue import settle_job
from crawlerai.llm.pricing import default_pricing
from crawlerai.resolve.records import FieldMeta, RecordContent
from crawlerai.schemas import registry
from crawlerai.services.llm_costs import costs_of_jobs
from crawlerai.services.records import MAX_PAGE, RecordFilter, RecordPage, StoredRecord, list_records
from crawlerai.services.scrape_steps import Formats, PageFormat, format_member, page_formats
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

ResultFormat = Literal["json", "json_values", RecordFormat]
# The outcomes of a page that was reached and extracted, so its capture has metadata to show (`json_values`).
_EXTRACTED: frozenset[TaskOutcome | None] = frozenset({"extracted", "partial"})


class JobNotFound(Refusal, LookupError):
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
    # The estimated cost of its LLM calls in USD, for visibility, not billing (SPEC-06 §4.8); null when some of their
    # tokens have no price.
    llm_cost_usd: float | None
    webhook_url: str | None
    engine_version: str
    # The cancel was asked for (SPEC-01 §4.3); a running job stays running until its claimed tasks end.
    cancel_requested: bool
    # The request the job was submitted with, as stored (`job.request`): the playground shows it again to edit and
    # re-run (SPEC-14 §4.8).
    request: dict[str, Any]


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
    are members only when the task reached its page and its capture is still kept. `last_error` is why the task
    failed, or why it ended with its outcome when the outcome alone does not say (a `blocked` task's `robots`), as the
    worker recorded it: URLs redacted under `CRAWLERAI_LOG_REDACT_URLS` (SPEC-01 §4.8)."""

    task_id: UrlTaskId
    url: str
    status: TaskStatus
    outcome: TaskOutcome | None
    last_error: str | None
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


class JsonValuesItem(BaseModel):
    """A task of a job in `json_values` (SPEC-14 §4.4): its URL, its outcome (null until it ends), the clean records
    its page stands for, and, when asked for, its page's metadata. `records` is empty for a task with no record (failed,
    blocked, `links_only`, or a job without a schema). `metadata` is a member only for an extracted or partial page
    whose capture is still kept."""

    url: str
    outcome: TaskOutcome | None
    records: list[dict[str, JsonValue]]
    metadata: PageMetadata | None = format_member()


class JsonValuesPage(BaseModel):
    """One page of a job's tasks in `json_values`, oldest first; `next_cursor` is the `cursor` of the page after it,
    None on the last."""

    model_config = ConfigDict(frozen=True)

    format: Literal["json_values"]
    items: list[JsonValuesItem]
    next_cursor: UrlTaskId | None


class ResultsQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: uuid.UUID | None = None  # a record's id; a task's for page outputs and `json_values`
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)
    format: ResultFormat = "json"
    include: Literal["metadata"] | None = None  # `json_values` only

    @model_validator(mode="after")
    def _include_with_json_values(self) -> "ResultsQuery":
        if self.include is not None and self.format != "json_values":
            raise ValueError("`include` is accepted only with format=json_values")
        return self


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
    Job.cancel_requested,
    Job.request,
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
    statement = select(*_JOB_COLUMNS)
    if query.kind is not None:
        statement = statement.where(Job.kind == query.kind)
    if query.status is not None:
        statement = statement.where(Job.status == query.status)
    rows, next_cursor = await keyset_page(
        conn, statement, Job.id, after=query.cursor, limit=query.limit, descending=True
    )
    items = await _summaries(conn, [row._mapping for row in rows])
    return JobPage(items=items, next_cursor=next_cursor)


async def _summaries(conn: AsyncConnection, jobs: Sequence[RowMapping]) -> list[JobSummary]:
    """The summaries of `jobs` (rows of `_JOB_COLUMNS`), in their order, with their tasks counted in one query and
    their LLM costs summed in another, at the shipped prices."""
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
    costs = await costs_of_jobs(conn, list(statuses), default_pricing())
    return [
        JobSummary(
            **job,
            counts=TaskCounts(**statuses[job["id"]]),
            outcomes=OutcomeCounts(**outcomes[job["id"]]),
            llm_cost_usd=costs[job["id"]],
        )
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
    # FOR NO KEY UPDATE, as `settle_job` takes, so a running task's inserts that refer to the job do not hold it up.
    locked = select(Job.status, Job.kind, Job.request).where(Job.id == job_id).with_for_update(key_share=True)
    job = (await conn.execute(locked)).one()
    if not JOB_TRANSITIONS[job.status]:
        return  # it ended while its tasks were cancelled
    await conn.execute(update(Job).where(Job.id == job_id).values(cancel_requested=True))
    if job.status == "queued":
        # No task of it was ever claimed: a claim starts its job in the same transaction. A `learn` job that never
        # started ends its state's run as a cancelled run does (D-0622).
        if job.kind == "learn":
            await learning_failed(conn, StateKey.from_request(job.request))
        await transition_job(conn, job_id, "cancelled")
    elif job.kind != "learn":  # a started learn run has no tasks, and ends itself on `cancel_requested`
        await settle_job(conn, job_id)


async def job_results(
    conn: AsyncConnection, job_id: JobId, query: ResultsQuery, *, store: ObjectStore
) -> RecordPage | ExportPage | PageOutputPage | JsonValuesPage:
    """The job's records after `query.cursor`, newest first, in the field shape of `/v1/records` (`json`) or exported
    in the schema's columns. Values are the stored published values, unchanged (INV-27). A job without a schema
    answers `json` with its page outputs, made from the captures in `store`, and has nothing to export. Any job
    answers `json_values` with its tasks after `query.cursor`, oldest first."""
    job = (await conn.execute(select(Job.schema_id, Job.request).where(Job.id == job_id))).one_or_none()
    if job is None:
        raise JobNotFound(f"no job {job_id}")
    if query.format == "json_values":
        return await _json_values(conn, store, job_id, job.schema_id, query)
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


class _TaskRow(NamedTuple):
    """A task with its capture's columns, None where it has none (`_page_outputs`)."""

    id: UrlTaskId
    url: str
    status: TaskStatus
    outcome: TaskOutcome | None
    last_error: str | None
    capture_id: CaptureId | None
    final_url: str | None
    fetched_at: datetime | None
    block_class: BlockClass | None
    object_key: str | None


async def _task_rows(
    conn: AsyncConnection, job_id: JobId, query: ResultsQuery
) -> tuple[list[_TaskRow], UrlTaskId | None]:
    """The page of the job's tasks after `query.cursor`, oldest first, and the cursor of the page after it."""
    columns = (
        UrlTask.id,
        UrlTask.url,
        UrlTask.status,
        UrlTask.outcome,
        UrlTask.last_error,
        UrlTask.capture_id,
        Capture.final_url,
        Capture.fetched_at,
        Capture.block_class,
        Capture.object_key,
    )
    statement = select(*columns).outerjoin(Capture, Capture.id == UrlTask.capture_id).where(UrlTask.job_id == job_id)
    after = None if query.cursor is None else UrlTaskId(query.cursor)
    rows, next_cursor = await keyset_page(conn, statement, UrlTask.id, after=after, limit=query.limit, descending=False)
    return [_TaskRow(**row._mapping) for row in rows], next_cursor


async def _page_outputs(
    conn: AsyncConnection, store: ObjectStore, job_id: JobId, formats: list[PageFormat], query: ResultsQuery
) -> PageOutputPage:
    rows, next_cursor = await _task_rows(conn, job_id, query)
    items = [await _page_output(store, row, formats) for row in rows]
    return PageOutputPage(items=items, next_cursor=next_cursor)


async def _page_output(store: ObjectStore, row: _TaskRow, formats: list[PageFormat]) -> PageOutput:
    output = PageOutput(
        task_id=row.id,
        url=row.url,
        status=row.status,
        outcome=row.outcome,
        last_error=row.last_error,
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


async def _json_values(
    conn: AsyncConnection, store: ObjectStore, job_id: JobId, schema_id: SchemaId | None, query: ResultsQuery
) -> JsonValuesPage:
    page, next_cursor = await _task_rows(conn, job_id, query)
    # A task's records are linked when it ends, so one read before its outcome shows none.
    records = await _clean_records(conn, schema_id, [row.id for row in page if row.outcome is not None])
    items = [
        await _json_values_item(store, row, records.get(row.id, []), metadata=query.include == "metadata")
        for row in page
    ]
    return JsonValuesPage(format="json_values", items=items, next_cursor=next_cursor)


async def _clean_records(
    conn: AsyncConnection, schema_id: SchemaId | None, task_ids: list[UrlTaskId]
) -> dict[UrlTaskId, list[dict[str, JsonValue]]]:
    """The clean records each task's page stands for, oldest first: those it stored, or the latest versions of its
    entities when it found them unchanged (`task_record`, SPEC-11 §4.2, §4.4)."""
    if schema_id is None or not task_ids:
        return {}
    schema = await registry.get_by_id(conn, schema_id)
    statement = (
        select(TaskRecord.url_task_id, Record.data)
        .join(Record, Record.id == TaskRecord.record_id)
        .where(TaskRecord.url_task_id.in_(task_ids))
        .order_by(Record.id)
    )
    records: defaultdict[UrlTaskId, list[dict[str, JsonValue]]] = defaultdict(list)
    for row in await conn.execute(statement):
        records[row.url_task_id].append(clean_record(schema, row.data))
    return records


async def _json_values_item(
    store: ObjectStore, row: _TaskRow, records: list[dict[str, JsonValue]], *, metadata: bool
) -> JsonValuesItem:
    item = JsonValuesItem(url=row.url, outcome=row.outcome, records=records)
    if not metadata or row.outcome not in _EXTRACTED or row.object_key is None or row.final_url is None:
        return item
    made = await asyncio.to_thread(_formats_of, store, row.object_key, row.final_url, ["metadata"])
    return item if made is None else item.model_copy(update=made)


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
