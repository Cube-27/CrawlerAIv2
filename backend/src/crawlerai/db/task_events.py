"""The run events of a finished task (jobs spec), recorded from what the task left in its rows,
in the transaction that finishes it: `task_fetched` for the page it fetched, `task_extracted` for its extraction,
`task_abstained` for the fields the records it stands for abstained on (those it stored, or an unchanged entity's
latest version, jobs spec: `task_record`), and `task_failed`, with its `last_error`, when it failed for
good (D-0745). Handlers write nothing for them.

The same transaction owes the job's webhook its task events (`db.webhook_outbox`), when the request asked for them:
`page` for the finished task, `record` for each record version its extraction stored, and `record_changed` for each
of those that replaced an earlier version.

Payloads carry the task's URL: the caller supplied the job, so the stream returns it unredacted (§4.2).
"""

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import record_event
from crawlerai.db.models import Capture, Extraction, ExtractionId, JobId, Record, TaskRecord, UrlTask, UrlTaskId
from crawlerai.db.webhook_outbox import emit, emit_many

TASK_FETCHED: Final = "task_fetched"
TASK_EXTRACTED: Final = "task_extracted"
TASK_ABSTAINED: Final = "task_abstained"
TASK_FAILED: Final = "task_failed"
# `record.field_meta[field].status` of a field the resolver declined to publish.
_ABSTAINED: Final = "abstained"


async def record_task_events(conn: AsyncConnection, task_id: UrlTaskId) -> None:
    task = (
        await conn.execute(
            select(
                UrlTask.job_id,
                UrlTask.url,
                UrlTask.status,
                UrlTask.outcome,
                UrlTask.attempts,
                UrlTask.last_error,
                UrlTask.capture_id,
                Capture.method,
                Capture.block_class,
            )
            .outerjoin(Capture, Capture.id == UrlTask.capture_id)
            .where(UrlTask.id == task_id)
        )
    ).one()
    if task.capture_id is not None:
        payload = {"url": task.url, "method": task.method, "block_class": task.block_class}
        await record_event(conn, task.job_id, TASK_FETCHED, payload)
    # A retried task can have run the resolver more than once; its last run is the one its outcome comes from.
    extraction = (
        await conn.execute(
            select(Extraction.id, Extraction.mode, Extraction.llm_calls)
            .where(Extraction.url_task_id == task_id)
            .order_by(Extraction.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if extraction is not None:
        payload = {"url": task.url, "outcome": task.outcome, "mode": extraction.mode, "llm_calls": extraction.llm_calls}
        await record_event(conn, task.job_id, TASK_EXTRACTED, payload)
        query = select(Record.field_meta).join(TaskRecord).where(TaskRecord.url_task_id == task_id)
        metas: list[dict[str, Any]] = list((await conn.execute(query)).scalars())
        abstained = sorted({field for meta in metas for field, entry in meta.items() if entry["status"] == _ABSTAINED})
        if abstained:
            await record_event(conn, task.job_id, TASK_ABSTAINED, {"url": task.url, "fields": abstained})
    # Only the `failed` status is a failure: a task that ended `blocked` or `not_found` is `done` (persistence-storage
    # spec).
    if task.status == "failed":
        payload = {"task_id": str(task_id), "url": task.url, "attempts": task.attempts, "last_error": task.last_error}
        await record_event(conn, task.job_id, TASK_FAILED, payload)
    page = {
        "task_id": str(task_id),
        "url": task.url,
        "status": task.status,
        "outcome": task.outcome,
        "capture_id": None if task.capture_id is None else str(task.capture_id),
        "last_error": task.last_error,
    }
    await emit(conn, task.job_id, "page", page)
    if extraction is not None:
        await _emit_records(conn, task.job_id, task_id, task.url, extraction.id)


async def _emit_records(
    conn: AsyncConnection, job_id: JobId, task_id: UrlTaskId, url: str, extraction_id: ExtractionId
) -> None:
    """`record` for each record the task's last extraction stored, and `record_changed` for each new version among
    them; an unchanged record stores nothing, so it owes nothing."""
    columns = (
        Record.id,
        Record.schema_id,
        Record.entity_key,
        Record.version,
        Record.changed_fields,
        Record.complete,
        Record.data,
    )
    rows = (await conn.execute(select(*columns).where(Record.extraction_id == extraction_id).order_by(Record.id))).all()
    payloads = [
        {
            "record_id": str(row.id),
            "task_id": str(task_id),
            "url": url,
            "schema_id": str(row.schema_id),
            "entity_key": row.entity_key,
            "version": row.version,
            "changed_fields": row.changed_fields,
            "complete": row.complete,
            "data": row.data,
        }
        for row in rows
    ]
    await emit_many(conn, job_id, "record", payloads)
    await emit_many(conn, job_id, "record_changed", [payload for payload in payloads if payload["version"] > 1])
