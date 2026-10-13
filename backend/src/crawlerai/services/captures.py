"""The captures service (SPEC-07 §4.6, §4.7, ARCHITECTURE §13.1): replay a stored capture with the current engine,
for debugging. Nothing a replay makes is stored.

A capture carries no schema of its own, so it replays against each schema version its stored records follow, the
version the records were made with (schemas are immutable per version, §5.2), so a replayed record compares with
the stored one. Replays run cold (`adhoc`, no config): the site's active config runs through SPEC-08's executor,
which `extract_page` gains with SPEC-08 PR 8, and until then no site has an active config. No replay calls an LLM:
`extract_page` gets no role C.
"""

import asyncio

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import Capture, CaptureId, Extraction, Record
from crawlerai.resolve.pipeline import EngineData, ModeNotSupported, extract_page
from crawlerai.resolve.records import RecordContent
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.records import ExtractedRecord
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import CaptureBundle, decode

_COLUMNS = (Capture.id, Capture.object_key)
_Capture = Row[CaptureId, str]


class CaptureNotFound(LookupError):
    """No capture has the id, or its bundle is no longer stored (captures expire, §15)."""


class NotReplayable(Exception):
    """The capture exists but cannot be replayed: no record was made from it, so no schema names what to extract, or
    its schema is one the pipeline does not extract yet."""


async def replay(
    engine: AsyncEngine, store: ObjectStore, data: EngineData, capture_id: CaptureId
) -> list[ExtractedRecord]:
    """The records the current engine makes from the capture, one schema version after another (by id). A page that
    resolves nothing (blocked, an error) adds none; an incomplete one adds its record with `complete=false`, as for
    any caller-supplied URL (§10)."""
    async with engine.connect() as conn:
        capture = (await conn.execute(select(*_COLUMNS).where(Capture.id == capture_id))).one_or_none()
        if capture is None:
            raise CaptureNotFound(f"no capture {capture_id}")
        schema_ids = (
            await conn.execute(
                select(Record.schema_id)
                .distinct()
                .join(Extraction, Extraction.id == Record.extraction_id)
                .where(Extraction.capture_id == capture_id)
                .order_by(Record.schema_id)
            )
        ).scalars()
        schemas = [await registry.get_by_id(conn, schema_id) for schema_id in schema_ids]
    if not schemas:
        raise NotReplayable(f"no record was made from capture {capture_id}, so no schema says what to extract")
    bundle = await _bundle(store, capture)
    made = [await _replay(bundle, schema, data) for schema in schemas]
    return [record for record in made if record is not None]


async def _bundle(store: ObjectStore, capture: _Capture) -> CaptureBundle:
    try:
        blob = await asyncio.to_thread(store.get, capture.object_key)
    except ObjectNotFound as e:
        raise CaptureNotFound(f"capture {capture.id}: its bundle is no longer stored") from e
    return await asyncio.to_thread(decode, blob)


async def _replay(bundle: CaptureBundle, schema: SchemaDef, data: EngineData) -> ExtractedRecord | None:
    try:
        result = await extract_page(bundle, schema, None, None, "adhoc", data=data)
    except ModeNotSupported as e:
        raise NotReplayable(f"schema {schema.name} version {schema.version}: {e}") from e
    if result.entity is None:
        return None
    content = RecordContent.of(schema, result.entity)
    return ExtractedRecord.of_content(content, mode=result.mode, confidence=result.record_confidence)
