"""A stored capture read again instead of fetching (SPEC-07 §4.4 `max_age`, `fetch.cache`, D-1435), for the scrape
service and the workers alike.

A capture stands for a fetch only when it reached its page, has not expired, and was made the way the fetch would be:
with the same page steps and the same request context names (the names of the caller's headers and cookies; their
values are never stored, D-1432). A capture of a page with a click revealing content is not the page without it.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Row, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.errors import Refusal
from crawlerai.db.models import Capture, CaptureId, SiteId, UrlTask
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

__all__ = ["NOT_CACHED", "CaptureRow", "NotCached", "Recent", "recent_capture", "reread"]

# The reason a fetch that may only read a stored capture (`cache: only`) found none.
NOT_CACHED = "not_cached"


class NotCached(Refusal):
    """`fetch.cache` is `only` and no stored capture stands for the page."""


@dataclass(frozen=True)
class Recent:
    """A stored capture read again: its id, and the fetch that made it."""

    capture_id: CaptureId
    result: FetchResult


CaptureRow = Row[CaptureId, str, int, dict[str, Any]]


async def recent_capture(
    conn: AsyncConnection,
    site_id: SiteId,
    canonical: str,
    policy: FetchPolicy,
    *,
    max_age: int | None,
    api: bool = False,
) -> CaptureRow | None:
    """The latest capture of `canonical` that reached its page (§4.8), within `max_age` seconds (None: any age), has
    not expired and was made with `policy`'s page steps and context names; one an API recipe fetched only with `api`
    (SPEC-09 §4.8: it holds JSON, not the page). Captures are found through the tasks that fetched them, which hold the
    canonical URL. Its bundle is read with `reread`, outside the transaction."""
    made = policy.model_dump(mode="json", include={"steps", "context"})
    query = (
        select(Capture.id, Capture.object_key, Capture.duration_ms, Capture.fetch_policy)
        .join(UrlTask, UrlTask.capture_id == Capture.id)
        .where(
            Capture.site_id == site_id,
            Capture.block_class == "ok",
            or_(Capture.expires_at.is_(None), Capture.expires_at > func.now()),
            UrlTask.canonical_url == canonical,
            func.coalesce(Capture.fetch_policy["steps"], cast("[]", JSONB)) == cast(json.dumps(made["steps"]), JSONB),
            func.coalesce(Capture.fetch_policy["context"], cast("null", JSONB))
            == cast(json.dumps(made["context"]), JSONB),
        )
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    if max_age is not None:
        query = query.where(Capture.fetched_at >= func.now() - timedelta(seconds=max_age))
    if not api:
        query = query.where(Capture.method != "api")
    return (await conn.execute(query)).one_or_none()


async def reread(store: ObjectStore, row: CaptureRow) -> Recent | None:
    """The capture's bundle, with the attempts its row keeps (SPEC-02 §4.4); None when its bundle is gone."""
    capture_id, object_key, duration_ms, fetch_policy = row
    try:
        blob = await asyncio.to_thread(store.get, object_key)
    except ObjectNotFound:
        return None
    bundle = await asyncio.to_thread(decode, blob)
    attempts = tuple(AttemptRecord.model_validate(attempt) for attempt in fetch_policy["attempts"])
    return Recent(capture_id, FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=attempts))
