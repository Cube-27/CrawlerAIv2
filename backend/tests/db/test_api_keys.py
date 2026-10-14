"""API keys against Postgres (SPEC-07 §4.2, INV-32): the CLI creates and revokes them, the API accepts a key only while
it is stored and unrevoked, `last_used_at` moves at most once a minute, and starting the API or a worker never
creates, reactivates or resets a key."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import Row, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.api.auth import require_api_key
from crawlerai.api.keys import hash_key
from crawlerai.cli import main
from crawlerai.core.settings import Settings
from crawlerai.db.models import ApiKey, ApiKeyId
from crawlerai.worker.loop import run_worker

pytestmark = pytest.mark.anyio


@pytest.fixture
def env(database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    return monkeypatch


@pytest.fixture
async def keys(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The database, with every key a test created deleted afterwards."""
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        before = set((await conn.execute(select(ApiKey.id))).scalars())
    yield engine
    async with engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id.not_in(before)))
    await engine.dispose()


async def _cli(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    # The CLI runs its own event loop, so it runs on a thread of its own here.
    await asyncio.to_thread(main, list(argv))
    return capsys.readouterr().out


async def _create(capsys: pytest.CaptureFixture[str], label: str = "test") -> dict[str, str]:
    created: dict[str, str] = json.loads(await _cli(capsys, "apikey", "create", "--label", label))
    return created


def _app() -> FastAPI:
    app = create_app(eval_ui=False)
    router = APIRouter()

    @router.get("/v1/whoami")
    async def whoami(key: Annotated[ApiKeyId, Depends(require_api_key)]) -> dict[str, str]:
        return {"key": str(key)}

    app.include_router(router)
    return app


async def _whoami(*keys: str) -> list[httpx.Response]:
    app = _app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as client,
    ):
        return [await client.get("/v1/whoami", headers={"authorization": f"Bearer {key}"}) for key in keys]


async def _row(engine: AsyncEngine, key_id: str) -> Row[Any]:
    async with engine.connect() as conn:
        return (await conn.execute(select(ApiKey).where(ApiKey.id == uuid.UUID(key_id)))).one()


async def test_a_created_key_is_shown_once_stored_hashed_and_accepted(
    env: pytest.MonkeyPatch, keys: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    created = await _create(capsys, "ci")

    row = await _row(keys, created["id"])
    [response] = await _whoami(created["key"])

    assert sorted(created) == ["id", "key", "label", "webhook_secret"]
    assert created["label"] == "ci"
    assert (row.hashed_key, row.label, row.revoked_at) == (hash_key(created["key"]), "ci", None)
    assert created["webhook_secret"] == row.webhook_secret  # the receiver verifies webhook signatures with it
    assert created["key"] not in (row.hashed_key, row.webhook_secret)
    assert response.status_code == 200
    assert response.json() == {"key": created["id"]}


async def test_unknown_and_revoked_keys_are_unauthorized(
    env: pytest.MonkeyPatch, keys: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    created = await _create(capsys)
    revoked = json.loads(await _cli(capsys, "apikey", "revoke", created["id"]))

    responses = await _whoami(created["key"], "ck_" + "0" * 43)

    assert revoked == {"id": created["id"], "revoked": True}
    assert (await _row(keys, created["id"])).revoked_at is not None
    assert [response.status_code for response in responses] == [401, 401]
    assert {response.json()["type"] for response in responses} == {"unauthorized"}


async def test_revoking_twice_keeps_the_first_revocation(
    env: pytest.MonkeyPatch, keys: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    created = await _create(capsys)
    await _cli(capsys, "apikey", "revoke", created["id"])
    first = (await _row(keys, created["id"])).revoked_at

    again = json.loads(await _cli(capsys, "apikey", "revoke", created["id"]))

    assert again == {"id": created["id"], "revoked": False}
    assert (await _row(keys, created["id"])).revoked_at == first


async def test_revoking_an_unknown_key_exits_with_an_error(
    env: pytest.MonkeyPatch, keys: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = str(uuid.uuid4())
    with pytest.raises(SystemExit) as exit_info:
        await _cli(capsys, "apikey", "revoke", unknown)

    assert exit_info.value.code == 2
    assert capsys.readouterr().err == f"crawlerai apikey revoke: no API key {unknown}\n"


@pytest.mark.parametrize(("age_s", "moves"), [(None, True), (30, False), (120, True)])
async def test_last_used_at_moves_at_most_once_a_minute(
    env: pytest.MonkeyPatch,
    keys: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
    age_s: int | None,
    moves: bool,
) -> None:
    created = await _create(capsys)
    key_id = uuid.UUID(created["id"])
    last_used = None if age_s is None else func.now() - timedelta(seconds=age_s)
    async with keys.begin() as conn:
        await conn.execute(update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=last_used))
    before = (await _row(keys, created["id"])).last_used_at

    [response] = await _whoami(created["key"])

    after = (await _row(keys, created["id"])).last_used_at
    assert response.status_code == 200
    assert (after != before) is moves


async def _api_keys(engine: AsyncEngine) -> Sequence[Row[Any]]:
    async with engine.connect() as conn:
        return (await conn.execute(select(ApiKey).order_by(ApiKey.id))).all()


async def test_starting_the_api_and_a_worker_leaves_the_keys_unchanged(
    env: pytest.MonkeyPatch, keys: AsyncEngine, capsys: pytest.CaptureFixture[str]
) -> None:
    # INV-32: keys come only from the CLI. One revoked and one live key, so a reactivation or a reset would show.
    live = await _create(capsys)
    await _cli(capsys, "apikey", "revoke", (await _create(capsys))["id"])
    before = await _api_keys(keys)
    stop = asyncio.Event()
    stop.set()

    app = create_app()
    async with app.router.lifespan_context(app):
        pass
    await run_worker(Settings(), {}, stop)

    assert live["id"] in {str(row.id) for row in before}
    assert await _api_keys(keys) == before
