"""The FastAPI application factory (SPEC-07 §4.1): routers, problem details for every error, and the database the
routers share."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.api import problems
from crawlerai.api.auth import RateLimiter
from crawlerai.api.routers import eval as eval_router
from crawlerai.api.routers import health, schemas
from crawlerai.core.settings import ApiSettings, DatabaseSettings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_async_engine(DatabaseSettings().database_url.get_secret_value())
    app.state.database = engine
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
    if app.state.eval_ui:
        app.include_router(eval_router.router)
    return app
