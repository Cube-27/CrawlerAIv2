"""Stored cookie state (acquisition spec, "Stored cookie state"): kept per site and engine, encrypted, cleaned of
challenge, empty, expired and duplicate cookies, rewritten only when it changes, and cleared whole."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.cookie_store import CookieStore
from crawlerai.acquire.session import ENGINE, SessionCookie
from crawlerai.db.models import SiteCookieState, SiteId

NOW = 2_000_000_000.0


def cookie(name: str, value: str = "v", *, path: str = "/", expires: float | None = None) -> SessionCookie:
    return SessionCookie(name, value, "example.test", path, secure=True, host_only=False, expires=expires)


async def _row(engine: AsyncEngine, site: SiteId) -> tuple[bytes, str] | None:
    async with engine.connect() as conn:
        query = select(SiteCookieState.state, SiteCookieState.updated_at).where(SiteCookieState.site_id == site)
        row = (await conn.execute(query)).one_or_none()
    return None if row is None else (row.state, str(row.updated_at))


@pytest.mark.anyio
async def test_a_state_is_kept_encrypted_cleaned_rewritten_only_when_it_changes_and_cleared(
    engine: AsyncEngine, own_origin: str, site: SiteId
) -> None:
    host = own_origin.removeprefix("https://")
    store = CookieStore(engine, Fernet.generate_key().decode(), clock=lambda: NOW)
    state = (
        cookie("session", "s1"),
        cookie("cf_clearance", "token"),
        cookie("renamed", "3~-1~abc"),
        cookie("empty", ""),
        cookie("old", expires=NOW - 1),
        cookie("locale", "en"),
        cookie("locale", "fr"),
        cookie("locale", "de", path="/de"),
    )

    assert await store.save(host, ENGINE, state)
    first = await _row(engine, site)
    assert first is not None
    assert b"s1" not in first[0]
    loaded = await store.load(host, ENGINE)
    assert [(c.name, c.value, c.path) for c in loaded] == [
        ("session", "s1", "/"),
        ("locale", "fr", "/"),
        ("locale", "de", "/de"),
    ]

    assert not await store.save(host, ENGINE, state)
    assert await _row(engine, site) == first

    await store.clear(host, ENGINE)
    assert await store.load(host, ENGINE) == ()
    assert not await store.save(host, ENGINE, (cookie("datadome", "x"),))
    assert await _row(engine, site) is None
