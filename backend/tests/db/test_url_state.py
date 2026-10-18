"""`url_state` for conditional GET (jobs spec) and the content fingerprint (§4.3), against a real Postgres: a 200
stores the validators a URL answered with, a 304 only marks it seen, and the stored validators are what the next fetch
sends; a fingerprint more than three bits from the stored one is a change, and replaces it."""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import AttemptRecord, FetchResult, Validators
from crawlerai.db.models import Project, Site, SiteId, UrlState
from crawlerai.recurring.conditional import Unchanged
from crawlerai.recurring.simhash import ContentFingerprint
from crawlerai.recurring.state import record_content, record_fetch, stored_validators

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/item/1"
ETAG = '"v1"'
LAST_MODIFIED = "Tue, 13 Oct 2026 08:00:00 GMT"
VALIDATORS = (("ETag", ETAG), ("Last-Modified", LAST_MODIFIED))
DAY = timedelta(days=1)
UNCHANGED = Unchanged(
    attempts=(AttemptRecord(method="http", status=304, block_class="ok", duration_ms=1),), duration_ms=1
)


async def _site(conn: AsyncConnection) -> SiteId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))
    ).scalar_one()
    return site_id


async def _row(conn: AsyncConnection, site_id: SiteId) -> tuple[str | None, str | None, datetime] | None:
    query = select(UrlState.etag, UrlState.last_modified, UrlState.last_seen_at).where(
        UrlState.site_id == site_id, UrlState.canonical_url == URL
    )
    row = (await conn.execute(query)).first()
    return None if row is None else (row.etag, row.last_modified, row.last_seen_at)


async def test_a_200_stores_the_validators_it_answered_with(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"<html></html>", VALIDATORS))

    assert await stored_validators(conn, site_id, URL) == Validators(etag=ETAG, last_modified=LAST_MODIFIED)
    row = await _row(conn, site_id)
    assert row is not None
    assert row[2] == (await conn.execute(select(func.now()))).scalar_one()


async def test_a_304_marks_the_url_seen_and_keeps_its_validators(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"", VALIDATORS))
    await conn.execute(update(UrlState).where(UrlState.site_id == site_id).values(last_seen_at=func.now() - DAY))
    await record_fetch(conn, site_id, URL, UNCHANGED)

    now = (await conn.execute(select(func.now()))).scalar_one()
    assert await _row(conn, site_id) == (ETAG, LAST_MODIFIED, now)


# The content fingerprint (§4.3).

FINGERPRINT = ContentFingerprint("00" * 16, 0x0123_4567_89AB_CDEF)


async def _content(conn: AsyncConnection, site_id: SiteId) -> tuple[str | None, str | None, datetime | None]:
    query = select(UrlState.content_digest, UrlState.content_fingerprint, UrlState.last_changed_at).where(
        UrlState.site_id == site_id
    )
    row = (await conn.execute(query)).one()
    return (row.content_digest, row.content_fingerprint, row.last_changed_at)


async def _a_day_ago(conn: AsyncConnection, site_id: SiteId) -> datetime | None:
    """Move the URL's last change a day back, so a later change is seen to set it again."""
    moved = update(UrlState).where(UrlState.site_id == site_id).values(last_changed_at=func.now() - DAY)
    return (await conn.execute(moved.returning(UrlState.last_changed_at))).scalar_one()


async def test_an_equal_fingerprint_is_unchanged(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    await record_content(conn, site_id, URL, FINGERPRINT)
    changed_at = await _a_day_ago(conn, site_id)

    assert await record_content(conn, site_id, URL, FINGERPRINT) is False

    assert await _content(conn, site_id) == ("00" * 16, "0123456789abcdef", changed_at)
