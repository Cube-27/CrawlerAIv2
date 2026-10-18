"""The configs service (learning-configs spec): a site's configs, operator corrections, forced
learning and exports, over a connection.

A correction is applied to the latest version of its (site, schema, page kind), so an edit never silently
drops a version someone else added, and the result is always stored as the next version: validated on the site's
held-out pages (§4.7) and active when validation keeps it, else a `draft` whose report says why not.

An export (§4.11) carries the release check (§12.3) run on the pages the config was validated on
(`provenance.validated_on`) that are still stored; a field with no engine value left on any of them is `manual`.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import RowMapping, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir import corrections
from crawlerai.config_ir.activation import NotPending, approve, reject, store_correction
from crawlerai.config_ir.corrections import Correction
from crawlerai.config_ir.exporters.configs import ConfigExport, ConfigFormat, export_config
from crawlerai.config_ir.held_out import load_captures, load_held_out
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import LEARN_AFTER_PAGES, StateKey, lock_state, request_learning
from crawlerai.config_ir.validation import ValidationReport, validate
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.core.errors import Refusal
from crawlerai.db.models import (
    ConfigOrigin,
    ConfigStatus,
    ExtractionConfig,
    ExtractionConfigId,
    FieldStatus,
    JobId,
    PageKind,
    SchemaId,
    Site,
    SiteId,
)
from crawlerai.schemas import registry
from crawlerai.schemas.types import document_digest
from crawlerai.storage.base import ObjectStore


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConfigSummary(_Out):
    """One version of a site's config for one schema and page kind, without its IR."""

    id: ExtractionConfigId
    site: str
    schema_id: SchemaId
    page_kind: PageKind
    version: int
    status: ConfigStatus
    origin: ConfigOrigin
    field_status: dict[str, FieldStatus]
    validation_report: ValidationReport | None


class ConfigDetail(ConfigSummary):
    ir: ExtractionConfigIR


class LearnRequest(_Out):
    """`schema_id` names the schema, and so the page kind, to learn for; `force` re-learns an active one."""

    schema_id: SchemaId
    force: bool = False


class ExportRequest(_Out):
    format: ConfigFormat


class SiteNotFound(Refusal, LookupError):
    pass


class ConfigNotFound(Refusal, LookupError):
    pass


class ConfigConflict(Refusal):
    """The request is valid, but the stored configs or learning state don't allow it now."""


_COLUMNS = (
    ExtractionConfig.id,
    Site.host,
    ExtractionConfig.site_id,
    ExtractionConfig.schema_id,
    ExtractionConfig.page_kind,
    ExtractionConfig.version,
    ExtractionConfig.status,
    ExtractionConfig.origin,
    ExtractionConfig.field_status,
    ExtractionConfig.validation_report,
)
# A list leaves out each version's IR, the largest column.
_SUMMARIES = select(*_COLUMNS).join(Site, Site.id == ExtractionConfig.site_id)
_DETAILS = _SUMMARIES.add_columns(ExtractionConfig.ir)


def _model[M: ConfigSummary](model: type[M], row: RowMapping) -> M:
    return model.model_validate({name: row["host" if name == "site" else name] for name in model.model_fields})


async def list_for_host(conn: AsyncConnection, host: str) -> list[ConfigSummary]:
    """Every version of every config of the site, by schema, page kind, then version."""
    site_id = await _site_id(conn, host)
    query = _SUMMARIES.where(ExtractionConfig.site_id == site_id).order_by(
        ExtractionConfig.schema_id, ExtractionConfig.page_kind, ExtractionConfig.version
    )
    return [_model(ConfigSummary, row) for row in (await conn.execute(query)).mappings()]


async def get(conn: AsyncConnection, config_id: ExtractionConfigId) -> ConfigDetail:
    return _model(ConfigDetail, await _row(conn, config_id))


async def correct(
    conn: AsyncConnection,
    store: ObjectStore,
    vocabulary: Vocabulary,
    config_id: ExtractionConfigId,
    correction: Correction,
) -> ConfigDetail:
    """Apply `correction` to the config `config_id`, which must be its scope's latest version, validate the result on
    the site's held-out pages and store it as the next version; the new version. Raises `InvalidCorrection` when the
    correction does not fit the config."""
    row = await _row(conn, config_id)
    key = StateKey(row["site_id"], row["schema_id"], row["page_kind"])
    await lock_state(conn, key)
    latest = await _latest_version(conn, key)
    if row["version"] != latest:
        raise ConfigConflict(f"config {config_id} is version {row['version']}; correct the latest, version {latest}")
    schema = await registry.get_by_id(conn, key.schema_id)
    ir = ExtractionConfigIR.model_validate(row["ir"])
    if ir.schema_.digest != document_digest(schema):
        # A schema is edited in place (D-0950): this config's steps were learned for the document before the edit.
        raise ConfigConflict(f"config {config_id} was learned for an earlier document of schema {schema.name}")
    corrected = corrections.correct(ir, schema, correction, engine_version=ENGINE_VERSION, at=datetime.now(UTC))
    # §4.4: the site's 8 most recent extracted pages; the operator wrote the steps from none of them.
    held_out = await load_held_out(conn, store, key.site_id, schema, limit=LEARN_AFTER_PAGES)
    # Both executors run on every page: CPU work, so a thread keeps the event loop serving meanwhile.
    validated = await asyncio.to_thread(validate, corrected, schema, held_out, vocabulary)
    return await get(conn, await store_correction(conn, key, corrected, validated, correction.operated()))


async def approve_config(conn: AsyncConnection, config_id: ExtractionConfigId) -> ConfigDetail:
    """Approve the config `config_id`, waiting as `pending_approval` (D-1342): it becomes its site's active config for
    its schema and page kind; the version active before is `suspended`."""
    return await _decide(conn, config_id, approve)


async def reject_config(conn: AsyncConnection, config_id: ExtractionConfigId) -> ConfigDetail:
    """Refuse the config `config_id`, waiting as `pending_approval` (D-1391): it is `suspended` and what served before
    goes on serving."""
    return await _decide(conn, config_id, reject)


async def _decide(
    conn: AsyncConnection,
    config_id: ExtractionConfigId,
    decide: Callable[[AsyncConnection, StateKey, ExtractionConfigId], Awaitable[None]],
) -> ConfigDetail:
    """The config after a person's decision on it; `ConfigConflict` when it is not waiting for one."""
    row = await _row(conn, config_id)
    try:
        await decide(conn, StateKey(row["site_id"], row["schema_id"], row["page_kind"]), config_id)
    except NotPending as e:
        detail = f"config {config_id} is {row['status']}, not the latest version waiting for approval"
        raise ConfigConflict(detail) from e
    return await get(conn, config_id)


async def export(
    conn: AsyncConnection, store: ObjectStore, config_id: ExtractionConfigId, request: ExportRequest
) -> ConfigExport:
    """The config in `request.format`, with its release check on the captures it was validated on."""
    row = await _row(conn, config_id)
    ir = ExtractionConfigIR.model_validate(row["ir"])
    schema = await registry.get_by_id(conn, row["schema_id"])
    held_out = await load_captures(conn, store, schema, ir.provenance.validated_on)
    # The release executor parses and runs every page: CPU work, so a thread keeps the event loop serving meanwhile.
    return await asyncio.to_thread(export_config, request.format, ir, schema, held_out)


async def learn(conn: AsyncConnection, host: str, request: LearnRequest) -> JobId:
    """Start a learning run for the site and schema, and return its `learn` job."""
    site_id = await _site_id(conn, host)
    schema = await registry.get_by_id(conn, request.schema_id)
    key = StateKey(site_id, schema.id, schema.page_kind)
    job_id = await request_learning(conn, key, force=request.force)
    if job_id is None:
        raise ConfigConflict(
            f"{host}, schema {schema.name}: a learning run is in flight, or the site has an "
            "active config and force is not set"
        )
    return job_id


async def _site_id(conn: AsyncConnection, host: str) -> SiteId:
    site_id: SiteId | None = (await conn.execute(select(Site.id).where(Site.host == host.lower()))).scalar_one_or_none()
    if site_id is None:
        raise SiteNotFound(f"no site {host}")
    return site_id


async def _row(conn: AsyncConnection, config_id: ExtractionConfigId) -> RowMapping:
    row = (await conn.execute(_DETAILS.where(ExtractionConfig.id == config_id))).mappings().one_or_none()
    if row is None:
        raise ConfigNotFound(f"no config {config_id}")
    return row


async def _latest_version(conn: AsyncConnection, key: StateKey) -> int:
    query = select(func.max(ExtractionConfig.version)).where(*key.config_scope())
    version: int = (await conn.execute(query)).scalar_one()
    return version
