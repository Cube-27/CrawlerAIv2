"""Offline re-extraction (jobs spec, "Job outcome summary"): the records the current engine makes again from the
captures a job stored, with no network and no LLM (the replay of one capture, `services.captures.replay`, whose
`extract_page` the worker and the evaluation harness run too). Nothing is stored: it reports the fields' statuses
beside those the job stored, so a change to extraction or resolution is read on a job's own pages.
"""

from collections import Counter
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import CaptureId, JobId, UrlTask
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services import captures
from crawlerai.services.captures import CaptureNotFound, NotReplayable
from crawlerai.services.job_outcomes import FieldTally, stored_field_tally
from crawlerai.services.jobs import get_job
from crawlerai.storage.base import ObjectStore


class Reextraction(BaseModel):
    """A job's captures extracted again: how many were, and how many were left out (no record was made from the
    capture, or it expired), and the fields now beside the fields as stored."""

    model_config = ConfigDict(frozen=True)

    id: JobId
    captures: int
    replayed: int
    skipped: int
    stored: FieldTally
    now: FieldTally


async def reextract_job(
    engine: AsyncEngine,
    store: ObjectStore,
    data: EngineData,
    job_id: JobId,
    progress: Callable[[int, int], None] | None = None,
) -> Reextraction:
    """Extract the captures of the job's tasks again, one after another, with the current engine and each site's active
    config; `JobNotFound` for no such job. `progress(done, total)` follows each capture."""
    async with engine.connect() as conn:
        await get_job(conn, job_id)  # `JobNotFound`
        ids = (
            await conn.execute(
                select(UrlTask.capture_id)
                .where(UrlTask.job_id == job_id, UrlTask.capture_id.is_not(None))
                .distinct()
                .order_by(UrlTask.capture_id)
            )
        ).scalars()
        capture_ids: list[CaptureId] = [c for c in ids if c is not None]
        stored = await stored_field_tally(conn, job_id)
    now = Counter[tuple[str, str | None]]()
    replayed = 0
    for done, capture_id in enumerate(capture_ids, start=1):
        try:
            records = await captures.replay(engine, store, data, capture_id, job_id)
        except (CaptureNotFound, NotReplayable):
            records = None
        if records is not None:
            replayed += 1
            now.update((field.status, field.reason) for record in records for field in record.fields.values())
        if progress is not None:
            progress(done, len(capture_ids))
    return Reextraction(
        id=job_id,
        captures=len(capture_ids),
        replayed=replayed,
        skipped=len(capture_ids) - replayed,
        stored=stored,
        now=FieldTally.of(now),
    )
