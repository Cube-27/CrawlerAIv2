"""Stored cookie state: kept per registrable domain and engine, encrypted,
cleaned of empty, expired and duplicate cookies (challenge and clearance cookies kept), rewritten only
when it changes, and cleared whole."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.cookie_store import CookieStore
from snowcrawl.acquire.session import ENGINE, SessionCookie
from snowcrawl.db.models import SiteCookieState

NOW = 2_000_000_000.0
DOMAIN = "cookie-state.example.test"


def cookie(name: str, value: str = "v", *, path: str = "/", expires: float | None = None) -> SessionCookie:
    return SessionCookie(name, value, DOMAIN, path, secure=True, host_only=False, expires=expires)


async def _row(engine: AsyncEngine) -> tuple[bytes, str] | None:
    async with engine.connect() as conn:
        query = select(SiteCookieState.state, SiteCookieState.updated_at).where(SiteCookieState.domain == DOMAIN)
        row = (await conn.execute(query)).one_or_none()
    return None if row is None else (row.state, str(row.updated_at))


@pytest.mark.anyio
async def test_a_state_is_kept_encrypted_cleaned_rewritten_only_when_it_changes_and_cleared(
    engine: AsyncEngine,
) -> None:
    store = CookieStore(engine, Fernet.generate_key().decode(), clock=lambda: NOW)
    state = (
        cookie("session", "s1.v"),
        cookie("cf_clearance", "token"),
        cookie("empty", ""),
        cookie("old", expires=NOW - 1),
        cookie("locale", "en"),
        cookie("locale", "fr"),
        cookie("locale", "de", path="/de"),
    )

    assert await store.save(DOMAIN, ENGINE, state)
    first = await _row(engine)
    assert first is not None
    assert b"s1.v" not in first[0]
    loaded = await store.load(DOMAIN, ENGINE)
    assert [(c.name, c.value, c.path) for c in loaded] == [
        ("session", "s1.v", "/"),
        ("cf_clearance", "token", "/"),
        ("locale", "fr", "/"),
        ("locale", "de", "/de"),
    ]

    assert not await store.save(DOMAIN, ENGINE, state)
    assert await _row(engine) == first

    assert not await store.save(DOMAIN, ENGINE, (cookie("empty", ""),))
    assert await store.load(DOMAIN, ENGINE) == ()
    assert await _row(engine) is None
