"""Stored cookie state: the cookies a temporary browser profile's context
held after an `ok` page of a site, kept across jobs and processes in `site_cookie_state`, one row per registrable
domain and engine, and loaded when the site's next temporary profile opens (`acquire.session`). A kept profile holds
its own cookies and uses none. Nothing an HTTP response sets is ever kept.

Cookies only, no other storage; challenge and clearance cookies are kept with the rest. A state is cleaned
before it is kept and again when it is loaded (`kept`): a cookie with an empty value or past its expiry (RFC 6265 §5.3
step 3) is dropped, and of cookies with the same name, domain and path (§5.3 step 11) the last is kept; session
cookies stay. A state with nothing left is not written. The row is encrypted with Fernet
(AES-128-CBC with HMAC-SHA256) under `SNOWCRAWL_COOKIE_KEY`, and rewritten only when the HMAC of its plain state, its
fingerprint, changes.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.session import SessionCookie
from snowcrawl.db.models import BrowserEngine, SiteCookieState

__all__ = ["CookieStore", "kept"]


def kept(cookies: Iterable[SessionCookie], now: float) -> tuple[SessionCookie, ...]:
    """The cookies a state keeps at Unix time `now`: none empty or expired, one per name, domain and path (the last),
    in their order."""
    by_key: dict[tuple[str, str, str], SessionCookie] = {}
    for cookie in cookies:
        if not cookie.value:
            continue
        if cookie.expires is not None and cookie.expires <= now:
            continue
        key = (cookie.name, cookie.domain, cookie.path)
        by_key.pop(key, None)
        by_key[key] = cookie
    return tuple(by_key.values())


@dataclass(frozen=True)
class CookieStore:
    """The stored cookie state in `database`, encrypted with the Fernet `key` (urlsafe base64 of 32 bytes)."""

    database: AsyncEngine
    key: str = field(repr=False)
    clock: Callable[[], float] = time.time

    def __post_init__(self) -> None:
        Fernet(self.key)  # raises ValueError for a key that is not one

    async def load(self, domain: str, engine: BrowserEngine) -> tuple[SessionCookie, ...]:
        """The state kept for the registrable `domain` and `engine`, cleaned (`kept`); none when there is none, or
        when it no longer decrypts under the key."""
        query = select(SiteCookieState.state).where(SiteCookieState.domain == domain, SiteCookieState.engine == engine)
        async with self.database.connect() as conn:
            state = (await conn.execute(query)).scalar_one_or_none()
        if state is None:
            return ()
        try:
            plain = Fernet(self.key).decrypt(state)
        except InvalidToken:
            return ()
        return kept((SessionCookie(**cookie) for cookie in json.loads(plain)), self.clock())

    async def save(self, domain: str, engine: BrowserEngine, cookies: Iterable[SessionCookie]) -> bool:
        """Keep `cookies` (cleaned, `kept`) as the state of the registrable `domain` and `engine`; a state equal to
        the kept one is not rewritten, and one with nothing left is not written but drops the kept one (the context
        no longer holds it). Whether a row was written."""
        cleaned = kept(cookies, self.clock())
        if not cleaned:
            await self.clear(domain, engine)
            return False
        plain = json.dumps([asdict(cookie) for cookie in cleaned], sort_keys=True, separators=(",", ":")).encode()
        fingerprint = hmac.new(self.key.encode(), plain, hashlib.sha256).hexdigest()
        insert = pg_insert(SiteCookieState).values(
            domain=domain,
            engine=engine,
            state=Fernet(self.key).encrypt(plain),
            fingerprint=fingerprint,
            updated_at=func.now(),
        )
        upsert = insert.on_conflict_do_update(
            index_elements=[SiteCookieState.domain, SiteCookieState.engine],
            set_={"state": insert.excluded.state, "fingerprint": fingerprint, "updated_at": func.now()},
            where=SiteCookieState.fingerprint != fingerprint,
        )
        async with self.database.begin() as conn:
            return (await conn.execute(upsert)).rowcount > 0

    async def clear(self, domain: str, engine: BrowserEngine) -> None:
        """Drop the state of the registrable `domain` and `engine`: a block invalidates it whole."""
        async with self.database.begin() as conn:
            await conn.execute(
                delete(SiteCookieState).where(SiteCookieState.domain == domain, SiteCookieState.engine == engine)
            )
