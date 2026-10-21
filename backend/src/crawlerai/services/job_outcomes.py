"""A job's outcomes (jobs spec, "Job outcome summary"): how many of its pages ended with each outcome, and how many
of the fields of its records have each status, with the reasons the unpublished ones give, and per field how many pages
fetched over HTTP alone left it `missing/no_candidates`, with the next step when the job did not ask for rendering
(`render.mode: locate`), also named when a listing page fetched over HTTP alone listed nothing, and per
detect-and-report signal how many of its pages raised it (`content.signals`; names only, no URLs), and how many of its
records are `new`, `changed` or `same` against their entities' previous records (jobs spec, "Page delta"). All are
counted
from what the job stored (`url_task.outcome`, `record.field_meta`, `capture`, `extraction.diagnostics`): no table of
its own. `GET /v1/jobs/{id}/outcomes` and
`crawlerai jobs summary` answer with it; `crawlerai jobs reextract` counts the same fields of the records the current
engine makes again from the job's stored captures (`services.reextract`).
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Final, cast, get_args

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Text, column, false, func, select, true
from sqlalchemy.dialects.postgresql import JSONB, distinct_on
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.content.signals import PREFIX as SIGNAL_PREFIX
from crawlerai.content.signals import SIGNALS, Signal
from crawlerai.db.models import Capture, Extraction, Job, JobId, Record, RecordDelta, TaskRecord, UrlTask
from crawlerai.resolve.page_state import NO_CANDIDATES
from crawlerai.resolve.types import FieldStatus
from crawlerai.services.jobs import OutcomeCounts, get_job

# The next step for fields HTTP pages do not carry (rest-api spec, "Render mode"): fields and outcomes, no internals.
LOCATE_HINT: Final = "render.mode: locate"


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
    # Per reason, the fields that are not published and give it (`no_candidates`, `out_of_stock`, `render_bound`...).
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


class DeltaCounts(BaseModel):
    """How many of a job's records are each delta (jobs spec, "Page delta")."""

    model_config = ConfigDict(frozen=True)

    new: int
    changed: int
    same: int


class JobOutcomes(BaseModel):
    """A job's pages by outcome and the fields of its records by status."""

    model_config = ConfigDict(frozen=True)

    id: JobId
    pages: OutcomeCounts
    fields: FieldCounts
    reasons: dict[str, int]
    # Per field, the records of pages no render ran for that left it `missing` with reason `no_candidates`.
    missing_unrendered: dict[str, int]
    # The next step for those fields, and for listing pages over HTTP that listed nothing, when the job's `render.mode`
    # is `off`; None without any or when it asked for one.
    hint: str | None
    # Per detect-and-report signal, the job's pages an extraction found it on; a signal no page raised is left out.
    signals: dict[Signal, int]
    records: DeltaCounts


async def job_outcomes(conn: AsyncConnection, job_id: JobId) -> JobOutcomes:
    """The job's outcome counts; `JobNotFound` for no such job."""
    job = await get_job(conn, job_id)
    tally = await stored_field_tally(conn, job_id)
    missing = await _missing_unrendered(conn, job_id)
    unlisted = await _listed_nothing_unrendered(conn, job_id)
    request: dict[str, Any] = (await conn.execute(select(Job.request).where(Job.id == job_id))).scalar_one()
    mode = (request.get("render") or {}).get("mode", "off")
    return JobOutcomes(
        id=job_id,
        pages=job.outcomes,
        fields=tally.statuses,
        reasons=tally.reasons,
        missing_unrendered=missing,
        hint=LOCATE_HINT if (missing or unlisted) and mode == "off" else None,
        signals=await _signals(conn, job_id),
        records=await _deltas(conn, job_id),
    )


async def _deltas(conn: AsyncConnection, job_id: JobId) -> DeltaCounts:
    """The job's records by delta, each once, as the first task of the job that stood for it saw it (as
    `services.records` lists them)."""
    first = (
        select(TaskRecord.record_id, TaskRecord.delta)
        .join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
        .where(UrlTask.job_id == job_id)
        .ext(distinct_on(TaskRecord.record_id))
        .order_by(TaskRecord.record_id, TaskRecord.created_at, TaskRecord.url_task_id)
        .subquery()
    )
    rows = await conn.execute(select(first.c.delta, func.count()).group_by(first.c.delta))
    counts = {cast(str, delta): cast(int, n) for delta, n in rows.all()}
    return DeltaCounts(**{delta: counts.get(delta, 0) for delta in get_args(RecordDelta)})


async def _signals(conn: AsyncConnection, job_id: JobId) -> dict[Signal, int]:
    """Per signal, the job's tasks with an extraction whose diagnostics name it (`content.signals.PREFIX`)."""
    note = func.jsonb_array_elements_text(Extraction.diagnostics).table_valued(column("value", Text)).lateral()
    rows = await conn.execute(
        select(note.c.value, func.count(UrlTask.id.distinct()))
        .select_from(UrlTask)
        .join(Extraction, Extraction.url_task_id == UrlTask.id)
        .join(note, true())
        .where(UrlTask.job_id == job_id, note.c.value.startswith(SIGNAL_PREFIX, autoescape=True))
        .group_by(note.c.value)
    )
    counts = {cast(str, note_).removeprefix(SIGNAL_PREFIX): cast(int, n) for note_, n in rows.all()}
    return {signal: counts[signal] for signal in SIGNALS if signal in counts}


async def _missing_unrendered(conn: AsyncConnection, job_id: JobId) -> dict[str, int]:
    """Per field, the records the job's tasks stand for whose page was fetched over HTTP with no browser attempt
    (`capture.method`, `fetch_policy.attempts`) and left it `missing/no_candidates`: a render may show it."""
    field = func.jsonb_each(Record.field_meta).table_valued(column("key", Text), column("value", JSONB)).lateral()
    browser_tried = Capture.fetch_policy["attempts"].contains([{"method": "browser"}])
    standing = (
        select(TaskRecord.record_id)
        .join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
        .join(Capture, Capture.id == UrlTask.capture_id)
        .where(UrlTask.job_id == job_id, Capture.method == "http", ~func.coalesce(browser_tried, false()))
        .distinct()
        .subquery()
    )
    rows = await conn.execute(
        select(field.c.key, func.count())
        .select_from(standing)
        .join(Record, Record.id == standing.c.record_id)
        .join(field, true())
        .where(field.c.value["status"].astext == "missing", field.c.value["reason"].astext == NO_CANDIDATES)
        .group_by(field.c.key)
        .order_by(field.c.key)
    )
    return {cast(str, key): cast(int, n) for key, n in rows.all()}


async def _listed_nothing_unrendered(conn: AsyncConnection, job_id: JobId) -> int:
    """The job's listing pages fetched over HTTP with no browser attempt that listed nothing (`partial` with no record,
    `store_page_record`): a render may show their rows."""
    browser_tried = Capture.fetch_policy["attempts"].contains([{"method": "browser"}])
    kept = select(TaskRecord.url_task_id).where(TaskRecord.url_task_id == UrlTask.id).exists()
    found = await conn.execute(
        select(func.count())
        .select_from(UrlTask)
        .join(Capture, Capture.id == UrlTask.capture_id)
        .where(
            UrlTask.job_id == job_id,
            UrlTask.page_kind == "listing",
            UrlTask.outcome == "partial",
            Capture.method == "http",
            ~func.coalesce(browser_tried, false()),
            ~kept,
        )
    )
    count: int = found.scalar_one()
    return count


async def stored_field_tally(conn: AsyncConnection, job_id: JobId) -> FieldTally:
    """The fields of the records the job's tasks stand for, by status and reason, in one aggregate query."""
    field = func.jsonb_each(Record.field_meta).table_valued(column("key", Text), column("value", JSONB)).lateral()
    status, reason = field.c.value["status"].astext, field.c.value["reason"].astext
    # Each record once, though several tasks may stand for it (a task whose record equals the latest version links it).
    standing = (
        select(TaskRecord.record_id)
        .join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
        .where(UrlTask.job_id == job_id)
        .distinct()
        .subquery()
    )
    rows = await conn.execute(
        select(status, reason, func.count().label("n"))
        .select_from(standing)
        .join(Record, Record.id == standing.c.record_id)
        .join(field, true())
        .group_by(status, reason)
    )
    counts: Counter[tuple[str, str | None]] = Counter()
    for status_, reason_, n in rows.all():
        counts[cast(str, status_), cast("str | None", reason_)] += cast(int, n)
    return FieldTally.of(counts)
