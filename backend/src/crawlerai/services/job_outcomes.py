"""A job's outcomes (jobs spec, "Job outcome summary"): how many of its pages ended with each outcome, and how many
of the fields of its records have each status, with the reasons the unpublished ones give. Both are counted from what
the job stored (`url_task.outcome`, `record.field_meta`): no table of its own. `GET /v1/jobs/{id}/outcomes` and
`crawlerai jobs summary` answer with it; `crawlerai jobs reextract` counts the same fields of the records the current
engine makes again from the job's stored captures (`services.reextract`).
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, cast, get_args

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Text, column, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import JobId, Record, TaskRecord, UrlTask
from crawlerai.resolve.types import FieldStatus
from crawlerai.services.jobs import OutcomeCounts, get_job


class FieldCounts(BaseModel):
    """How many fields of a job's records have each status (resolution spec)."""

    model_config = ConfigDict(frozen=True)

    published: int
    missing: int
    conflict: int
    abstained: int
    interaction_required: int


class FieldTally(BaseModel):
    """The fields of some records by status, and the reason of each unpublished one, counted."""

    model_config = ConfigDict(frozen=True)

    statuses: FieldCounts
    # Per reason, the fields that are not published and give it (`no_candidates`, `out_of_stock`, `script_rendered`...).
    reasons: dict[str, int]

    @classmethod
    def of(cls, counts: Mapping[tuple[str, str | None], int]) -> "FieldTally":
        """The tally of `counts`, the number of fields per (status, reason)."""
        by_status = Counter[str]()
        reasons = Counter[str]()
        for (status, reason), n in counts.items():
            by_status[status] += n
            if status != "published" and reason is not None:
                reasons[reason] += n
        return cls(
            statuses=FieldCounts(**{status: by_status[status] for status in get_args(FieldStatus)}),
            reasons=dict(sorted(reasons.items())),
        )

    @classmethod
    def of_metas(cls, metas: Iterable[Mapping[str, Mapping[str, Any]]]) -> "FieldTally":
        """The tally of records' `field_meta` documents."""
        return cls.of(Counter((meta["status"], meta.get("reason")) for record in metas for meta in record.values()))


class JobOutcomes(BaseModel):
    """A job's pages by outcome and the fields of its records by status."""

    model_config = ConfigDict(frozen=True)

    id: JobId
    pages: OutcomeCounts
    fields: FieldCounts
    reasons: dict[str, int]


async def job_outcomes(conn: AsyncConnection, job_id: JobId) -> JobOutcomes:
    """The job's outcome counts; `JobNotFound` for no such job."""
    job = await get_job(conn, job_id)
    tally = await stored_field_tally(conn, job_id)
    return JobOutcomes(id=job_id, pages=job.outcomes, fields=tally.statuses, reasons=tally.reasons)


async def stored_field_tally(conn: AsyncConnection, job_id: JobId) -> FieldTally:
    """The fields of the records the job's tasks stand for, by status and reason, in one aggregate query."""
    field = func.jsonb_each(Record.field_meta).table_valued(column("key", Text), column("value", JSONB)).lateral()
    status, reason = field.c.value["status"].astext, field.c.value["reason"].astext
    rows = await conn.execute(
        select(status, reason, func.count().label("n"))
        .select_from(UrlTask)
        .join(TaskRecord, TaskRecord.url_task_id == UrlTask.id)
        .join(Record, Record.id == TaskRecord.record_id)
        .join(field, true())
        .where(UrlTask.job_id == job_id)
        .group_by(status, reason)
    )
    counts: Counter[tuple[str, str | None]] = Counter()
    for status_, reason_, n in rows.all():
        counts[cast(str, status_), cast("str | None", reason_)] += cast(int, n)
    return FieldTally.of(counts)
