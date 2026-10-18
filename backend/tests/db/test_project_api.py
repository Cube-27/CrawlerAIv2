"""`GET`/`PATCH /v1/project/settings`: the project's LLM call cap and its cap on a key's uncharged role S calls, null
for none (owner, 2026-10-16; D-1282), and whether learned configs wait for approval, off until set (D-1342)."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, Project

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(
    engine: AsyncEngine, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with engine.begin() as conn:
        key = await create_key(conn, "project-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        yield client
    async with engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
        await conn.execute(
            update(Project).values(llm_call_cap=None, draft_call_cap=None, require_config_approval=False)
        )


async def test_the_caps_are_none_until_set_and_can_be_cleared(client: httpx.AsyncClient) -> None:
    before = await client.get("/v1/project/settings")
    capped = await client.patch("/v1/project/settings", json={**NONE, "llm_call_cap": 25, "draft_call_cap": 4})
    read = await client.get("/v1/project/settings")
    cleared = await client.patch("/v1/project/settings", json=NONE)

    assert [(r.status_code, r.json()) for r in (before, capped, read)] == [
        (200, NONE),
        (200, {**NONE, "llm_call_cap": 25, "draft_call_cap": 4}),
        (200, {**NONE, "llm_call_cap": 25, "draft_call_cap": 4}),
    ]
    assert (cleared.status_code, (await client.get("/v1/project/settings")).json()) == (200, NONE)


NONE = {"llm_call_cap": None, "draft_call_cap": None, "require_config_approval": False}


async def test_config_approval_is_off_until_set(client: httpx.AsyncClient) -> None:
    on = await client.patch("/v1/project/settings", json={**NONE, "require_config_approval": True})

    assert (on.status_code, (await client.get("/v1/project/settings")).json()) == (
        200,
        {**NONE, "require_config_approval": True},
    )


@pytest.mark.parametrize(
    "body",
    [
        {**NONE, "llm_call_cap": -1},
        {**NONE, "draft_call_cap": -1},
        # Past a PostgreSQL `integer` column's range (§8.1.1): refused, not a failed write.
        {**NONE, "llm_call_cap": 2**31},
        {**NONE, "draft_call_cap": 2**31},
        {"llm_call_cap": None, "draft_call_cap": None},
        {},
        {**NONE, "other": 1},
    ],
)
async def test_an_invalid_cap_is_refused(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.patch("/v1/project/settings", json=body)

    assert response.status_code == 422
