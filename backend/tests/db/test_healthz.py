"""`GET /healthz` pings the database (SPEC-07 §4.6) and reports whether the labeling endpoints are mounted, which
the frontend's navigation reads (SPEC-12 §4.3). The unreachable case is in `tests/unit/test_api_problems.py`."""

from pathlib import Path

import httpx
import pytest

from crawlerai.api.app import create_app

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("eval_ui", [False, True])
async def test_healthz_is_ok_when_the_database_answers(
    database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eval_ui: bool
) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    app = create_app(eval_ui=eval_ui)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client,
    ):
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "eval_ui": eval_ui}
