"""Persist a fetched page (SPEC-02 §4.10): its bundle to the object store, and a `capture` row describing it.

Eval captures never come here: they encode the bundle and write it under their own prefixes (SPEC-03, C1).
"""

import asyncio
from datetime import timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult
from crawlerai.db.models import Capture, CaptureId, SiteId
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import capture_key, encode

CAPTURE_TTL = timedelta(days=30)  # production captures (SPEC-01 §4.4)


async def store_capture(
    conn: AsyncConnection,
    store: ObjectStore,
    result: FetchResult,
    site_id: SiteId,
    *,
    expires_in: timedelta | None = CAPTURE_TTL,
) -> CaptureId:
    """Write the bundle, then insert its row in `conn`'s transaction, so a row never names a missing bundle. A
    failure after the write leaves an unreferenced object under a fresh id, which nothing reads."""
    manifest = result.bundle.manifest
    key = capture_key(manifest.capture_id, manifest.fetched_at)
    # Encoding compresses the whole bundle and the store is synchronous (boto3): both run off the event loop.
    blob = await asyncio.to_thread(encode, result.bundle)
    await asyncio.to_thread(store.put, key, blob)
    await conn.execute(
        insert(Capture).values(
            id=manifest.capture_id,
            site_id=site_id,
            url=manifest.url,
            fetched_at=manifest.fetched_at,
            method=manifest.method,
            status_code=manifest.status_code,
            final_url=manifest.final_url,
            block_class=manifest.block_class,
            object_key=key,
            html_sha256=manifest.html_sha256,
            expires_at=None if expires_in is None else manifest.fetched_at + expires_in,
            size_bytes=len(blob),
            duration_ms=result.duration_ms,
            # SPEC-02 §4.4: the row keeps every rung tried, beside the policy they ran under.
            fetch_policy={
                **manifest.fetch_policy,
                "attempts": [attempt.model_dump(mode="json") for attempt in result.attempts],
            },
        )
    )
    return CaptureId(manifest.capture_id)
