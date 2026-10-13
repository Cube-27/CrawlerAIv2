"""Config exports (SPEC-08 §4.10, §4.11, ARCHITECTURE §12.2, §12.3): a stored config as `json` or `platform_draft`,
with the release check run on its held-out pages.

The held-out pages are the captures the config was validated on (`provenance.validated_on`), each with the records the
engine stored from its latest extraction for the config's schema version: a detail page's one, or a listing's one per
row in the order they were stored, which is the page's row order. A capture whose bundle is no longer stored (captures
expire, §15), or with no such record, is left out; a field with no engine value left on any page is `manual`.
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.config_ir.exporters.configs import ConfigExport, ConfigFormat, export_config
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.validation import Facts, HeldOutPage
from crawlerai.content.context import page_context
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import (
    Capture,
    CaptureId,
    Extraction,
    ExtractionConfig,
    ExtractionConfigId,
    ExtractionId,
    Record,
)
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

type _Data = Mapping[str, JsonValue]


class ExportRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    format: ConfigFormat


class ConfigNotFound(LookupError):
    pass


async def export(
    engine: AsyncEngine, store: ObjectStore, config_id: ExtractionConfigId, fmt: ConfigFormat
) -> ConfigExport:
    async with engine.connect() as conn:
        query = select(ExtractionConfig.ir, ExtractionConfig.schema_id).where(ExtractionConfig.id == config_id)
        row = (await conn.execute(query)).one_or_none()
        if row is None:
            raise ConfigNotFound(f"no config {config_id}")
        ir = ExtractionConfigIR.model_validate(row.ir)
        schema = await registry.get_by_id(conn, row.schema_id)
        stored = await _stored(conn, schema, ir.provenance.validated_on)
    # Reading the bundles, parsing the pages and running the release executor on them is blocking and CPU work, so
    # one thread does it while the event loop serves other requests.
    return await asyncio.to_thread(_export, store, fmt, ir, schema, stored)


@dataclass(frozen=True, slots=True)
class _Stored:
    """A held-out capture's object key and the records of its latest extraction, in the order they were stored."""

    object_key: str
    extraction_id: ExtractionId
    records: list[_Data] = field(default_factory=list)


async def _stored(conn: AsyncConnection, schema: SchemaDef, captures: Sequence[CaptureId]) -> dict[CaptureId, _Stored]:
    """Each capture with records of `schema`'s version, in `captures` order."""
    query = (
        select(Capture.id, Capture.object_key, Record.extraction_id, Record.data)
        .join(Extraction, Extraction.capture_id == Capture.id)
        .join(Record, Record.extraction_id == Extraction.id)
        .where(Capture.id.in_(captures), Record.schema_id == schema.id, Record.schema_version == schema.version)
        .order_by(Capture.id, Extraction.id.desc(), Record.id)  # ids are UUIDv7: newest extraction, records in order
    )
    found: dict[CaptureId, _Stored] = {}
    for row in await conn.execute(query):
        stored = found.setdefault(row.id, _Stored(row.object_key, row.extraction_id))
        if stored.extraction_id == row.extraction_id:
            stored.records.append(row.data)
    return {capture: found[capture] for capture in captures if capture in found}


def _export(
    store: ObjectStore, fmt: ConfigFormat, ir: ExtractionConfigIR, schema: SchemaDef, stored: dict[CaptureId, _Stored]
) -> ConfigExport:
    pages = [page for capture, s in stored.items() if (page := _held_out(store, schema, capture, s)) is not None]
    return export_config(fmt, ir, schema, pages)


def _held_out(store: ObjectStore, schema: SchemaDef, capture_id: CaptureId, stored: _Stored) -> HeldOutPage | None:
    try:
        bundle = decode(store.get(stored.object_key))
    except ObjectNotFound:
        return None
    page = ParsedPage.of(bundle)
    ctx = page_context(page, bundle.manifest.final_url, bundle.manifest.fetched_at)
    facts, rows = _facts(schema, stored.records)
    return HeldOutPage(capture_id, page, ctx, facts, rows)


def _facts(schema: SchemaDef, records: list[_Data]) -> tuple[Facts, tuple[Facts, ...]]:
    """The page's published values and a listing's rows'; `record.data` holds published fields only (§6)."""
    if schema.page_kind == "detail":
        return Facts(published=dict(records[0])), ()
    page_fields = {name for name, spec in schema.fields.items() if spec.scope == "page"}
    page = Facts(published={name: value for name, value in records[0].items() if name in page_fields})
    rows = tuple(
        Facts(published={name: value for name, value in data.items() if name not in page_fields}) for data in records
    )
    return page, rows
