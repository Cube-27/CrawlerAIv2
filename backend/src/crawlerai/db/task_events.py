"""The run events of a finished task (SPEC-10 §4.2, ARCHITECTURE §17), recorded from what the task left in its rows,
in the transaction that finishes it: `task_fetched` for the page it fetched, `task_extracted` for its extraction, and
`task_abstained` for the fields its records abstained on. Handlers write nothing for them.

Payloads carry the task's URL: the caller supplied the job, so the stream returns it unredacted (§4.2).
"""

from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import record_event
from crawlerai.db.models import Capture, Extraction, Record, UrlTask, UrlTaskId

TASK_FETCHED: Final = "task_fetched"
TASK_EXTRACTED: Final = "task_extracted"
TASK_ABSTAINED: Final = "task_abstained"
# `record.field_meta[field].status` of a field the resolver declined to publish (ARCHITECTURE §10).
_ABSTAINED: Final = "abstained"


async def record_task_events(conn: AsyncConnection, task_id: UrlTaskId) -> None:
    task = (
        await conn.execute(
            select(
                UrlTask.job_id, UrlTask.url, UrlTask.outcome, UrlTask.capture_id, Capture.method, Capture.block_class
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
    if extraction is None:
        return
    payload = {"url": task.url, "outcome": task.outcome, "mode": extraction.mode, "llm_calls": extraction.llm_calls}
    await record_event(conn, task.job_id, TASK_EXTRACTED, payload)
    query = select(Record.field_meta).where(Record.extraction_id == extraction.id)
    metas: list[dict[str, Any]] = list((await conn.execute(query)).scalars())
    abstained = sorted({field for meta in metas for field, entry in meta.items() if entry["status"] == _ABSTAINED})
    if abstained:
        await record_event(conn, task.job_id, TASK_ABSTAINED, {"url": task.url, "fields": abstained})
