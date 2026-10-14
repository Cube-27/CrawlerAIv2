"""Active mode (SPEC-08 §4.8, §4.9; ARCHITECTURE §8.4): the config a page of a site is extracted with, and the drift
record of each page it ran on.

A (site, schema version, page kind) with an active config extracts its pages in `config` mode with that config. The
config row is the authority: `extraction_config` holds at most one active config per site, schema and page kind
(ARCHITECTURE §6), and one learned for another schema version than the page's does not run (a new version starts
cold, §5.2). Each page the config ran on, served and resolved, is added to its drift window (`drift.record_run`).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.drift import Drifted, DriftMargins, record_run
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import StateKey
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, JobId, SiteId
from crawlerai.resolve.task import ActiveConfig
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef


async def active_config(
    conn: AsyncConnection, site_id: SiteId, schema: SchemaDef, vocabulary: Vocabulary
) -> ActiveConfig | None:
    """The active config of `site_id` for `schema`'s version and page kind, bound to its executor; None in cold mode."""
    configs = ExtractionConfig
    key = StateKey(site_id, schema.id, schema.version, schema.page_kind)
    active = (*key.config_scope(), configs.schema_version == schema.version, configs.status == "active")
    row = (await conn.execute(select(configs.id, configs.version, configs.ir).where(*active))).one_or_none()
    if row is None:
        return None
    executor = EngineExecutor(ExtractionConfigIR.model_validate(row.ir), vocabulary)
    return ActiveConfig(row.id, row.version, executor)


async def config_by_id(conn: AsyncConnection, config_id: ExtractionConfigId, vocabulary: Vocabulary) -> ActiveConfig:
    """Config `config_id` bound to its executor, whatever its status now: the config a job pinned when it was
    submitted (INV-28)."""
    configs = ExtractionConfig
    row = (await conn.execute(select(configs.version, configs.ir).where(configs.id == config_id))).one()
    executor = EngineExecutor(ExtractionConfigIR.model_validate(row.ir), vocabulary)
    return ActiveConfig(config_id, row.version, executor)


async def record_page(
    conn: AsyncConnection,
    config: ActiveConfig,
    result: ExtractionResult,
    *,
    margins: DriftMargins | None,
    job_id: JobId,
) -> list[Drifted]:
    """Add `result`, a page `config` ran on, to the config's drift window, and return the fields it suspended. A page
    that was not served or did not resolve shows nothing about the config, and is not recorded."""
    if result.outcome not in ("extracted", "partial"):
        return []
    return await record_run(conn, config.id, result.candidates, margins=margins, job_id=job_id)
