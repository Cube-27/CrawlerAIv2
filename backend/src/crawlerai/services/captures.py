"""The captures service (SPEC-07 §4.6, §4.7, ARCHITECTURE §13.1): replay a stored capture with the current engine,
for debugging, and read a stored capture's markdown again. Nothing either makes is stored.

A capture carries no schema of its own, so it replays against each schema version its stored records follow, the
version the records were made with (schemas are immutable per version, §5.2), so a replayed record compares with
the stored one. A schema version the site has an active config for replays with that config (`config` mode, SPEC-08
§4.8), as a page fetched now would extract; nothing joins its drift window. No replay calls an LLM: `extract_page`
gets no role C.
"""

import asyncio
from collections import OrderedDict

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.config_ir.active import active_config
from crawlerai.content.markdown import markdown
from crawlerai.content.page import ParsedPage
from crawlerai.core.errors import Refusal
from crawlerai.db.models import Capture, CaptureId, Extraction, Record, SiteId
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.records import record_confidence
from crawlerai.resolve.task import ActiveConfig, page_records
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.records import ExtractedRecord
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import CaptureBundle, decode

_COLUMNS = (Capture.id, Capture.site_id, Capture.url, Capture.object_key)
_Capture = Row[CaptureId, SiteId, str, str]

# The markdown of the captures paged most recently, least recent first: enough for a few clients paging at once.
_MARKDOWN_KEPT = 8
_MARKDOWN: OrderedDict[CaptureId, str] = OrderedDict()


class CaptureNotFound(Refusal, LookupError):
    """No capture has the id, or its bundle is no longer stored (captures expire, §15)."""


class NotReplayable(Exception):
    """The capture exists but no record was made from it, so no schema names what to extract."""


async def replay(
    engine: AsyncEngine, store: ObjectStore, data: EngineData, capture_id: CaptureId
) -> list[ExtractedRecord]:
    """The records the current engine makes from the capture, one schema version after another (by id). A page that
    resolves nothing (blocked, an error) adds none; an incomplete one adds its record with `complete=false`, as for
    any caller-supplied URL (§10)."""
    async with engine.connect() as conn:
        capture = await _capture(conn, capture_id)
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
        configs = [await active_config(conn, capture.site_id, schema, data.vocabulary) for schema in schemas]
    if not schemas:
        raise NotReplayable(f"no record was made from capture {capture_id}, so no schema says what to extract")
    bundle = await _bundle(store, capture)
    return [
        record
        for schema, config in zip(schemas, configs, strict=True)
        for record in await _replay(bundle, schema, config, data, capture)
    ]


async def markdown_of(engine: AsyncEngine, store: ObjectStore, capture_id: CaptureId) -> str:
    """The capture's markdown, made again from its bundle: a format is a function of the capture alone (ARCHITECTURE
    §15, INV-26), so it equals the markdown the capture's scrape answered with. The MCP `scrape` tool pages it, one
    call per page, so the last few captures' markdown is kept and a later page is not made again; the capture row is
    still read each time, so a capture that is gone is not found."""
    async with engine.connect() as conn:
        capture = await _capture(conn, capture_id)
    made = _MARKDOWN.get(capture_id)
    if made is None:
        bundle = await _bundle(store, capture)
        made = await asyncio.to_thread(lambda: markdown(ParsedPage.of(bundle), bundle.manifest.final_url))
    _MARKDOWN[capture_id] = made
    _MARKDOWN.move_to_end(capture_id)
    while len(_MARKDOWN) > _MARKDOWN_KEPT:
        _MARKDOWN.popitem(last=False)
    return made


async def _capture(conn: AsyncConnection, capture_id: CaptureId) -> _Capture:
    capture = (await conn.execute(select(*_COLUMNS).where(Capture.id == capture_id))).one_or_none()
    if capture is None:
        raise CaptureNotFound(f"no capture {capture_id}")
    return capture


async def _bundle(store: ObjectStore, capture: _Capture) -> CaptureBundle:
    try:
        blob = await asyncio.to_thread(store.get, capture.object_key)
    except ObjectNotFound as e:
        raise CaptureNotFound(f"capture {capture.id}: its bundle is no longer stored") from e
    return await asyncio.to_thread(decode, blob)


async def _replay(
    bundle: CaptureBundle, schema: SchemaDef, config: ActiveConfig | None, data: EngineData, capture: _Capture
) -> list[ExtractedRecord]:
    if config is not None:
        config = config.for_capture(bundle.manifest, data.adapters)
    result = await extract_page(bundle, schema, None if config is None else config.executor, None, data=data)
    if result.entity is None:
        return []
    # The records a page task would store: a listing's rows are deduplicated by their URLs (§4.10). Their entity keys
    # are not returned, so the capture's URL stands in for the task's canonical one.
    _, drafts = page_records(
        schema, result.entity, result.rows, site_id=capture.site_id, page_url=capture.url, caller_supplied=True
    )
    return [
        ExtractedRecord.of_content(draft, mode=result.mode, confidence=record_confidence(schema, draft.field_meta))
        for draft in drafts
    ]
