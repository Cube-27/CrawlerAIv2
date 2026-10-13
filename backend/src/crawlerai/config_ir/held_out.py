"""Held-out pages from storage (SPEC-08 §4.4, §4.7): the stored captures of a (site, schema version) that a config is
validated on, each parsed with its context and with the facts the engine stored for it.

The pages are a site's most recent captures with outcome `extracted` or `partial` that have records of the schema
version (§4.4), each with its latest extraction. A capture whose bundle is no longer stored (captures expire, §15) is
skipped. What the engine published is the extraction's records (`record.data` holds published fields only, §6): a
detail page's one, or a listing's one per row in the order they were stored, which is the page's row order.

The references corroboration compares with (§8.3 step 4) are the valid structured-data or adapter candidates owned by
an entity that published a field of the page. Records do not say which row entity a listing record came from, so a
listing's rows have no references, and their fields stay `uncorroborated`.
"""

import asyncio
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, get_args

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import (
    Candidate,
    Capture,
    CaptureId,
    Extraction,
    ExtractionId,
    Record,
    SiteId,
    SourceKind,
    UrlTask,
)
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

# §6: the pages learning reads are those whose outcome is `extracted` or `partial`.
EXTRACTED: Final = ("extracted", "partial")
# ARCHITECTURE §8.3 step 4: structured data or an adapter; a config's own values and the model's are not references.
REFERENCE_KINDS: Final = frozenset(get_args(SourceKind)) - {"config", "llm"}


@dataclass(frozen=True, slots=True)
class StoredCandidate:
    """A valid candidate of an extraction: its owner, field, normalized value, source and whether it was published."""

    entity_ref: str
    field: str
    value: JsonValue
    source_kind: SourceKind
    chosen: bool


def facts_of(
    schema: SchemaDef, records: Sequence[Mapping[str, JsonValue]], candidates: Iterable[StoredCandidate]
) -> tuple[Facts, tuple[Facts, ...]]:
    """The page's facts and a listing's rows' facts, from one extraction's records (`record.data`, in stored order)
    and its valid candidates."""
    if schema.page_kind == "listing":
        page_fields = {name for name, spec in schema.fields.items() if spec.scope == "page"}
        first = records[0] if records else {}
        page = Facts(published={name: value for name, value in first.items() if name in page_fields})
        rows = tuple(
            Facts(published={name: value for name, value in data.items() if name not in page_fields})
            for data in records
        )
        return page, rows
    candidates = list(candidates)
    owners = {c.entity_ref for c in candidates if c.chosen}
    references: dict[str, list[JsonValue]] = defaultdict(list)
    for c in candidates:
        if c.entity_ref in owners and c.source_kind in REFERENCE_KINDS:
            references[c.field].append(c.value)
    return Facts(published=dict(records[0]) if records else {}, references=dict(references)), ()


async def load_held_out(
    conn: AsyncConnection, store: ObjectStore, site_id: SiteId, schema: SchemaDef, *, limit: int
) -> list[HeldOutPage]:
    """Up to `limit` held-out pages of `site_id` for `schema`'s version, most recent first."""
    extractions = await _extractions(conn, site_id, schema, limit)
    ids = [extraction_id for _, _, extraction_id in extractions]
    records = await _records(conn, ids, schema)
    candidates = await _candidates(conn, ids)
    pages: list[HeldOutPage] = []
    for capture_id, object_key, extraction_id in extractions:
        loaded = await _parsed(store, object_key)
        if loaded is None:
            continue
        page, ctx = loaded
        facts, rows = facts_of(schema, records[extraction_id], candidates[extraction_id])
        pages.append(HeldOutPage(capture_id, page, ctx, facts, rows))
    return pages


async def _extractions(
    conn: AsyncConnection, site_id: SiteId, schema: SchemaDef, limit: int
) -> list[tuple[CaptureId, str, ExtractionId]]:
    """The most recent captures with a record of `schema`'s version from an `extracted` or `partial` task, each with
    its latest such extraction."""
    has_record = (
        select(Record.id)
        .where(
            Record.extraction_id == Extraction.id,
            Record.schema_id == schema.id,
            Record.schema_version == schema.version,
        )
        .exists()
    )
    latest = (
        select(Capture.id, Capture.object_key, Capture.fetched_at, Extraction.id.label("extraction_id"))
        .join(Extraction, Extraction.capture_id == Capture.id)
        .join(UrlTask, UrlTask.id == Extraction.url_task_id)
        .where(Capture.site_id == site_id, UrlTask.outcome.in_(EXTRACTED), has_record)
        .order_by(Capture.id, Extraction.id.desc())
        .ext(distinct_on(Capture.id))
        .subquery()
    )
    query = (
        select(latest.c.id, latest.c.object_key, latest.c.extraction_id)
        .order_by(latest.c.fetched_at.desc(), latest.c.id.desc())
        .limit(limit)
    )
    return [(row.id, row.object_key, row.extraction_id) for row in await conn.execute(query)]


async def _records(
    conn: AsyncConnection, ids: Sequence[ExtractionId], schema: SchemaDef
) -> dict[ExtractionId, list[Mapping[str, JsonValue]]]:
    query = (
        select(Record.extraction_id, Record.data)
        .where(Record.extraction_id.in_(ids), Record.schema_id == schema.id, Record.schema_version == schema.version)
        .order_by(Record.id)  # ids are UUIDv7, so this is the order the records were stored in
    )
    found: dict[ExtractionId, list[Mapping[str, JsonValue]]] = defaultdict(list)
    for row in await conn.execute(query):
        found[row.extraction_id].append(row.data)
    return found


async def _candidates(conn: AsyncConnection, ids: Sequence[ExtractionId]) -> dict[ExtractionId, list[StoredCandidate]]:
    query = select(
        Candidate.extraction_id,
        Candidate.entity_ref,
        Candidate.field,
        Candidate.normalized_value,
        Candidate.source_kind,
        Candidate.chosen,
    ).where(Candidate.extraction_id.in_(ids), Candidate.normalize_status == "ok")
    found: dict[ExtractionId, list[StoredCandidate]] = defaultdict(list)
    for row in await conn.execute(query):
        found[row.extraction_id].append(
            StoredCandidate(row.entity_ref, row.field, row.normalized_value, row.source_kind, row.chosen)
        )
    return found


async def _parsed(store: ObjectStore, object_key: str) -> tuple[ParsedPage, Context] | None:
    try:
        blob = await asyncio.to_thread(store.get, object_key)
    except ObjectNotFound:
        return None
    bundle = await asyncio.to_thread(decode, blob)
    page = ParsedPage.of(bundle)
    return page, page_context(page, bundle.manifest.final_url, bundle.manifest.fetched_at)
