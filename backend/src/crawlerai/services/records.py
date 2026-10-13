"""Records as the API returns them (SPEC-07 §4.4, §4.6, ARCHITECTURE §13.1, INV-22, INV-27): `scrape`, `/v1/records`
and replay answer with them. And the records service: what `GET /v1/records` and the MCP record tools do, over a
connection.

Every schema field is a member, published or not, with the §13.1 attributes (`value`, `status`, `evidence`,
`confidence`, `calibrated`, `locator`) and `reason`, `source_kind`, `derived_by` from `field_meta`. The value is the
record's published value, unchanged (INV-27), and `None` for a field that did not publish.
"""

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import RowMapping, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import CaptureId, Extraction, ExtractionMode, JobId, Record, RecordId, SchemaId, Site
from crawlerai.resolve.records import FieldMeta, RecordContent, record_confidence
from crawlerai.resolve.types import Probability
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef

MAX_PAGE = 200
_COLUMNS = (
    Record.id,
    Record.schema_id,
    Record.version,
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
    the schema version its fields follow, and its own version (§14)."""

    capture_id: CaptureId | None
    schema_id: SchemaId
    version: int


class RecordPage(BaseModel):
    """One page of records, newest first; `next_cursor` is null on the last page."""

    model_config = ConfigDict(frozen=True)

    items: list[StoredRecord]
    next_cursor: RecordId | None


class RecordFilter(BaseModel):
    """The records to list: those of a job, of a site (its host), of a schema version, or any combination."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: JobId | None = None
    site: str | None = None
    schema_id: SchemaId | None = None
    cursor: RecordId | None = None
    limit: int = Field(default=50, ge=1, le=MAX_PAGE)


async def list_records(conn: AsyncConnection, query: RecordFilter) -> RecordPage:
    """The page of records after `query.cursor` (the first page without one) that match its filters. Records are
    ordered by id, newest first (ids are UUIDv7, RFC 9562 §5.7, so their order is creation order)."""
    statement = (
        select(*_COLUMNS)
        .join(Extraction, Extraction.id == Record.extraction_id)
        .order_by(Record.id.desc())
        .limit(query.limit + 1)
    )
    if query.job_id is not None:
        statement = statement.where(Record.job_id == query.job_id)
    if query.site is not None:
        # Hosts compare without case (RFC 4343), and sites are stored lowercase.
        statement = statement.join(Site, Site.id == Record.site_id).where(Site.host == query.site.lower())
    if query.schema_id is not None:
        statement = statement.where(Record.schema_id == query.schema_id)
    if query.cursor is not None:
        statement = statement.where(Record.id < query.cursor)
    rows = (await conn.execute(statement)).mappings().all()
    page = rows[: query.limit]
    schemas = {schema_id: await registry.get_by_id(conn, schema_id) for schema_id in {row["schema_id"] for row in page}}
    items = [_stored(row, schemas[row["schema_id"]]) for row in page]
    return RecordPage(items=items, next_cursor=items[-1].id if len(rows) > query.limit else None)


def _stored(row: RowMapping, schema: SchemaDef) -> StoredRecord:
    data = row["data"]
    fields = {
        name: RecordField.model_validate({**meta, "value": data.get(name)}) for name, meta in row["field_meta"].items()
    }
    columns = {name: row[name] for name in ("id", "capture_id", "schema_id", "version", "mode", "complete")}
    return StoredRecord(**columns, confidence=record_confidence(schema, fields), fields=fields)


def _fields(data: Mapping[str, Any], meta: Mapping[str, FieldMeta]) -> dict[str, RecordField]:
    return {name: RecordField(**field.model_dump(), value=data.get(name)) for name, field in meta.items()}
