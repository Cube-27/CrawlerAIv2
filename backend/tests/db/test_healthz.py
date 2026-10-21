"""`GET /healthz` pings the database and reports the LLM setup check (rest-api spec). The unreachable case is in
`tests/unit/test_api_problems.py`."""

from pathlib import Path

import httpx
import pytest

from crawlerai.api.app import create_app

pytestmark = pytest.mark.anyio


async def test_healthz_is_ok_when_the_database_answers(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    # A listed provider without its key: the setup check reports it without asking any provider.
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.delenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", raising=False)
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client,
    ):
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm": "unavailable"}
