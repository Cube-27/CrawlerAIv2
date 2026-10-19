"""Stored cookie state (acquisition spec, "Stored cookie state"): the cookies a browser engine's context held after an
`ok` page of a site, kept across jobs and processes in `site_cookie_state`, one row per site (`site.host`, the page
URL's host) and engine, and loaded into the site's later browser contexts and HTTP and JSON fetches (`acquire.session`).
State flows from the browser to HTTP only: nothing an HTTP response sets is ever kept.

Cookies only, no other storage. A state is cleaned before it is kept and again when it is loaded (`kept`): challenge and
clearance cookies (`adapters.challenges.challenge_cookie`) are never kept, a cookie with an empty value or past its
expiry (RFC 6265 §5.3 step 3, §5.5) is dropped, and of cookies with the same name, domain and path (§5.3 step 11) the
last is kept; session cookies stay. A state with nothing left is not written. The row is encrypted with Fernet
(AES-128-CBC with HMAC-SHA256) under `CRAWLERAI_COOKIE_KEY`, and rewritten only when the HMAC of its plain state, its
fingerprint, changes.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.session import SessionCookie
from crawlerai.adapters.challenges import challenge_cookie
from crawlerai.db.models import BrowserEngine, Site, SiteCookieState

__all__ = ["CookieStore", "kept"]


def kept(cookies: Iterable[SessionCookie], now: float) -> tuple[SessionCookie, ...]:
    """The cookies a state keeps at Unix time `now`: no challenge cookie, none empty or expired, one per name, domain
    and path (the last), in their order."""
    by_key: dict[tuple[str, str, str], SessionCookie] = {}
    for cookie in cookies:
        if not cookie.value or challenge_cookie(cookie.name, cookie.value):
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

    async def load(self, host: str, engine: BrowserEngine) -> tuple[SessionCookie, ...]:
        """The state kept for the site `host` and `engine`, cleaned (`kept`); none when there is none, or when it no
        longer decrypts under the key."""
        query = (
            select(SiteCookieState.state)
            .join(Site, Site.id == SiteCookieState.site_id)
            .where(Site.host == host, SiteCookieState.engine == engine)
        )
        async with self.database.connect() as conn:
            state = (await conn.execute(query)).scalar_one_or_none()
        if state is None:
            return ()
        try:
            plain = Fernet(self.key).decrypt(state)
        except InvalidToken:
            return ()
        return kept((SessionCookie(**cookie) for cookie in json.loads(plain)), self.clock())

    async def save(self, host: str, engine: BrowserEngine, cookies: Iterable[SessionCookie]) -> bool:
        """Keep `cookies` (cleaned, `kept`) as the state of the site `host` and `engine`, unless nothing is left or
        the site has no row; a state equal to the kept one is not rewritten. Whether a row was written."""
        cleaned = kept(cookies, self.clock())
        if not cleaned:
            return False
        plain = json.dumps([asdict(cookie) for cookie in cleaned], sort_keys=True, separators=(",", ":")).encode()
        fingerprint = hmac.new(self.key.encode(), plain, hashlib.sha256).hexdigest()
        site = select(
            Site.id, literal(engine), literal(Fernet(self.key).encrypt(plain)), literal(fingerprint), func.now()
        ).where(Site.host == host)
        insert = pg_insert(SiteCookieState).from_select(
            ["site_id", "engine", "state", "fingerprint", "updated_at"], site
        )
        upsert = insert.on_conflict_do_update(
            index_elements=[SiteCookieState.site_id, SiteCookieState.engine],
            set_={"state": insert.excluded.state, "fingerprint": fingerprint, "updated_at": func.now()},
            where=SiteCookieState.fingerprint != fingerprint,
        )
        async with self.database.begin() as conn:
            return (await conn.execute(upsert)).rowcount > 0

    async def clear(self, host: str, engine: BrowserEngine) -> None:
        """Drop the state of the site `host` and `engine`: a block invalidates it whole."""
        site = select(Site.id).where(Site.host == host).scalar_subquery()
        async with self.database.begin() as conn:
            await conn.execute(
                delete(SiteCookieState).where(SiteCookieState.site_id == site, SiteCookieState.engine == engine)
            )
