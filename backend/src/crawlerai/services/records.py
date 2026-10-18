"""Records as the API returns them (SPEC-07 §4.4, §4.6, ARCHITECTURE §13.1, INV-22, INV-27): `scrape`, `/v1/records`
and replay answer with them. And the records service: what `GET /v1/records` and the MCP record tools do, over a
connection.

Every schema field is a member, published or not, with the §13.1 attributes (`value`, `status`, `evidence`,
`confidence`, `calibrated`, `locator`) and `reason`, `source_kind`, `derived_by` from `field_meta`. The value is the
record's published value, unchanged (INV-27), and `None` for a field that did not publish.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Final, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import Row, RowMapping, ScalarSelect, Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import aliased

from crawlerai.db.models import (
    CaptureId,
    Extraction,
    ExtractionMode,
    JobId,
    Record,
    RecordId,
    SchemaId,
    Site,
    TaskRecord,
    UrlTask,
    UrlTaskId,
)
from crawlerai.db.paging import keyset_page
from crawlerai.resolve.records import FieldMeta, RecordContent, record_confidence
from crawlerai.resolve.types import FieldSet, Probability
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef

MAX_PAGE = 200
# The advisory lock of the change feed (`_committed`, migration 0018): blake2b("record_feed", digest_size=8) as a
# signed bigint.
RECORD_FEED_LOCK: Final = -7838622165994782610
_COLUMNS = (
    Record.id,
    Record.schema_id,
    Record.version,
    Record.changed_fields,
    Record.mode,
    Record.complete,
    Record.data,
    Record.field_meta,
    Extraction.capture_id,
)


class RecordField(FieldMeta):
    value: JsonValue


class ExtractedRecord(BaseModel):
    """A record's content (§6 `record`): `complete` when every required field and group published (§10), and its
    confidence, the minimum over the required fields, `None` when any of them is uncalibrated. A replay answers with
    these: they are not stored, so they have no id."""

    model_config = ConfigDict(frozen=True)

    mode: ExtractionMode
    complete: bool
    confidence: Probability | None
    fields: dict[str, RecordField]

    @classmethod
    def of_content(cls, content: RecordContent, *, mode: ExtractionMode, confidence: float | None) -> Self:
        fields = _fields(content.data, content.field_meta)
        return cls(mode=mode, complete=content.complete, confidence=confidence, fields=fields)


class ScrapedRecord(ExtractedRecord):
    """A stored record as `scrape` answers with it."""

    id: RecordId

    @classmethod
    def of(cls, record_id: RecordId, draft: RecordContent, *, mode: ExtractionMode, confidence: float | None) -> Self:
        fields = _fields(draft.data, draft.field_meta)
        return cls(id=record_id, mode=mode, complete=draft.complete, confidence=confidence, fields=fields)


class StoredRecord(ScrapedRecord):
    """A `record` row, with the capture it was extracted from (`None` once the capture expired, ARCHITECTURE §15),
    the schema its fields follow, its own version and the fields whose published value differs from the
    version it supersedes, empty for an entity's first (§14, SPEC-11 §4.4)."""

    capture_id: CaptureId | None
    schema_id: SchemaId
    version: int
    changed_fields: list[str]


class RecordPage(BaseModel):
    """One page of records, newest first; `next_cursor` is null on the last page."""

    model_config = ConfigDict(frozen=True)

    items: list[StoredRecord]
    next_cursor: RecordId | None


class RecordFilter(BaseModel):
    """The records to list: those of a job, of a site (its host), of a schema, stored at or after a time, or
    any combination. A job's are those its pages stand for, stored by it or found unchanged (SPEC-11 §4.2, §4.4).
    Stored from `changed_since` on, a record is a new entity or a new version of one: the change feed of recurring
    runs (§4.4). An entity re-extracted unchanged stores no record, so `changed_since` does not list it again."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: JobId | None = None
    site: str | None = None
    schema_id: SchemaId | None = None
    # An instant: a time with its offset (RFC 3339 §5.6).
    changed_since: AwareDatetime | None = None
    cursor: RecordId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


async def list_records(conn: AsyncConnection, query: RecordFilter) -> RecordPage:
    """The page of records after `query.cursor` (the first page without one) that match its filters. Records are
    ordered by id, newest first (ids are UUIDv7, RFC 9562 §5.7, so their order is creation order)."""
    statement = select(*_COLUMNS).join(Extraction, Extraction.id == Record.extraction_id)
    if query.site is not None:
        # Hosts compare without case (RFC 4343), and sites are stored lowercase.
        statement = statement.join(Site, Site.id == Record.site_id).where(Site.host == query.site.lower())
    if query.schema_id is not None:
        statement = statement.where(Record.schema_id == query.schema_id)
    if query.changed_since is not None:
        await _committed(conn)
        statement = statement.where(Record.created_at >= query.changed_since)
    if query.job_id is None:
        rows, next_cursor = await keyset_page(
            conn, statement, Record.id, after=query.cursor, limit=query.limit, descending=True
        )
    else:
        rows, next_cursor = await _job_page(conn, statement, query.job_id, query)
    page = [row._mapping for row in rows]
    schemas = {schema_id: await registry.get_by_id(conn, schema_id) for schema_id in {row["schema_id"] for row in page}}
    items = [_stored(row, schemas[row["schema_id"]]) for row in page]
    return RecordPage(items=items, next_cursor=next_cursor)


async def _job_page(
    conn: AsyncConnection, statement: Select[Any], job_id: JobId, query: RecordFilter
) -> tuple[Sequence[Row[Any]], RecordId | None]:
    """The page of the job's records (SPEC-11 §4.2, §4.4): those its tasks stand for, stored or found unchanged, each at
    the first task of the job that stands for it, newest task first and, within a task, newest record first. The page
    is read from the job's tasks by id (keyset, `ix_url_task_job_id_id`), so it never builds the job's whole set of
    `task_record` rows; the cursor stays a record id, and stands where that record does in the job. A cursor of a
    record the job has no task for gives an empty page."""
    link, owner = aliased(TaskRecord), aliased(UrlTask)

    def first_task(record: Any) -> ScalarSelect[UrlTaskId]:
        of_record = select(link.url_task_id).join(owner, owner.id == link.url_task_id)
        # No `min` of a uuid in PostgreSQL: the smallest id is the first of the order.
        first = of_record.where(link.record_id == record, owner.job_id == job_id).order_by(link.url_task_id).limit(1)
        return first.scalar_subquery()

    statement = (
        statement.join(TaskRecord, TaskRecord.record_id == Record.id)
        .join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
        .where(UrlTask.job_id == job_id, UrlTask.id == first_task(Record.id))
    )
    if query.cursor is not None:
        position = (await conn.execute(select(first_task(query.cursor)))).scalar_one()
        if position is None:
            return [], None
        statement = statement.where(tuple_(UrlTask.id, Record.id) < tuple_(position, query.cursor))
    ordered = statement.order_by(UrlTask.id.desc(), Record.id.desc()).limit(query.limit + 1)
    rows = (await conn.execute(ordered)).all()
    page = rows[: query.limit]
    return page, page[-1].id if len(rows) > query.limit else None


async def _committed(conn: AsyncConnection) -> None:
    """Wait until every record whose commit time is already set has committed, so that a poller that asks from the
    time it last asked misses no record that committed late. A record's `created_at` is set again as its transaction
    commits, which holds `RECORD_FEED_LOCK` shared until the commit is visible (migration 0018). Once the lock is free,
    a record stamped earlier is visible to the next statement (READ COMMITTED takes a snapshot per statement), and one
    stamped later is no earlier than this call. The lock is released at once."""
    # The select list is evaluated in order: the lock is taken, then released.
    await conn.execute(select(func.pg_advisory_lock(RECORD_FEED_LOCK), func.pg_advisory_unlock(RECORD_FEED_LOCK)))


def _stored(row: RowMapping, schema: SchemaDef) -> StoredRecord:
    data = row["data"]
    fields = {
        name: RecordField.model_validate({**meta, "value": data.get(name)}) for name, meta in row["field_meta"].items()
    }
    names = ("id", "capture_id", "schema_id", "version", "changed_fields", "mode", "complete")
    columns = {name: row[name] for name in names}
    return StoredRecord(**columns, confidence=record_confidence(schema, fields), fields=fields)


def page_fields(schema: SchemaDef, fields: FieldSet) -> dict[str, RecordField]:
    """A listing's page-scope fields (SPEC-01 §4.3 `scope: page`) in the record field shape: what a listing that kept
    no record still resolved, such as its next page."""
    scoped = {name: outcome for name, outcome in fields.items() if schema.fields[name].scope == "page"}
    data = {name: outcome.value for name, outcome in scoped.items() if outcome.status == "published"}
    return _fields(data, {name: FieldMeta.of(outcome) for name, outcome in scoped.items()})


def _fields(data: Mapping[str, Any], meta: Mapping[str, FieldMeta]) -> dict[str, RecordField]:
    return {name: RecordField(**field.model_dump(), value=data.get(name)) for name, field in meta.items()}
