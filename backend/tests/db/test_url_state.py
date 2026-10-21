"""`url_state`'s content fingerprint (§4.3), against a real Postgres: an equal fingerprint is no change."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Project, Site, SiteId, UrlState
from crawlerai.recurring.simhash import ContentFingerprint
from crawlerai.recurring.state import record_content

pytestmark = pytest.mark.anyio

URL = "https://shop.example.test/item/1"
DAY = timedelta(days=1)


async def _site(conn: AsyncConnection) -> SiteId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))
    ).scalar_one()
    return site_id


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
