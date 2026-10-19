"""Recurring schedules (§22 "Recurring schedule storage", admitted 2026-10-17; jobs spec): the request of a batch
scrape, crawl or extract, submitted as a job at each due time of a cron expression or an interval
(`crawlerai.core.cadence`). `/v1/schedules` and the MCP schedule tools answer with these.

Creating a schedule checks its request as its submission would, once, so a schedule that could never run is refused
at once: the targets pass the SSRF guard, and a `records` schema is resolved and stored by id, so a schema drafted from
field names is drafted once, not at every run, and an edit of the schema applies to the runs after it (INV-28 pins
it per job). A scrape is scheduled as the batch of its one URL, the queued form of a scrape; its `browser_actions` and
`timeout_s` belong to a scrape answered while the caller waits, so a request with browser actions is refused. A
`schema.prompt` is refused: its draft needs fetched pages, and a schedule runs a schema it already has. A request with
caller headers or cookies is refused too: a schedule keeps no secret value (D-1510), and a run submitted with the
placeholder it would store sends that placeholder as the value.

Running: `run_due_schedules`, a scheduler entry, locks the due schedules that are not paused (`FOR UPDATE SKIP LOCKED`),
submits each one's job through the jobs services in that same transaction, and moves it to its next due time, so a run
and its job commit together: two schedulers never submit one run twice, and a crash before the commit submits
nothing, the run being due again. A run the service refuses (a target refused by then, globs matching nothing) stores
no job: its reason is the schedule's `last_error`, and the schedule moves on. A schedule due more than once by then
runs once (`next_run`). The jobs of a schedule are ordinary jobs of its request: re-runs of one request, so record
versions, `changed_fields`, conditional fetches and `url_gone` (jobs spec) follow them as they follow a re-submission.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Self, assert_never

from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator
from sqlalchemy import Row, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.core.cadence import MIN_INTERVAL_S, Cadence, next_run
from crawlerai.core.errors import Refusal
from crawlerai.core.validation import PG_INTEGER_MAX
from crawlerai.db.models import ApiKeyId, Job, JobId, Schedule, ScheduledKind, ScheduleId
from crawlerai.db.paging import keyset_page
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.batch import BatchScrapeRequest, Placement, records_schema, submit_batch
from crawlerai.services.crawl import CrawlRequest, submit_crawl
from crawlerai.services.extract import ExtractRequest, submit_extract
from crawlerai.services.fetching import Fetching, check_targets
from crawlerai.services.records import MAX_PAGE
from crawlerai.services.scrape import RecordsUnavailable, ScrapeRequest
from crawlerai.services.scrape_steps import (
    DEFAULT_PROJECT,
    Input,
    SchemaById,
    SchemaPrompt,
    named_schema,
)

MAX_NAME: Final = 200
# Due schedules one scheduler run submits; a full batch runs again at once (`scheduler.loop`). One at a time: a run's
# submission fetches (the SSRF guard, an extract's maps) inside the transaction that holds its row.
SCHEDULE_BATCH: Final = 1
_BATCH_MEMBERS: Final = {"formats", "schema_", "page_kind", "fetch", "locale", "budget", "render_fields"}

ScheduledRequest = BatchScrapeRequest | CrawlRequest | ExtractRequest


class ScheduleNotFound(Refusal, LookupError):
    pass


class Unschedulable(Refusal):
    """The request cannot run on a schedule (a scrape's browser actions, a schema prompt, secret values)."""


class _Cadence(Input):
    """When it runs: a 5-field cron expression in `timezone` (IANA), or every `interval_s` seconds."""

    cron: str | None = None
    interval_s: int | None = Field(default=None, ge=MIN_INTERVAL_S, le=PG_INTEGER_MAX)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def _one_valid_cadence(self) -> Self:
        self.cadence()  # an `InvalidCadence` is a ValueError: a 422 naming the reason
        return self

    def cadence(self) -> Cadence:
        return Cadence(self.cron, self.interval_s, self.timezone)


class _NewScheduleFields(_Cadence):
    name: str = Field(min_length=1, max_length=MAX_NAME)
    paused: bool = False


class NewScrapeSchedule(_NewScheduleFields):
    kind: Literal["scrape"]
    request: ScrapeRequest


class NewBatchSchedule(_NewScheduleFields):
    kind: Literal["batch_scrape"]
    request: BatchScrapeRequest


class NewCrawlSchedule(_NewScheduleFields):
    kind: Literal["crawl"]
    request: CrawlRequest


class NewExtractSchedule(_NewScheduleFields):
    kind: Literal["extract"]
    request: ExtractRequest


NewSchedule = Annotated[
    NewScrapeSchedule | NewBatchSchedule | NewCrawlSchedule | NewExtractSchedule, Field(discriminator="kind")
]


class _AnySchedule(RootModel[NewSchedule]):
    pass


class ScheduleUpdate(Input):
    """The members to change; any left out stay. A new `request` comes with its `kind`; a `cron` replaces an interval
    and an `interval_s` a cron expression."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME)
    kind: Literal["scrape", "batch_scrape", "crawl", "extract"] | None = None
    request: dict[str, Any] | None = None
    cron: str | None = None
    interval_s: int | None = Field(default=None, ge=MIN_INTERVAL_S, le=PG_INTEGER_MAX)
    timezone: str | None = None

    @model_validator(mode="after")
    def _request_with_its_kind(self) -> Self:
        if (self.kind is None) != (self.request is None):
            raise ValueError("`kind` and `request` change together")
        if self.cron is not None and self.interval_s is not None:
            raise ValueError("give exactly one of `cron` and `interval_s`")
        return self


class ScheduleOut(BaseModel):
    """A schedule: its run (`kind`, and `request` as stored, a records schema by id), its cadence, whether it is
    paused, when it runs next, and its last run: when, the job it submitted, or why it submitted none."""

    model_config = ConfigDict(frozen=True)

    id: ScheduleId
    name: str
    kind: ScheduledKind
    request: dict[str, Any]
    cron: str | None
    interval_s: int | None
    timezone: str
    paused: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_job_id: JobId | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class SchedulePage(BaseModel):
    """One page of schedules, newest first; `next_cursor` is the `cursor` of the page after it, None on the last."""

    model_config = ConfigDict(frozen=True)

    items: list[ScheduleOut]
    next_cursor: ScheduleId | None


class ScheduleListQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cursor: ScheduleId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


class RunStarted(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: JobId


@dataclass(frozen=True)
class Submitting:
    """What a schedule's checks and runs submit with: the fetching (the SSRF guard, an extract's maps), the engine's
    data (a records job's pins) and the LLM client (field names drafted at creation)."""

    fetching: Fetching
    data: EngineData | None
    llm: LLMClient


def _last_job() -> Any:
    """The newest job of the schedule, as a correlated scalar subquery (ids are UUIDv7: newest is largest)."""
    return (
        select(Job.id)
        .where(Job.schedule_id == Schedule.id)
        .order_by(Job.id.desc())
        .limit(1)
        .correlate(Schedule)
        .scalar_subquery()
        .label("last_job_id")
    )


_COLUMNS = (
    Schedule.id,
    Schedule.name,
    Schedule.kind,
    Schedule.request,
    Schedule.cron,
    Schedule.interval_s,
    Schedule.timezone,
    Schedule.paused,
    Schedule.next_run_at,
    Schedule.last_run_at,
    Schedule.last_error,
    Schedule.created_at,
    Schedule.updated_at,
)


def _out(row: Row[Any]) -> ScheduleOut:
    return ScheduleOut.model_validate(row._mapping)


async def get_schedule(conn: AsyncConnection, schedule_id: ScheduleId, *, for_update: bool = False) -> ScheduleOut:
    """The schedule; `for_update` locks its row until `conn`'s transaction ends, for a change read from it."""
    query = select(*_COLUMNS, _last_job()).where(Schedule.id == schedule_id)
    if for_update:
        query = query.with_for_update(of=Schedule)
    row = (await conn.execute(query)).one_or_none()
    if row is None:
        raise ScheduleNotFound(f"no schedule {schedule_id}")
    return _out(row)


async def list_schedules(conn: AsyncConnection, query: ScheduleListQuery) -> SchedulePage:
    rows, next_cursor = await keyset_page(
        conn, select(*_COLUMNS, _last_job()), Schedule.id, after=query.cursor, limit=query.limit, descending=True
    )
    return SchedulePage(items=[_out(row) for row in rows], next_cursor=next_cursor)


async def create_schedule(
    engine: AsyncEngine, submitting: Submitting, new: NewSchedule, *, api_key_id: ApiKeyId | None
) -> ScheduleOut:
    """Check `new`'s request as its submission would and store the schedule, due at its first time after now. Raises,
    storing nothing, `Unschedulable` and the submission's own refusals (`TargetsRejected`, a schema's errors)."""
    kind, request = await _checked(engine, submitting, new)
    async with engine.begin() as conn:
        now = await _now(conn)
        values = {
            "project_id": DEFAULT_PROJECT,
            "name": new.name,
            "kind": kind,
            "request": request.model_dump(mode="json", by_alias=True),
            "cron": new.cron,
            "interval_s": new.interval_s,
            "timezone": new.timezone,
            "paused": new.paused,
            "next_run_at": next_run(new.cadence(), now),
            "api_key_id": api_key_id,
        }
        schedule_id = (await conn.execute(insert(Schedule).values(values).returning(Schedule.id))).scalar_one()
        return await get_schedule(conn, schedule_id)


async def update_schedule(
    engine: AsyncEngine, submitting: Submitting, schedule_id: ScheduleId, change: ScheduleUpdate
) -> ScheduleOut:
    """Apply `change`: the result is checked as a new schedule is (a 422 `ValidationError` names what is wrong), and
    a changed cadence is due at its first time after now. A new request is checked (slow: the SSRF guard, a schema)
    before the write; the write merges `change` again over the row as it is then, locked, so a concurrent update of
    other members is kept, never written back stale."""
    async with engine.connect() as conn:
        new = _validated(_merged(await get_schedule(conn, schedule_id), change))
    checked = None if change.request is None else await _checked(engine, submitting, new)
    async with engine.begin() as conn:
        current = await get_schedule(conn, schedule_id, for_update=True)
        new = _validated(_merged(current, change))
        values: dict[str, Any] = {"name": new.name, "cron": new.cron, "interval_s": new.interval_s}
        values |= {"timezone": new.timezone, "updated_at": func.now()}
        if checked is not None:
            kind, request = checked
            values |= {"kind": kind, "request": request.model_dump(mode="json", by_alias=True)}
        if _cadence_changed(current, new):
            values["next_run_at"] = next_run(new.cadence(), await _now(conn))
        await _update(conn, schedule_id, values)
        return await get_schedule(conn, schedule_id)


def _validated(merged: dict[str, Any]) -> NewSchedule:
    try:
        return _AnySchedule.model_validate(merged).root
    except ValidationError as e:
        raise InvalidUpdate(e) from e


class InvalidUpdate(Refusal):
    """The schedule an update would make is not a valid one."""

    def __init__(self, error: ValidationError) -> None:
        # A location starts with the union member's tag (the `kind`), which the caller did not write.
        self.errors = [(".".join(str(part) for part in item["loc"][1:]), item["msg"]) for item in error.errors()]
        super().__init__("the schedule the update would make is not valid")


def _merged(current: ScheduleOut, change: ScheduleUpdate) -> dict[str, Any]:
    """The new schedule's members: the current ones, with `change`'s over them. A stored scrape is a batch."""
    cadence = {"cron": current.cron, "interval_s": current.interval_s}
    if change.cron is not None or change.interval_s is not None:
        cadence = {"cron": change.cron, "interval_s": change.interval_s}
    return {
        "name": change.name or current.name,
        "kind": change.kind or current.kind,
        "request": current.request if change.request is None else change.request,
        "timezone": change.timezone or current.timezone,
        "paused": current.paused,
        **cadence,
    }


def _cadence_changed(current: ScheduleOut, new: NewSchedule) -> bool:
    return (current.cron, current.interval_s, current.timezone) != (new.cron, new.interval_s, new.timezone)


async def set_paused(conn: AsyncConnection, schedule_id: ScheduleId, *, paused: bool) -> ScheduleOut:
    """Pause or resume the schedule. A resumed schedule is due at its first time after now: the runs it missed while
    paused are not made up. The row is locked before it is read, so a pause and a resume at once see each other."""
    current = await get_schedule(conn, schedule_id, for_update=True)
    values: dict[str, Any] = {"paused": paused, "updated_at": func.now()}
    if current.paused and not paused:
        cadence = Cadence(current.cron, current.interval_s, current.timezone)
        values["next_run_at"] = next_run(cadence, await _now(conn))
    await _update(conn, schedule_id, values)
    return await get_schedule(conn, schedule_id)


async def delete_schedule(conn: AsyncConnection, schedule_id: ScheduleId) -> None:
    """Delete the schedule; its jobs stay, no longer linked to it."""
    deleted = await conn.execute(delete(Schedule).where(Schedule.id == schedule_id).returning(Schedule.id))
    if deleted.first() is None:
        raise ScheduleNotFound(f"no schedule {schedule_id}")


async def run_now(engine: AsyncEngine, submitting: Submitting, schedule_id: ScheduleId) -> RunStarted:
    """Submit the schedule's job now, paused or not, leaving its next due time as it is. Raises the submission's
    refusals, storing nothing."""
    async with engine.begin() as conn:
        locked = select(Schedule.kind, Schedule.request, Schedule.api_key_id).where(Schedule.id == schedule_id)
        row = (await conn.execute(locked.with_for_update())).one_or_none()
        if row is None:
            raise ScheduleNotFound(f"no schedule {schedule_id}")
        job_id = await submit_run(engine, submitting, conn, schedule_id, row.kind, row.request, row.api_key_id)
        await _update(conn, schedule_id, {"last_run_at": func.now(), "last_error": None})
    return RunStarted(job_id=job_id)


async def run_due_schedules(conn: AsyncConnection, submitting: Submitting, *, batch: int) -> int:
    """Submit the jobs of up to `batch` due schedules that are not paused, oldest due first, each moved to its next
    due time in this transaction; return how many."""
    due = (
        select(
            Schedule.id,
            Schedule.kind,
            Schedule.request,
            Schedule.api_key_id,
            Schedule.cron,
            Schedule.interval_s,
            Schedule.timezone,
            Schedule.next_run_at,
        )
        .where(Schedule.paused.is_(False), Schedule.next_run_at <= func.now())
        .order_by(Schedule.next_run_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    )
    rows = (await conn.execute(due)).all()
    now = await _now(conn)
    for row in rows:
        error: str | None = None
        try:
            await submit_run(conn.engine, submitting, conn, row.id, row.kind, row.request, row.api_key_id)
        except (Refusal, ValidationError) as e:
            error = str(e)
        cadence = Cadence(row.cron, row.interval_s, row.timezone)
        values = {"next_run_at": next_run(cadence, now, row.next_run_at), "last_run_at": now, "last_error": error}
        await _update(conn, row.id, values)
    return len(rows)


async def submit_run(
    engine: AsyncEngine,
    submitting: Submitting,
    conn: AsyncConnection,
    schedule_id: ScheduleId,
    kind: ScheduledKind,
    request: dict[str, Any],
    api_key_id: ApiKeyId | None,
) -> JobId:
    """Submit a run of the schedule as a job stored in `conn`'s transaction."""
    placement = Placement(into=conn, schedule_id=schedule_id)
    fetching, data, llm = submitting.fetching, submitting.data, submitting.llm
    match kind:
        case "batch_scrape":
            batch = BatchScrapeRequest.model_validate(request)
            submitted = await submit_batch(
                engine,
                fetching.connector,
                batch,
                data=data,
                llm=llm,
                api_key_id=api_key_id,
                placement=placement,
                egresses=fetching.egresses,
            )
            return submitted.job_id
        case "crawl":
            crawl = CrawlRequest.model_validate(request)
            started = await submit_crawl(
                engine,
                fetching.connector,
                crawl,
                data=data,
                llm=llm,
                api_key_id=api_key_id,
                placement=placement,
                egresses=fetching.egresses,
            )
            return started.job_id
        case "extract":
            extract = ExtractRequest.model_validate(request)
            queued = await submit_extract(
                engine, fetching, extract, llm=llm, data=data, api_key_id=api_key_id, placement=placement
            )
            return queued.job_id
        case _:
            assert_never(kind)


async def _checked(
    engine: AsyncEngine, submitting: Submitting, new: NewSchedule
) -> tuple[ScheduledKind, ScheduledRequest]:
    """`new`'s job kind and request, as a run submits it: a scrape as a batch, its targets checked by the SSRF guard
    and its `records` schema by id. A request with `fetch.headers` or `fetch.cookies` is `Unschedulable` (D-1510)."""
    if new.request.fetch.headers or new.request.fetch.cookies:
        raise Unschedulable(
            "a schedule keeps no secret values, so its request takes no fetch.headers or fetch.cookies: "
            "a stored placeholder would be sent as the value"
        )
    match new:
        case NewScrapeSchedule(request=scrape):
            return "batch_scrape", await _batch_checked(engine, submitting, _as_batch(scrape))
        case NewBatchSchedule(request=batch):
            return "batch_scrape", await _batch_checked(engine, submitting, batch)
        case NewCrawlSchedule(request=crawl):
            await check_targets(submitting.fetching.connector, [("url", crawl.url)], webhook_url=crawl.webhook_url)
            page_kind = crawl.page_kind_rules[0].page_kind if crawl.page_kind_rules else None
            schema = await records_schema(
                engine, crawl.formats, crawl.schema_, page_kind, submitting.data, submitting.llm
            )
            return "crawl", _by_id(crawl, schema)
        case NewExtractSchedule(request=extract):
            if isinstance(extract.schema_, SchemaPrompt):
                raise Unschedulable("a schedule runs a schema it has: draft the prompt's schema first, then name it")
            await check_targets(submitting.fetching.connector, extract.targets(), webhook_url=extract.webhook_url)
            if submitting.data is None:
                # An extract always stores records, as `submit_extract` refuses it without the data.
                raise RecordsUnavailable("this process has not loaded the engine's data files")
            schema = await named_schema(engine, extract.schema_, extract.page_kind, submitting.llm)
            return "extract", _by_id(extract, schema)
        case _:
            assert_never(new)


async def _batch_checked(engine: AsyncEngine, submitting: Submitting, batch: BatchScrapeRequest) -> ScheduledRequest:
    targets = [(f"urls[{index}]", url) for index, url in enumerate(batch.urls)]
    await check_targets(submitting.fetching.connector, targets, webhook_url=batch.webhook_url)
    schema = await records_schema(
        engine, batch.formats, batch.schema_, batch.page_kind, submitting.data, submitting.llm
    )
    return _by_id(batch, schema)


def _by_id(request: ScheduledRequest, schema: SchemaDef | None) -> ScheduledRequest:
    """`request` naming `schema` (the one its `records` resolved to) by id; unchanged without one."""
    if schema is None:
        return request
    return request.model_copy(update={"schema_": SchemaById(id=schema.id)})


def _as_batch(scrape: ScrapeRequest) -> BatchScrapeRequest:
    """The batch of a scrape's one URL, with its formats, schema, page kind, fetch, locale, budget and render fields."""
    if scrape.browser_actions is not None:
        raise Unschedulable("browser actions run in a scrape answered while the caller waits, not on a schedule")
    members = scrape.model_dump(by_alias=True, include=_BATCH_MEMBERS, exclude_none=True)
    try:
        return BatchScrapeRequest.model_validate({"urls": [scrape.url], **members})
    except ValidationError as e:
        reasons = "; ".join(item["msg"] for item in e.errors())
        raise Unschedulable(f"this scrape cannot run as a batch: {reasons}") from e


async def _now(conn: AsyncConnection) -> datetime:
    now: datetime = (await conn.execute(select(func.now()))).scalar_one()
    return now


async def _update(conn: AsyncConnection, schedule_id: ScheduleId, values: dict[str, Any]) -> None:
    updated = await conn.execute(
        update(Schedule).where(Schedule.id == schedule_id).values(**values).returning(Schedule.id)
    )
    if updated.first() is None:
        raise ScheduleNotFound(f"no schedule {schedule_id}")
