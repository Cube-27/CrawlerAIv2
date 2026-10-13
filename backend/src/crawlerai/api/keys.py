"""API keys (SPEC-07 §4.2, D-0027): `ck_` + 32 random bytes in base62, shown once at creation and stored only as their
SHA-256. Keys are created and revoked only by the CLI (INV-32); the API only looks them up."""

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import ApiKey, ApiKeyId

KEY_PREFIX = "ck_"
_KEY_BYTES = 32
_BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
_BASE62_WIDTH = 43  # 62**43 > 2**256: every 32-byte value fits
# `last_used_at` is written at most this often, so a busy key costs no write per request (SPEC-07 §4.2).
LAST_USED_RESOLUTION = timedelta(minutes=1)

RevokeOutcome = Literal["revoked", "already_revoked", "not_found"]


@dataclass(frozen=True)
class CreatedKey:
    id: ApiKeyId
    label: str
    key: str  # the only time the key exists outside its holder


def base62(raw: bytes) -> str:
    """`raw` as a big-endian number in base62, left-padded with `0` to the width of a key's 32 bytes."""
    value = int.from_bytes(raw)
    digits = []
    while value:
        value, digit = divmod(value, 62)
        digits.append(_BASE62[digit])
    return "".join(reversed(digits)).rjust(_BASE62_WIDTH, "0")


def generate_key() -> str:
    return KEY_PREFIX + base62(secrets.token_bytes(_KEY_BYTES))


def hash_key(key: str) -> str:
    # A key carries 256 random bits, so a plain SHA-256 is enough; a slow password hash would buy nothing (D-0027).
    return hashlib.sha256(key.encode()).hexdigest()


async def create_key(conn: AsyncConnection, label: str) -> CreatedKey:
    key = generate_key()
    # The per-key webhook signing secret (SPEC-10 §4.2) is drawn now, as the column requires one.
    values = {"hashed_key": hash_key(key), "label": label, "webhook_secret": secrets.token_hex(_KEY_BYTES)}
    key_id = (await conn.execute(insert(ApiKey).values(**values).returning(ApiKey.id))).scalar_one()
    return CreatedKey(id=key_id, label=label, key=key)


async def revoke_key(conn: AsyncConnection, key_id: uuid.UUID) -> RevokeOutcome:
    """Revoke a key; a revoked key keeps the time of its first revocation."""
    revoked = await conn.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .returning(ApiKey.id)
    )
    if revoked.first() is not None:
        return "revoked"
    exists = await conn.execute(select(ApiKey.id).where(ApiKey.id == key_id))
    return "already_revoked" if exists.first() is not None else "not_found"


async def authenticate(conn: AsyncConnection, hashed_key: str) -> ApiKeyId | None:
    """The id of the unrevoked key with this hash, marking it used; None for an unknown or revoked key."""
    key_id = (
        await conn.execute(select(ApiKey.id).where(ApiKey.hashed_key == hashed_key, ApiKey.revoked_at.is_(None)))
    ).scalar_one_or_none()
    if key_id is not None:
        await conn.execute(
            update(ApiKey)
            .where(
                ApiKey.id == key_id,
                or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < func.now() - LAST_USED_RESOLUTION),
            )
            .values(last_used_at=func.now())
        )
    return key_id
