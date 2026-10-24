"""`GET /healthz` pings the database and reports the LLM setup check. The unreachable case is in
`tests/unit/test_api_problems.py`."""

import httpx
import pytest

from snowcrawl.api.app import create_app

pytestmark = pytest.mark.anyio


async def test_healthz_is_ok_when_the_database_answers(app_env: pytest.MonkeyPatch) -> None:
    # A listed provider without its key: the setup check reports it without asking any provider.
    app_env.setenv("SNOWCRAWL_LLM_PROVIDERS", "anthropic")
    app_env.delenv("SNOWCRAWL_LLM_API_KEY_ANTHROPIC", raising=False)
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client,
    ):
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm": "unavailable"}
