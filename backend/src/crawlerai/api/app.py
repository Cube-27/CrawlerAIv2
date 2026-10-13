"""The FastAPI application factory (SPEC-07 §4.1): routers, problem details for every error, and the database the
routers share."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.acquire.browser import fetch_browser, open_browser
from crawlerai.acquire.http import fetch_http
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api import problems
from crawlerai.api.auth import RateLimiter
from crawlerai.api.routers import captures, config_exports, configs, health, jobs, records, schemas, scrape
from crawlerai.api.routers import eval as eval_router
from crawlerai.collect.schema_org_map import VocabularyMissing
from crawlerai.core.engine_version import ENGINE_VERSION, backend_dir, data_dir
from crawlerai.core.settings import ApiSettings, Settings
from crawlerai.llm.providers.from_settings import client_from_settings
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.scrape import Fetching
from crawlerai.storage import open_store

log = logging.getLogger(__name__)


def _fetching(settings: Settings) -> Fetching:
    """The rungs `scrape` fetches with, all through one SSRF guard."""
    connector = SafeConnector()
    pools = settings.proxy_pools

    async def browser(url: str, policy: FetchPolicy) -> FetchResult:
        # The browser is a rung of last resort here (ARCHITECTURE §7.1), so it is launched per fetch rather than kept
        # running beside every API process.
        async with open_browser() as session:
            return await fetch_browser(
                url, policy, session=session, engine_version=ENGINE_VERSION, connector=connector, pools=pools
            )

    http = partial(
        fetch_http, engine_version=ENGINE_VERSION, impersonate=settings.impersonate, connector=connector, pools=pools
    )
    return Fetching(Rungs(http=http, browser=browser), connector, open_store(settings.object_store), HostLimiter())


def _engine_data() -> EngineData | None:
    """The engine's data files from `backend/data/` of the source tree, for `records` and replays; None where they
    are not there (an installed package, or a tree without `crawlerai data fetch`): `records` and replays then answer
    503, and the other formats work (D-0492 ships the files)."""
    backend = backend_dir(Path(__file__))
    if backend is None:
        log.warning("no backend source tree: records and replays are unavailable")
        return None
    try:
        return EngineData.load(data_dir(backend))
    except VocabularyMissing as e:
        log.warning("records and replays are unavailable: %s", e)
        return None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    engine = create_async_engine(settings.database_url.get_secret_value())
    app.state.database = engine
    app.state.fetching = _fetching(settings)
    app.state.llm = client_from_settings(settings, engine)
    app.state.engine_data = _engine_data()
    try:
        yield
    finally:
        await engine.dispose()


def create_app(eval_ui: bool | None = None) -> FastAPI:
    """`eval_ui` mounts the labeling endpoints (SPEC-03 §4.10); unset, `CRAWLERAI_EVAL_UI` decides. Settings are
    read at startup, not here, so `crawlerai openapi` builds the document without a database."""
    app = FastAPI(title="CrawlerAI", lifespan=_lifespan, openapi_url="/v1/openapi.json")  # SPEC-07 §4.6
    settings = ApiSettings()
    app.state.eval_ui = settings.eval_ui if eval_ui is None else eval_ui
    app.state.trusted_proxies = settings.trusted_proxies
    app.state.rate_limiter = RateLimiter(settings.api_rate_per_s, settings.api_rate_burst)
    problems.install(app)
    app.include_router(health.router)
    app.include_router(schemas.router)
    app.include_router(scrape.router)
    app.include_router(records.router)
    app.include_router(captures.router)
    app.include_router(jobs.router)
    app.include_router(configs.router)
    app.include_router(config_exports.router)
    if app.state.eval_ui:
        app.include_router(eval_router.router)
    return app
