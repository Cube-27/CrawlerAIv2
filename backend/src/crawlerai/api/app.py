"""The FastAPI application factory. SPEC-07 adds routers, problem details and the database ping to `/healthz`."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="CrawlerAI")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
