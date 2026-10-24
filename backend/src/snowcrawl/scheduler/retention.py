"""Retention: the scheduler's `expire_captures`, `expire_candidates` and
`expire_webhooks`.

Only production captures expire: a row is deleted only when its `object_key` is under `captures/`, so a bundle
elsewhere is never touched, whatever its row says.
"""

import asyncio
from datetime import timedelta
from typing import Final

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.db.models import Candidate, Capture, WebhookDelivery, WebhookEvent
from snowcrawl.storage.artifacts import ARTIFACT_TYPES, artifact_key
from snowcrawl.storage.base import ObjectStore
from snowcrawl.storage.capture_bundle import CAPTURES_PREFIX

CANDIDATE_TTL: Final = timedelta(days=30)  # Candidates are kept 30 days
# An ended webhook delivery and its events are kept 30 days, for `GET /v1/jobs/{id}/webhook-deliveries`.
WEBHOOK_TTL: Final = timedelta(days=30)
# Rows per transaction. It bounds how long a run holds row locks, and how many bundles one failed run leaves deleted
# under rows that stay; the scheduler runs a full batch again at once, so a backlog still drains in one turn.
RETENTION_BATCH: Final = 1000


async def expire_captures(conn: AsyncConnection, store: ObjectStore, *, batch: int) -> int:
    """Delete up to `batch` production captures past `expires_at`, the longest expired first, rows and bundles, and
    return how many.

    The bundles are deleted before `conn`'s transaction commits the row deletes. If a bundle delete or the commit
    fails, the rows stay and the next run deletes again (`delete` of a missing key is a no-op), so no bundle is left
    without the row that expires it. The other direction has a window: until that next run, up to one batch of rows,
    all already past `expires_at`, may name bundles that are gone. Tasks and extractions that cite a capture keep
    their rows (`capture_id` is `ON DELETE SET NULL`).
    """
    due = (
        select(Capture.id)
        .where(Capture.expires_at < func.now(), Capture.object_key.startswith(CAPTURES_PREFIX, autoescape=True))
        .order_by(Capture.expires_at)
        .limit(batch)
    )
    deleted = await conn.execute(delete(Capture).where(Capture.id.in_(due)).returning(Capture.object_key))
    keys = list(deleted.scalars())
    # The store is synchronous (boto3): one thread for the whole batch.
    await asyncio.to_thread(_delete_objects, store, keys)
    return len(keys)


def _delete_objects(store: ObjectStore, keys: list[str]) -> None:
    for key in keys:
        store.delete(key)
        for name in ARTIFACT_TYPES:  # the screenshot and PDF of the capture go with its bundle
            store.delete(artifact_key(key, name))


async def expire_candidates(conn: AsyncConnection, *, batch: int) -> int:
    """Delete up to `batch` candidates created more than `CANDIDATE_TTL` ago, the oldest first, and return how many."""
    due = (
        select(Candidate.id)
        .where(Candidate.created_at < func.now() - CANDIDATE_TTL)
        .order_by(Candidate.created_at)
        .limit(batch)
    )
    deleted = await conn.execute(delete(Candidate).where(Candidate.id.in_(due)))
    return deleted.rowcount


async def expire_webhooks(conn: AsyncConnection, *, batch: int) -> int:
    """Delete up to `batch` ended webhook deliveries (`delivered` or `failed`) created more than `WEBHOOK_TTL` ago, the
    oldest first, with the events they carried, and return how many deliveries. A pending delivery is never deleted:
    it is still owed."""
    due = (
        select(WebhookDelivery.id)
        .where(WebhookDelivery.status != "pending", WebhookDelivery.created_at < func.now() - WEBHOOK_TTL)
        .order_by(WebhookDelivery.created_at)
        .limit(batch)
    )
    ids = list((await conn.execute(due)).scalars())
    await conn.execute(delete(WebhookEvent).where(WebhookEvent.delivery_id.in_(ids)))
    deleted = await conn.execute(delete(WebhookDelivery).where(WebhookDelivery.id.in_(ids)))
    return deleted.rowcount
