"""Record versions (jobs spec): how a page's records are stored when the same
entities were extracted before.

Each record is compared with the latest version of its entity, the record with the same (site, schema, entity key) and
the highest `version`. A record equal to it in every value (`recurring.record_fp`), every field's metadata and
completeness, under the same document of the schema, stores nothing and answers with that version, which holds exactly
what was just extracted; any difference, none stored, or another document (`record.schema_digest`; a schema is edited
in place) adds the next version, superseding it and naming its changed fields. Either
way the task stands for the record it answers with (`task_record`, §4.2), so that its job lists it. This is the
`resolve.task.RecordWriter` a page task stores its records with.

`url_state` is not written here: it is per URL, and its `last_changed_at` is when the page's content last changed
(`recurring.state.record_content`), which a record of one schema must not move for the others.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import RowMapping, func, insert, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, Record, RecordId, SiteId, TaskRecord, UrlTaskId
from crawlerai.recurring.record_fp import changed_fields, record_fingerprint
from crawlerai.resolve.records import FieldMeta, RecordDraft
from crawlerai.resolve.task import RecordSource, StoredRecord
from crawlerai.schemas.types import SchemaDef, document_digest

__all__ = ["latest_versions", "link_records", "store_records"]


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
    differ (`_same`), and return them in `drafts`' order: an entity extracted exactly as its latest version is that
    record."""
    await _lock(conn, source.site_id, schema)
    latest = await latest_versions(conn, source.site_id, schema, [draft.entity_key for draft in drafts])
    digest = document_digest(schema)
    stored: list[StoredRecord | None] = []
    new: list[_New] = []
    for position, draft in enumerate(drafts):
        fingerprint = record_fingerprint(draft.data, schema)
        previous = latest.get(draft.entity_key)
        if previous is not None and _same(previous, draft, fingerprint, digest):
            stored.append(StoredRecord(previous["id"], _stored_draft(previous)))
        else:
            stored.append(None)
            new.append(_New(position, draft, fingerprint, previous))
    for record, record_id in zip(new, await _insert(conn, schema, digest, source, new), strict=True):
        stored[record.position] = StoredRecord(record_id, record.draft)
    records = tuple(record for record in stored if record is not None)
    await link_records(conn, source.task_id, [record.id for record in records])
    return records


async def link_records(conn: AsyncConnection, task_id: UrlTaskId, record_ids: Sequence[RecordId]) -> None:
    """Record that the task's page stands for `record_ids`: those it stored, or the latest versions equal to what it
    extracted. A listing's rows can name one entity twice, so a link already there is kept."""
    if record_ids:
        rows = [{"url_task_id": task_id, "record_id": record_id} for record_id in dict.fromkeys(record_ids)]
        await conn.execute(pg_insert(TaskRecord).values(rows).on_conflict_do_nothing())


async def _lock(conn: AsyncConnection, site_id: SiteId, schema: SchemaDef) -> None:
    """Hold the site's record versions for the schema until the transaction ends, so that two tasks storing the same
    entity at once cannot both add the same version. A task's transaction already waits on the same site and schema
    for its progressive state row (`services.scrape_steps`), so this adds no wait of its own to speak of."""
    digest = hashlib.blake2b(f"record_versions:{site_id}:{schema.id}".encode(), digest_size=8).digest()
    # pg_advisory_xact_lock takes a bigint key (PostgreSQL §9.28.10): the digest's 8 bytes, signed.
    await conn.execute(select(func.pg_advisory_xact_lock(int.from_bytes(digest, "big", signed=True))))


async def latest_versions(
    conn: AsyncConnection, site_id: SiteId, schema: SchemaDef, keys: list[str]
) -> dict[str, RowMapping]:
    """The latest version of each entity of `keys` under `schema` on the site, by key; an entity with none is absent."""
    columns = (Record.id, Record.entity_key, Record.version, Record.fingerprint, Record.schema_digest, Record.data)
    query = (
        select(*columns, Record.field_meta, Record.complete)
        .where(Record.site_id == site_id, Record.schema_id == schema.id, Record.entity_key.in_(keys))
        .ext(distinct_on(Record.entity_key))
        .order_by(Record.entity_key, Record.version.desc(), Record.id.desc())
    )
    return {row["entity_key"]: row for row in (await conn.execute(query)).mappings()}


def _same(previous: RowMapping, draft: RecordDraft, fingerprint: str, digest: str) -> bool:
    """Whether the latest stored version holds exactly what `draft` does: its values, the metadata of every field and
    its completeness, under the same schema document."""
    stored = (previous["fingerprint"], previous["schema_digest"], previous["complete"], previous["field_meta"])
    return bool(stored == (fingerprint, digest, draft.complete, _meta(draft)))


def _meta(draft: RecordDraft) -> dict[str, Any]:
    """The record's field metadata as `record.field_meta` stores it."""
    return {name: meta.model_dump(mode="json") for name, meta in draft.field_meta.items()}


def _stored_draft(row: RowMapping) -> RecordDraft:
    meta = {name: FieldMeta.model_validate(value) for name, value in row["field_meta"].items()}
    return RecordDraft(data=row["data"], field_meta=meta, complete=row["complete"], entity_key=row["entity_key"])


async def _insert(
    conn: AsyncConnection, schema: SchemaDef, digest: str, source: RecordSource, new: list[_New]
) -> Sequence[RecordId]:
    if not new:
        return ()
    # The country the job's fetches go out from, pinned at its submit, is the one every page of it was fetched from.
    egress = (
        (await conn.execute(select(Job.egress_country, Job.egress_basis).where(Job.id == source.job_id)))
        .one()
        ._asdict()
    )
    values = [{**_values(schema, source, record), **egress, "schema_digest": digest} for record in new]
    inserted = await conn.execute(insert(Record).returning(Record.id, sort_by_parameter_order=True), values)
    return inserted.scalars().all()


def _values(schema: SchemaDef, source: RecordSource, record: _New) -> dict[str, Any]:
    draft, previous = record.draft, record.previous
    values = {
        "extraction_id": source.extraction_id,
        "job_id": source.job_id,
        "site_id": source.site_id,
        "schema_id": schema.id,
        "entity_key": draft.entity_key,
        "data": draft.data,
        "field_meta": _meta(draft),
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
