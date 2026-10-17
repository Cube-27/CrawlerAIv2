"""The FastAPI application factory (SPEC-07 §4.1): routers, problem details for every error, and the database the
routers share."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from crawlerai.api import mcp, problems
from crawlerai.api.auth import RateLimiter
from crawlerai.api.routers import (
    batch,
    captures,
    configs,
    crawl,
    events,
    extract,
    health,
    jobs,
    project,
    records,
    schedules,
    schemas,
    scrape,
    search,
    usage,
)
from crawlerai.api.routers import eval as eval_router
from crawlerai.api.routers import map as map_router
from crawlerai.core.settings import ApiSettings, Settings
from crawlerai.services.runtime import open_runtime

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with open_runtime(Settings()) as runtime, mcp.running(app):
        app.state.database = runtime.database
        app.state.fetching = runtime.fetching
        app.state.llm = runtime.llm
        app.state.engine_data = runtime.engine_data
        app.state.drift_margins = runtime.drift_margins
        app.state.llm_setup = runtime.llm_setup
        app.state.search = runtime.search
        yield


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
    app.include_router(batch.router)
    app.include_router(map_router.router)
    app.include_router(search.router)
    app.include_router(crawl.router)
    app.include_router(extract.router)
    app.include_router(records.router)
    app.include_router(captures.router)
    app.include_router(jobs.router)
    app.include_router(schedules.router)
    app.include_router(events.router)
    app.include_router(configs.router)
    app.include_router(usage.router)
    app.include_router(project.router)
    if app.state.eval_ui:
        app.include_router(eval_router.router)
    mcp.mount(app)
    return app
