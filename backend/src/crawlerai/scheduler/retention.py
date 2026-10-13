"""Retention (SPEC-01 §2, §4.4; ARCHITECTURE §6, §15): the scheduler's `expire_captures` and `expire_candidates`.

Only production captures expire: a row is deleted only when its `object_key` is under `captures/`, so dev eval
bundles under `eval/` are never touched, whatever their row says (C1). Hidden and fresh bundles live in another
store this module never opens (INV-01).
"""

import asyncio
from datetime import timedelta
from typing import Final

from sqlalchemy import delete, func
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Candidate, Capture
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import CAPTURES_PREFIX

CANDIDATE_TTL: Final = timedelta(days=30)  # ARCHITECTURE §6: candidates are kept 30 days


async def expire_captures(conn: AsyncConnection, store: ObjectStore) -> int:
    """Delete production captures past `expires_at`, rows and bundles, and return how many.

    The bundles are deleted before `conn`'s transaction commits the row deletes. If a bundle delete or the commit
    fails, the rows stay and the next run deletes again (`delete` of a missing key is a no-op), so no bundle is left
    without the row that expires it. Tasks and extractions that cite a capture keep their rows (`capture_id` is
    `ON DELETE SET NULL`).
    """
    deleted = await conn.execute(
        delete(Capture)
        .where(Capture.expires_at < func.now(), Capture.object_key.startswith(CAPTURES_PREFIX, autoescape=True))
        .returning(Capture.object_key)
    )
    keys = list(deleted.scalars())
    # The store is synchronous (boto3): one thread for the whole batch.
    await asyncio.to_thread(_delete_objects, store, keys)
    return len(keys)


def _delete_objects(store: ObjectStore, keys: list[str]) -> None:
    for key in keys:
        store.delete(key)


async def expire_candidates(conn: AsyncConnection) -> int:
    """Delete candidates created more than `CANDIDATE_TTL` ago, and return how many."""
    deleted = await conn.execute(delete(Candidate).where(Candidate.created_at < func.now() - CANDIDATE_TTL))
    return deleted.rowcount
