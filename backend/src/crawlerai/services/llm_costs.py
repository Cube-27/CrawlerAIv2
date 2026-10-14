"""The LLM cost history (SPEC-06 §4.8, SPEC-10 §4.2): the LLM calls jobs made, with their tokens and an estimated
cost, by day, by provider, model and prompt kind, and by job. `GET /v1/usage/llm`, `GET /v1/usage/llm/jobs` and the
job summary's `llm_cost_usd` answer with these. The cost is an estimate for visibility, not billing (ARCHITECTURE
§1).

The client records each answered call as three `usage_event` rows (`llm_calls`, `llm_tokens_in`, `llm_tokens_out`)
that share its metadata (SPEC-06 §4.2). A row's tokens are priced at the price that applied to its call
(`crawlerai.llm.pricing`): its provider and model, its date, and, for a model priced by prompt length, the call's
input tokens (`metadata.tokens_in` on the output row). Tokens no price applies to are counted as unpriced, and any sum
that includes them has no estimate (`estimated_usd` null) rather than a partial one (C7).

`usage_event` has no time column; an event's time is its id's, a UUIDv7 whose leading 48 bits are its creation time
in Unix milliseconds (RFC 9562 §5.7). A range of UTC days is therefore a range of ids, which the primary key serves.
Calls made without a job (the labeling pre-fill, an eval replay's recording) write no usage event (SPEC-06 §4.2), so
they are not in this history.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    DateTime,
    FromClause,
    Numeric,
    Row,
    Select,
    Text,
    and_,
    case,
    cast,
    column,
    false,
    func,
    literal,
    or_,
    select,
    values,
)
from sqlalchemy.dialects.postgresql import BIT
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.ids import uuid7_floor
from crawlerai.db.models import Job, JobId, JobKind, UsageEvent
from crawlerai.llm.pricing import TOKENS_PER_PRICE_UNIT, Pricing
from crawlerai.services.records import MAX_PAGE

DEFAULT_RANGE_DAYS: Final = 30
MAX_RANGE_DAYS: Final = 366  # a year, leap or not
TOP_JOBS: Final = 10
_TOKENS: Final = ("llm_tokens_in", "llm_tokens_out")


def _today() -> date:
    return datetime.now(UTC).date()


class CostQuery(BaseModel):
    """A range of UTC days, both ends included: by default the 30 days through today."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: date | None = None  # default: 29 days before `end`
    end: date | None = None  # default: today

    @property
    def last_day(self) -> date:
        return _today() if self.end is None else self.end

    @property
    def first_day(self) -> date:
        return self.last_day - timedelta(days=DEFAULT_RANGE_DAYS - 1) if self.start is None else self.start

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if self.last_day < self.first_day:
            raise ValueError("the range ends before it starts")
        if (self.last_day - self.first_day).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f"the range spans more than {MAX_RANGE_DAYS} days")
        return self


class JobCostQuery(CostQuery):
    cursor: JobId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


class LLMUsage(BaseModel):
    """LLM calls and their tokens, with their estimated cost in USD: null when some of the tokens have no price
    (`unpriced_tokens`), never a guess."""

    model_config = ConfigDict(frozen=True)

    calls: int
    tokens_in: int
    tokens_out: int
    unpriced_tokens: int
    estimated_usd: float | None


class DayUsage(LLMUsage):
    day: date  # a UTC day


class ModelRoleUsage(LLMUsage):
    """The calls to one model for one role (`prompt_kind`, SPEC-06 §4.2)."""

    provider: str | None
    model: str | None
    prompt_kind: str | None


class JobUsage(LLMUsage):
    job_id: JobId
    kind: JobKind
    created_at: datetime


class CostReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: date
    end: date
    currency: Literal["USD"] = "USD"
    total: LLMUsage
    days: list[DayUsage]  # every day of the range, oldest first
    breakdown: list[ModelRoleUsage]  # costliest first; unknown costs first of all
    top_jobs: list[JobUsage]  # the costliest jobs, at most `TOP_JOBS`


class JobCostPage(BaseModel):
    """One page of the jobs with LLM calls in the range, newest first; `next_cursor` is the `cursor` of the page after
    it, None on the last."""

    model_config = ConfigDict(frozen=True)

    items: list[JobUsage]
    next_cursor: JobId | None


async def cost_report(conn: AsyncConnection, query: CostQuery, pricing: Pricing) -> CostReport:
    costed = _costed(pricing, (query.first_day, query.last_day))
    total = (await conn.execute(select(*_sums(costed)))).one()
    by_day = {row.day: row for row in await _grouped(conn, costed, costed.c.day)}
    breakdown = await _grouped(conn, costed, costed.c.provider, costed.c.model, costed.c.prompt_kind)
    top = await conn.execute(
        _jobs(costed).order_by(func.sum(costed.c.usd).desc(), costed.c.job_id.desc()).limit(TOP_JOBS)
    )
    first, last = query.first_day, query.last_day
    days = [first + timedelta(days=n) for n in range((last - first).days + 1)]
    return CostReport(
        start=first,
        end=last,
        total=LLMUsage(**_usage(total)),
        days=[DayUsage(day=day, **(_usage(by_day[day]) if day in by_day else _NO_USAGE)) for day in days],
        breakdown=sorted(
            (
                ModelRoleUsage(provider=row.provider, model=row.model, prompt_kind=row.prompt_kind, **_usage(row))
                for row in breakdown
            ),
            key=lambda usage: (usage.estimated_usd is not None, -(usage.estimated_usd or 0), -usage.calls),
        ),
        top_jobs=[_job_usage(row) for row in top.all()],
    )


async def job_costs(conn: AsyncConnection, query: JobCostQuery, pricing: Pricing) -> JobCostPage:
    """The page of jobs after `query.cursor` (the first page without one) with LLM calls in the range. Jobs are ordered
    by id, newest first (ids are UUIDv7, RFC 9562 §5.7, so their order is creation order)."""
    costed = _costed(pricing, (query.first_day, query.last_day))
    statement = _jobs(costed).order_by(costed.c.job_id.desc()).limit(query.limit + 1)
    if query.cursor is not None:
        statement = statement.where(costed.c.job_id < query.cursor)
    rows = (await conn.execute(statement)).all()
    items = [_job_usage(row) for row in rows[: query.limit]]
    return JobCostPage(items=items, next_cursor=items[-1].job_id if len(rows) > query.limit else None)


async def costs_of_jobs(conn: AsyncConnection, job_ids: Sequence[JobId], pricing: Pricing) -> dict[JobId, float | None]:
    """Each job's estimated LLM cost over all its calls: 0 for a job without calls, None when some tokens have no
    price."""
    costs: dict[JobId, float | None] = dict.fromkeys(job_ids, 0.0)
    if job_ids:
        costed = _costed(pricing, None, job_ids)
        for row in await _grouped(conn, costed, costed.c.job_id):
            costs[row.job_id] = _usage(row)["estimated_usd"]
    return costs


_NO_USAGE: Final[dict[str, Any]] = {
    "calls": 0,
    "tokens_in": 0,
    "tokens_out": 0,
    "unpriced_tokens": 0,
    "estimated_usd": 0.0,
}


def _usage(row: Row[Any]) -> dict[str, Any]:
    unpriced = int(row.unpriced_tokens)
    return {
        "calls": int(row.calls),
        "tokens_in": int(row.tokens_in),
        "tokens_out": int(row.tokens_out),
        "unpriced_tokens": unpriced,
        "estimated_usd": None if unpriced else float(row.usd),
    }


def _job_usage(row: Row[Any]) -> JobUsage:
    return JobUsage(job_id=row.job_id, kind=row.kind, created_at=row.created_at, **_usage(row))


def _sums(costed: FromClause) -> tuple[ColumnElement[Any], ...]:
    def total(name: str) -> ColumnElement[Any]:
        return func.coalesce(func.sum(costed.c[name]), 0).label(name)

    return tuple(total(name) for name in ("calls", "tokens_in", "tokens_out", "unpriced_tokens", "usd"))


async def _grouped(conn: AsyncConnection, costed: FromClause, *keys: ColumnElement[Any]) -> Sequence[Row[Any]]:
    return (await conn.execute(select(*keys, *_sums(costed)).group_by(*keys))).all()


def _jobs(costed: FromClause) -> Select[Any]:
    """The sums per job, with the job's kind and creation time."""
    return (
        select(costed.c.job_id, Job.kind, Job.created_at, *_sums(costed))
        .join(Job, Job.id == costed.c.job_id)
        .group_by(costed.c.job_id, Job.kind, Job.created_at)
    )


def _event_time() -> ColumnElement[datetime]:
    """The event's creation time: its UUIDv7 id's leading 48 bits, Unix milliseconds (RFC 9562 §5.7)."""
    hex_ms = func.substr(func.replace(cast(UsageEvent.id, Text), "-", ""), 1, 12)
    unix_ms = cast(cast(literal("x") + hex_ms, BIT(48)), BigInteger)
    return func.to_timestamp(unix_ms / 1000.0)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def _price_table(pricing: Pricing) -> FromClause:
    """The prices as a table: one row per price, its dates as UTC midnights."""
    columns = (
        column("provider", Text),
        column("model", Text),
        column("valid_from", DateTime(timezone=True)),
        column("valid_until", DateTime(timezone=True)),
        column("tiered", BigInteger),
        column("min_prompt", BigInteger),
        column("max_prompt", BigInteger),
        column("usd_in", Numeric),
        column("usd_out", Numeric),
    )
    rows = [
        (
            p.provider,
            p.model,
            _midnight(p.effective_from),
            None if p.effective_until is None else _midnight(p.effective_until),
            int(p.tiered),
            p.min_prompt_tokens,
            p.max_prompt_tokens,
            p.input_usd_per_mtok,
            p.output_usd_per_mtok,
        )
        for p in pricing.prices
    ]
    if not rows:  # no prices: an empty table of the same columns
        return select(*(literal(None, c.type).label(c.name) for c in columns)).where(false()).subquery("price")
    return values(*columns, name="price").data(rows)


def _costed(pricing: Pricing, days: tuple[date, date] | None, job_ids: Sequence[JobId] | None = None) -> FromClause:
    """One row per LLM usage event of the UTC days `days` (both included; all when None) and of `job_ids` (all when
    None): its day, job, provider, model and prompt kind, its calls or tokens, its priced cost and its unpriced
    tokens."""
    event = UsageEvent
    at = _event_time()
    price = _price_table(pricing)
    is_tokens = event.resource.in_(_TOKENS)
    # The call's prompt length: the input row's quantity, or the metadata the client puts on each of its rows.
    prompt_tokens = case(
        (event.resource == "llm_tokens_in", event.quantity),
        else_=cast(event.metadata_["tokens_in"].astext, BigInteger),
    )
    applies = and_(
        is_tokens,
        price.c.provider == event.provider,
        price.c.model == event.model_or_pool,
        at >= price.c.valid_from,
        or_(price.c.valid_until.is_(None), at < price.c.valid_until),
        or_(
            price.c.tiered == 0,
            and_(
                prompt_tokens >= price.c.min_prompt,
                or_(price.c.max_prompt.is_(None), prompt_tokens <= price.c.max_prompt),
            ),
        ),
    )
    per_mtok = case((event.resource == "llm_tokens_in", price.c.usd_in), else_=price.c.usd_out)

    def quantity_if(condition: ColumnElement[bool]) -> ColumnElement[int]:
        return case((condition, event.quantity), else_=0)

    priced = price.c.provider.is_not(None)
    statement = (
        select(
            func.date(func.timezone("UTC", at)).label("day"),
            event.job_id,
            event.provider,
            event.model_or_pool.label("model"),
            event.metadata_["prompt_kind"].astext.label("prompt_kind"),
            quantity_if(event.resource == "llm_calls").label("calls"),
            quantity_if(event.resource == "llm_tokens_in").label("tokens_in"),
            quantity_if(event.resource == "llm_tokens_out").label("tokens_out"),
            quantity_if(and_(is_tokens, ~priced)).label("unpriced_tokens"),
            case((priced, event.quantity * per_mtok / TOKENS_PER_PRICE_UNIT), else_=Decimal(0)).label("usd"),
        )
        .select_from(event)
        .outerjoin(price, applies)
        .where(event.resource.in_(("llm_calls", *_TOKENS)))
    )
    if days is not None:
        first, last = days
        statement = statement.where(
            event.id >= uuid7_floor(_midnight(first)), event.id < uuid7_floor(_midnight(last + timedelta(days=1)))
        )
    if job_ids is not None:
        statement = statement.where(event.job_id.in_(list(job_ids)))
    return statement.subquery("costed")
