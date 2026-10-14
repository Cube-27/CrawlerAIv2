"""Record versions (SPEC-11 §4.4, ARCHITECTURE §14 row 3): how a page's records are stored when the same
entities were extracted before.

Each record is compared with the latest version of its entity, the record with the same (site, schema, entity key) and
the highest `version`. An equal fingerprint (`recurring.record_fp`) stores nothing and answers with that version; a
different one, or none stored, adds the next version, superseding it and naming its changed fields. This is the
`resolve.task.RecordWriter` a page task stores its records with.

`url_state` is not written here: it is per URL, and its `last_changed_at` is when the page's content last changed
(`recurring.state.record_content`), which a record of one schema version must not move for the others.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import RowMapping, func, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Record, RecordId, SiteId
from crawlerai.recurring.record_fp import changed_fields, record_fingerprint
from crawlerai.resolve.records import FieldMeta, RecordDraft
from crawlerai.resolve.task import RecordSource, StoredRecord
from crawlerai.schemas.types import SchemaDef

__all__ = ["store_records"]


@dataclass(frozen=True, slots=True)
class _New:
    """A record to insert: its position in the page's records, its content, its fingerprint and the version it
    supersedes, if any."""

    position: int
    draft: RecordDraft
    fingerprint: str
    previous: RowMapping | None


async def store_records(
    conn: AsyncConnection, schema: SchemaDef, drafts: Sequence[RecordDraft], source: RecordSource
) -> tuple[StoredRecord, ...]:
    """Store a page's records, in `conn`'s transaction, as new versions of their entities where their fingerprints
    differ, and return them in `drafts`' order: an unchanged entity's is its latest stored record, as stored."""
    await _lock(conn, source.site_id, schema)
    latest = await _latest(conn, source.site_id, schema, [draft.entity_key for draft in drafts])
    stored: list[StoredRecord | None] = []
    new: list[_New] = []
    for position, draft in enumerate(drafts):
        fingerprint = record_fingerprint(draft.data, schema)
        previous = latest.get(draft.entity_key)
        if previous is not None and previous["fingerprint"] == fingerprint:
            stored.append(StoredRecord(previous["id"], _stored_draft(previous)))
        else:
            stored.append(None)
            new.append(_New(position, draft, fingerprint, previous))
    for record, record_id in zip(new, await _insert(conn, schema, source, new), strict=True):
        stored[record.position] = StoredRecord(record_id, record.draft)
    return tuple(record for record in stored if record is not None)


async def _lock(conn: AsyncConnection, site_id: SiteId, schema: SchemaDef) -> None:
    """Hold the site's record versions for the schema until the transaction ends, so that two tasks storing the same
    entity at once cannot both add the same version. A task's transaction already waits on the same site and schema
    for its progressive state row (`services.scrape_steps`), so this adds no wait of its own to speak of."""
    digest = hashlib.blake2b(f"record_versions:{site_id}:{schema.id}".encode(), digest_size=8).digest()
    # pg_advisory_xact_lock takes a bigint key (PostgreSQL §9.28.10): the digest's 8 bytes, signed.
    await conn.execute(select(func.pg_advisory_xact_lock(int.from_bytes(digest, "big", signed=True))))


async def _latest(conn: AsyncConnection, site_id: SiteId, schema: SchemaDef, keys: list[str]) -> dict[str, RowMapping]:
    columns = (Record.id, Record.entity_key, Record.version, Record.fingerprint, Record.data, Record.field_meta)
    query = (
        select(*columns, Record.complete)
        .where(Record.site_id == site_id, Record.schema_id == schema.id, Record.entity_key.in_(keys))
        .ext(distinct_on(Record.entity_key))
        # Ids are UUIDv7 (RFC 9562 §5.7): among equal versions, which records stored before versions existed share,
        # the newest.
        .order_by(Record.entity_key, Record.version.desc(), Record.id.desc())
    )
    return {row["entity_key"]: row for row in (await conn.execute(query)).mappings()}


def _stored_draft(row: RowMapping) -> RecordDraft:
    meta = {name: FieldMeta.model_validate(value) for name, value in row["field_meta"].items()}
    return RecordDraft(data=row["data"], field_meta=meta, complete=row["complete"], entity_key=row["entity_key"])


async def _insert(
    conn: AsyncConnection, schema: SchemaDef, source: RecordSource, new: list[_New]
) -> Sequence[RecordId]:
    if not new:
        return ()
    values = [_values(schema, source, record) for record in new]
    inserted = await conn.execute(insert(Record).returning(Record.id, sort_by_parameter_order=True), values)
    return inserted.scalars().all()


def _values(schema: SchemaDef, source: RecordSource, record: _New) -> dict[str, Any]:
    draft, previous = record.draft, record.previous
    values = {
        "extraction_id": source.extraction_id,
        "job_id": source.job_id,
        "site_id": source.site_id,
        "schema_id": schema.id,
        "schema_version": schema.version,
        "entity_key": draft.entity_key,
        "data": draft.data,
        "field_meta": {name: meta.model_dump(mode="json") for name, meta in draft.field_meta.items()},
        "complete": draft.complete,
        "mode": source.mode,
        "fingerprint": record.fingerprint,
        "version": 1,
        "supersedes_record_id": None,
        "changed_fields": [],
    }
    if previous is not None:
        values["version"] = previous["version"] + 1
        values["supersedes_record_id"] = previous["id"]
        values["changed_fields"] = changed_fields(previous["data"], draft.data, schema)
    return values
