"""The FastAPI application factory. SPEC-07 adds routers, problem details and the database ping to `/healthz`."""

from fastapi import FastAPI

from crawlerai.api.routers import eval as eval_router
from crawlerai.core.settings import ApiSettings


def create_app(eval_ui: bool | None = None) -> FastAPI:
    """`eval_ui` mounts the labeling endpoints (SPEC-03 §4.10); unset, `CRAWLERAI_EVAL_UI` decides."""
    app = FastAPI(title="CrawlerAI")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if ApiSettings().eval_ui if eval_ui is None else eval_ui:
        app.include_router(eval_router.router)
    return app
