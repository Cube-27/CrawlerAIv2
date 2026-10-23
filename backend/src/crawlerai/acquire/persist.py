"""Persist a fetched page: its bundle to the object store, and a `capture` row describing it."""

import asyncio
from datetime import timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import FetchResult, policy_with_attempts
from crawlerai.db.models import Capture, CaptureId, SiteId
from crawlerai.storage.artifacts import artifact_key
from crawlerai.storage.base import ObjectStore
from crawlerai.storage.capture_bundle import capture_key, encode

CAPTURE_TTL = timedelta(days=30)  # production captures


async def store_capture(
    conn: AsyncConnection,
    store: ObjectStore,
    result: FetchResult,
    site_id: SiteId,
    *,
    expires_in: timedelta | None = CAPTURE_TTL,
) -> CaptureId:
    """Write the bundle and the files the browser made of the page beside it (`storage.artifacts`), then insert its row
    in `conn`'s transaction, so a row never names a missing bundle. A
    failure after the write leaves an unreferenced object under a fresh id, which nothing reads."""
    manifest = result.bundle.manifest
    key = capture_key(manifest.capture_id, manifest.fetched_at)
    # Encoding compresses the whole bundle and the store is synchronous (boto3): both run off the event loop.
    blob = await asyncio.to_thread(encode, result.bundle)
    await asyncio.to_thread(store.put, key, blob)
    for name, data in result.artifacts.items():
        await asyncio.to_thread(store.put, artifact_key(key, name), data)
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
            # the row keeps every rung tried, beside the policy they ran under.
            fetch_policy=policy_with_attempts(manifest.fetch_policy, result.attempts),
        )
    )
    return CaptureId(manifest.capture_id)
