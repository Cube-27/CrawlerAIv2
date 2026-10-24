"""A stored capture read again instead of fetching (`max_age`, `fetch.cache`), for the scrape
service and the workers alike.

A capture stands for a fetch only when it reached its page, has not expired, and was made the way the fetch would be:
with the same page steps, the same request context (the names of the caller's headers and cookies, in a canonical order
and case, and the keyed digest of their values, `core.context_digest`, the values are never stored), so a capture
fetched with other values, or with none, never stands for the fetch,
and, for a screenshot, the same area. A capture of a page with a click revealing content is not the page without it.
"""

import asyncio
from collections.abc import Collection
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.acquire.stored_fetch import StoredFetch, made_as
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.core.errors import Refusal
from snowcrawl.db.models import Capture, CaptureId, SiteId, UrlTask
from snowcrawl.storage.artifacts import PDF, SCREENSHOT, stored_names
from snowcrawl.storage.base import ObjectNotFound, ObjectStore
from snowcrawl.storage.capture_bundle import decode

__all__ = ["NOT_CACHED", "CaptureRow", "NotCached", "Recent", "recent_capture", "reread"]

# The reason a fetch that may only read a stored capture (`cache: only`) found none.
NOT_CACHED = "not_cached"
# The artifacts that are the files of a format.
_FILE_FORMATS: Final = {SCREENSHOT: "screenshot", PDF: "pdf"}


class NotCached(Refusal):
    """`fetch.cache` is `only` and no stored capture stands for the page."""


@dataclass(frozen=True)
class Recent:
    """A stored capture read again: its id, the fetch that made it, and the names of the files stored beside it."""

    capture_id: CaptureId
    result: FetchResult
    artifacts: frozenset[str] = frozenset()


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
    """The latest capture of `canonical` that reached its page, within `max_age` seconds (None: any age), has
    not expired and was made with `policy`'s page steps and context, names and value digest (and its screenshot area,
    when it asks for a screenshot; for a content-only read, one judged by that rule or rendered, `content_only`); one
    an API recipe fetched only with `api` (it holds JSON, not the page). Captures are found through the tasks that
    fetched them, which hold the canonical URL. Its bundle is read with `reread`,
    outside the transaction."""
    query = (
        select(Capture.id, Capture.object_key, Capture.duration_ms, Capture.fetch_policy)
        .join(UrlTask, UrlTask.capture_id == Capture.id)
        .where(
            Capture.site_id == site_id,
            Capture.block_class == "ok",
            or_(Capture.expires_at.is_(None), Capture.expires_at > func.now()),
            UrlTask.canonical_url == canonical,
            made_as(policy),
        )
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    if max_age is not None:
        query = query.where(Capture.fetched_at >= func.now() - timedelta(seconds=max_age))
    if not api:
        query = query.where(Capture.method != "api")
    return (await conn.execute(query)).one_or_none()


async def reread(store: ObjectStore, row: CaptureRow, formats: Collection[str] = ()) -> Recent | None:
    """The capture's bundle, with the attempts its row keeps and the names of the files stored beside
    it; None when its bundle is gone, or a screenshot or PDF among `formats` was not stored with it."""
    capture_id, object_key, duration_ms, fetch_policy = row
    try:
        blob = await asyncio.to_thread(store.get, object_key)
    except ObjectNotFound:
        return None
    names = await asyncio.to_thread(stored_names, store, object_key)
    if not {name for name, format in _FILE_FORMATS.items() if format in formats} <= names:
        return None
    bundle = await asyncio.to_thread(decode, blob)
    attempts = StoredFetch.model_validate(fetch_policy).attempts
    return Recent(capture_id, FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=attempts), names)
