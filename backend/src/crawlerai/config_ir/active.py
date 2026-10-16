"""Active mode (SPEC-08 §4.8, §4.9; ARCHITECTURE §8.4): the config a page of a site is extracted with, and the drift
record of each page it ran on.

A (site, schema, page kind) with an active config extracts its pages in `config` mode with that config. The config
row is the authority: `extraction_config` holds at most one active config per site, schema and page kind
(ARCHITECTURE §6); a schema edit suspends the schema's active configs, so its pages start cold again (§5.2). Each
page the config ran on, served and resolved, is added to its drift window (`drift.record_run`).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.api_recipe.execute import RecipeExecutor
from crawlerai.config_ir.api_recipe.model import ApiRecipe
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
    """The active config of `site_id` for `schema` and its page kind, bound to its executor; None in cold mode."""
    configs = ExtractionConfig
    key = StateKey(site_id, schema.id, schema.page_kind)
    active = (*key.config_scope(), configs.status == "active")
    row = (await conn.execute(select(configs.id, configs.version, configs.ir).where(*active))).one_or_none()
    if row is None:
        return None
    return _bound(row.id, row.version, ExtractionConfigIR.model_validate(row.ir), vocabulary)


async def config_by_id(conn: AsyncConnection, config_id: ExtractionConfigId, vocabulary: Vocabulary) -> ActiveConfig:
    """Config `config_id` bound to its executor, whatever its status now: the config a job pinned when it was
    submitted (INV-28)."""
    configs = ExtractionConfig
    row = (await conn.execute(select(configs.version, configs.ir).where(configs.id == config_id))).one()
    return _bound(config_id, row.version, ExtractionConfigIR.model_validate(row.ir), vocabulary)


def recipe_of(config: ActiveConfig) -> ApiRecipe | None:
    """The API recipe of `config`, which serves its pages (SPEC-09 §4.8), as `_bound` parsed it; None without one."""
    return config.api.recipe if isinstance(config.api, RecipeExecutor) else None


def _bound(config_id: ExtractionConfigId, version: int, ir: ExtractionConfigIR, vocabulary: Vocabulary) -> ActiveConfig:
    """The config bound to its executor, and to its recipe's when it has one: the recipe's locators name the config
    (D-0600)."""
    executor = EngineExecutor(ir, vocabulary)
    recipe = ir.api_recipe
    api = None if recipe is None else RecipeExecutor.of(recipe, str(config_id), executor.field_status)
    return ActiveConfig(config_id, version, executor, api)


async def record_page(
    conn: AsyncConnection,
    config: ActiveConfig,
    result: ExtractionResult,
    *,
    margins: DriftMargins | None,
    job_id: JobId,
) -> list[Drifted]:
    """Add `result`, a page `config` ran on, to the config's drift window, and return the fields it suspended. A page
    that was not served or did not resolve shows nothing about the config, and is not recorded; nor is one its recipe
    served (`ActiveConfig.drifts`)."""
    if not config.drifts or result.outcome not in ("extracted", "partial"):
        return []
    return await record_run(conn, config.id, result.candidates, margins=margins, job_id=job_id)
