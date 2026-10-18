"""A stored capture read again instead of fetching (rest-api spec `max_age`, `fetch.cache`, D-1435), for the scrape
service and the workers alike.

A capture stands for a fetch only when it reached its page, has not expired, and was made the way the fetch would be:
with the same page steps, the same request context names (the names of the caller's headers and cookies, in a
canonical order and case; their values are never stored, acquisition spec, "Caller request context") and, for a
screenshot, the same area. A capture of a page with a click revealing content is not the page without it.
"""

import asyncio
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from sqlalchemy import ColumnElement, Row, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.errors import Refusal
from crawlerai.db.models import Capture, CaptureId, SiteId, UrlTask
from crawlerai.storage.artifacts import PDF, SCREENSHOT, stored_names
from crawlerai.storage.base import ObjectNotFound, ObjectStore
from crawlerai.storage.capture_bundle import decode

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
    """The latest capture of `canonical` that reached its page (§4.8), within `max_age` seconds (None: any age), has
    not expired and was made with `policy`'s page steps and context names (and its screenshot area, when it asks for a
    screenshot); one an API recipe fetched only with `api` (it holds JSON, not the page). Captures are
    found through the tasks that fetched them, which hold the canonical URL. Its bundle is read with `reread`, outside
    the transaction."""
    made = policy.model_dump(mode="json", include={"steps", "context", "screenshot"})
    query = (
        select(Capture.id, Capture.object_key, Capture.duration_ms, Capture.fetch_policy)
        .join(UrlTask, UrlTask.capture_id == Capture.id)
        .where(
            Capture.site_id == site_id,
            Capture.block_class == "ok",
            or_(Capture.expires_at.is_(None), Capture.expires_at > func.now()),
            UrlTask.canonical_url == canonical,
            func.coalesce(Capture.fetch_policy["steps"], _jsonb([])) == _jsonb(made["steps"]),
            func.coalesce(Capture.fetch_policy["context"], _jsonb(None)) == _jsonb(made["context"]),
        )
        .order_by(Capture.fetched_at.desc())
        .limit(1)
    )
    if max_age is not None:
        query = query.where(Capture.fetched_at >= func.now() - timedelta(seconds=max_age))
    if policy.screenshot is not None:
        # A screenshot of the viewport does not stand for one of the full page, nor the other way round.
        query = query.where(Capture.fetch_policy["screenshot"] == _jsonb(made["screenshot"]))
    if not api:
        query = query.where(Capture.method != "api")
    return (await conn.execute(query)).one_or_none()


def _jsonb(value: object) -> ColumnElement[Any]:
    """`value` as a JSONB value in SQL: its JSON text, bound as text and cast there (a JSONB-typed bind would encode the
    text again, as a JSON string)."""
    return cast(literal(json.dumps(value)), JSONB)


async def reread(store: ObjectStore, row: CaptureRow, formats: Collection[str] = ()) -> Recent | None:
    """The capture's bundle, with the attempts its row keeps (acquisition spec) and the names of the files stored beside
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
    attempts = tuple(AttemptRecord.model_validate(attempt) for attempt in fetch_policy["attempts"])
    return Recent(capture_id, FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=attempts), names)
