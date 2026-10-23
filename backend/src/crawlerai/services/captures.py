"""The captures service: replay a stored capture with the current engine,
for debugging, and read a stored capture's markdown again. Nothing either makes is stored.

A capture carries no schema of its own, so it replays against each schema its stored records follow, with the
schema's current document (a schema is edited in place). A schema the site has an active config for replays
with that config (`config` mode), as a page fetched now would extract; nothing joins its drift
window. No replay calls an LLM: `extract_page` gets no role C.
"""

import asyncio
from collections import OrderedDict

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.config_ir.active import active_config
from crawlerai.content.markdown import markdown
from crawlerai.content.page import ParsedPage
from crawlerai.core.errors import Refusal
from crawlerai.db.models import Capture, CaptureId, Extraction, JobId, Record, SiteId, TaskRecord, UrlTask
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.records import record_confidence
from crawlerai.resolve.task import ActiveConfig, page_records
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.records import ExtractedRecord
from crawlerai.storage.artifacts import ARTIFACT_TYPES, artifact_key
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import CaptureBundle, decode

_COLUMNS = (Capture.id, Capture.site_id, Capture.url, Capture.object_key)
_Capture = Row[CaptureId, SiteId, str, str]

# The markdown of the captures paged most recently, least recent first: enough for a few clients paging at once.
_MARKDOWN_KEPT = 8
_MARKDOWN: OrderedDict[CaptureId, str] = OrderedDict()


class CaptureNotFound(Refusal, LookupError):
    """No capture has the id, or its bundle is no longer stored (captures expire)."""


class NotReplayable(Exception):
    """The capture exists but no record was made from it, so no schema names what to extract."""


async def replay(
    engine: AsyncEngine, store: ObjectStore, data: EngineData, capture_id: CaptureId, job_id: JobId | None = None
) -> list[ExtractedRecord]:
    """The records the current engine makes from the capture, one schema after another (by id), against the schemas
    of the records stored from it, those of `job_id` when given. A page that resolves nothing (blocked, an error) adds
    none; an incomplete one adds its record with `complete=false`, as for any caller-supplied URL. It reads the
    capture's stored bundle and the database, and reaches no network (`reextract_job` runs it for a job's captures)."""
    async with engine.connect() as conn:
        capture = await _capture(conn, capture_id)
        if job_id is None:
            stored = select(Record.schema_id).distinct().join(Extraction, Extraction.id == Record.extraction_id)
            stored = stored.where(Extraction.capture_id == capture_id)
        else:
            # The records the job's tasks stand for, equal records of an earlier job's included.
            stored = select(Record.schema_id).distinct().join(TaskRecord, TaskRecord.record_id == Record.id)
            stored = stored.join(UrlTask, UrlTask.id == TaskRecord.url_task_id)
            stored = stored.where(UrlTask.job_id == job_id, UrlTask.capture_id == capture_id)
        schema_ids = (await conn.execute(stored.order_by(Record.schema_id))).scalars()
        schemas = [await registry.get_by_id(conn, schema_id) for schema_id in schema_ids]
        configs = [
            await active_config(conn, capture.site_id, schema, data.vocabulary, capture.url) for schema in schemas
        ]
    if not schemas:
        raise NotReplayable(f"no record was made from capture {capture_id}, so no schema says what to extract")
    bundle = await _bundle(store, capture)
    return [
        record
        for schema, config in zip(schemas, configs, strict=True)
        for record in await _replay(bundle, schema, config, data, capture)
    ]


async def markdown_of(engine: AsyncEngine, store: ObjectStore, capture_id: CaptureId) -> str:
    """The capture's markdown, made again from its bundle: a format is a function of the capture alone, so it
    equals the markdown the capture's scrape answered with. The MCP `scrape` tool pages it, one call per page, so the
    last few captures' markdown is kept and a later page is not made again; the capture row is still read each time, so
    a capture that is gone is not found."""
    async with engine.connect() as conn:
        capture = await _capture(conn, capture_id)
    made = _MARKDOWN.get(capture_id)
    if made is None:
        bundle = await _bundle(store, capture)
        manifest = bundle.manifest
        made = await asyncio.to_thread(lambda: markdown(ParsedPage.of(bundle), manifest.final_url))
    _MARKDOWN[capture_id] = made
    _MARKDOWN.move_to_end(capture_id)
    while len(_MARKDOWN) > _MARKDOWN_KEPT:
        _MARKDOWN.popitem(last=False)
    return made


async def artifact(engine: AsyncEngine, store: ObjectStore, capture_id: CaptureId, name: str) -> bytes:
    """The artifact `name` of the capture (`storage.artifacts`): the screenshot or PDF the browser made of its page.
    Raises `CaptureNotFound` for a capture that is gone, and for one that has no such artifact."""
    if name not in ARTIFACT_TYPES:
        raise CaptureNotFound(f"no artifact {name!r}")
    async with engine.connect() as conn:
        capture = await _capture(conn, capture_id)
    try:
        return await asyncio.to_thread(store.get, artifact_key(capture.object_key, name))
    except (ObjectNotFound, ValueError) as e:  # a ValueError: the bundle is outside `captures/`, so has none
        raise CaptureNotFound(f"capture {capture_id} has no artifact {name!r}") from e


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
    # The records a page task would store: a listing's rows are deduplicated by their URLs. Their entity keys
    # are not returned, so the capture's URL stands in for the task's canonical one.
    _, drafts = page_records(
        schema,
        result.entity,
        result.rows,
        site_id=capture.site_id,
        page_url=capture.url,
        caller_supplied=True,
        diagnostics=result.diagnostics,
    )
    return [
        ExtractedRecord.of_content(
            schema, draft, mode=result.mode, confidence=record_confidence(schema, draft.field_meta)
        )
        for draft in drafts
    ]
