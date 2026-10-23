"""The FastAPI application factory: routers, problem details for every error, and the database the
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
from crawlerai.api.routers import map as map_router
from crawlerai.core.settings import ApiSettings, Settings
from crawlerai.services.runtime import open_runtime

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with open_runtime(Settings()) as runtime, mcp.running(app):
        app.state.runtime = runtime
        yield


def create_app() -> FastAPI:
    """Settings that need a database are read at startup, not here, so `crawlerai openapi` builds the document
    without one."""
    app = FastAPI(title="CrawlerAI", lifespan=_lifespan, openapi_url="/v1/openapi.json")
    settings = ApiSettings()
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
    mcp.mount(app)
    return app
