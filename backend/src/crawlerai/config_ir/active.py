"""Active mode (learning-configs spec): the config a page of a site is extracted with, and the drift
record of each page it ran on.

A (site, schema, page kind) with an active config extracts its pages in `config` mode with that config. The config
row is the authority: `extraction_config` holds at most one active config per site, schema and page kind
; a schema edit suspends the schema's active configs, so its pages start cold again (§5.2). Each
page the config ran on, served and resolved, is added to its drift window (`drift.record_run`).
"""

from functools import partial
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.rungs import FetchPlan
from crawlerai.acquire.types import CallEndpoint, FetchPolicy, FetchResult
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.api_recipe.binding import page_data, resolve_params
from crawlerai.config_ir.api_recipe.execute import RecipeExecutor
from crawlerai.config_ir.api_recipe.model import PLACEHOLDER, ApiRecipe
from crawlerai.config_ir.api_recipe.replay import request_for
from crawlerai.config_ir.drift import Drifted, DriftMargins, record_run
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps
from crawlerai.config_ir.progressive import StateKey
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, JobId, RenderMode, SiteId
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


def fetch_plan(config: ActiveConfig | None, render_mode: RenderMode) -> FetchPlan:
    """The fetch plan of the config's field sources (acquisition spec, "Fetch plan"; learning-configs spec, "Locate
    run" step 6): the browser when a running field's source is the browser's render or the surface renders every page
    (`always`); the companion call of each recipe a running `call` field names, and its endpoint for the browser's
    ready wait."""
    ir = config.executor.ir if config is not None and isinstance(config.executor, EngineExecutor) else None
    running = [] if ir is None else _running(ir)
    recipes = {} if ir is None else {s.call: ir.recipes[s.call] for s in running if s.call is not None}
    return FetchPlan(
        browser=render_mode == "always" or any(steps.needs == "browser" for steps in running),
        calls=tuple(partial(companion_request, recipe) for recipe in recipes.values()),
        endpoints=tuple(endpoint(recipe) for recipe in recipes.values()),
    )


def _running(ir: ExtractionConfigIR) -> list[FieldSteps]:
    listed = ir.listing.fields.values() if ir.listing is not None else ()
    return [steps for steps in (*ir.fields.values(), *listed) if steps.status != "suspended"]


def companion_request(
    recipe: ApiRecipe, page: FetchResult, policy: FetchPolicy
) -> tuple[JsonRequest, tuple[str, ...]] | None:
    """`recipe`'s request for the HTTP `page`, bound from the URL it was requested at and, when a binder reads them,
    its JSON documents, with the headers it references from the policy's request context, and the values it was bound
    with (the identity check's keys); None when it binds nothing."""
    url = page.bundle.manifest.url
    data = page_data(ParsedPage.of(page.bundle)) if recipe.requires_page_fetch else {}
    request = request_for(recipe, url, data, policy.context)
    params = resolve_params(recipe, url, data)
    return None if request is None or params is None else (request, tuple(params.values()))


def endpoint(recipe: ApiRecipe) -> CallEndpoint:
    """The endpoint `recipe` calls, as the browser's ready wait matches the page's own calls of it."""
    parts = urlsplit(recipe.url.partition("?")[0])
    segments = parts.path[1:].split("/") if parts.path else []
    return CallEndpoint(
        method=recipe.method,
        origin=f"{parts.scheme}://{parts.netloc}",
        segments=tuple(None if PLACEHOLDER.search(segment) else segment for segment in segments),
    )


def recipe_of(config: ActiveConfig) -> ApiRecipe | None:
    """The API recipe of `config`, which serves its pages (adapters spec), as `_bound` parsed it; None without one."""
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
    published = [name for name, outcome in (result.entity or {}).items() if outcome.status == "published"]
    return await record_run(conn, config.id, result.candidates, margins=margins, job_id=job_id, published=published)
