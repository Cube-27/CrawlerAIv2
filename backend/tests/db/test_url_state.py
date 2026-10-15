"""`url_state` for conditional GET (SPEC-11 §4.2) and the content fingerprint (§4.3), against a real Postgres: a 200
stores the validators a URL answered with, a 304 only marks it seen, and the stored validators are what the next fetch
sends; a fingerprint more than three bits from the stored one is a change, and replaces it."""

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.types import AttemptRecord, FetchResult, Validators
from crawlerai.core.capture import CaptureMethod
from crawlerai.db.models import Project, Site, SiteId, UrlState
from crawlerai.recurring.conditional import Unchanged
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


async def test_a_later_200_replaces_the_validators_and_drops_the_ones_it_lacks(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"", VALIDATORS))
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"", (("ETag", '"v2"'),)))

    assert await stored_validators(conn, site_id, URL) == Validators(etag='"v2"', last_modified=None)


async def test_a_200_without_validators_stores_none_to_send(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b""))

    assert await stored_validators(conn, site_id, URL) is None
    now = (await conn.execute(select(func.now()))).scalar_one()
    assert await _row(conn, site_id) == (None, None, now)  # the URL is still recorded as seen


@pytest.mark.parametrize(("status", "method"), [(404, "http"), (200, "browser")])
async def test_only_an_http_200_stores_validators(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult], status: int, method: CaptureMethod
) -> None:
    # The HTTP rung is the only one that sends them (§4.2), and an API response describes its endpoint, not the page.
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, status, b"", VALIDATORS, method=method))

    assert await _row(conn, site_id) is None


async def test_a_200_that_failed_or_was_not_ok_stores_nothing(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    # A body cut short (an error after the status line) or a shell was never extracted whole: a later 304 must not
    # stand for it.
    site_id = await _site(conn)
    await record_fetch(
        conn, site_id, URL, fetch_result(URL, 200, b"", VALIDATORS, block_class="error", error="body_cap")
    )
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"", VALIDATORS, block_class="shell"))

    assert await _row(conn, site_id) is None


async def test_a_redirected_200_stores_nothing(conn: AsyncConnection, fetch_result: Callable[..., FetchResult]) -> None:
    # Its validators describe the resource redirected to, not the URL asked for.
    site_id = await _site(conn)
    moved = fetch_result(URL, 200, b"", VALIDATORS)
    manifest = moved.bundle.manifest.model_copy(update={"final_url": f"{URL}/moved"})
    await record_fetch(
        conn, site_id, URL, moved.model_copy(update={"bundle": moved.bundle.model_copy(update={"manifest": manifest})})
    )

    assert await _row(conn, site_id) is None


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

FINGERPRINT = 0x0123_4567_89AB_CDEF


async def _content(conn: AsyncConnection, site_id: SiteId) -> tuple[str | None, datetime | None]:
    query = select(UrlState.content_fingerprint, UrlState.last_changed_at).where(UrlState.site_id == site_id)
    row = (await conn.execute(query)).one()
    return (row.content_fingerprint, row.last_changed_at)


async def _a_day_ago(conn: AsyncConnection, site_id: SiteId) -> datetime | None:
    """Move the URL's last change a day back, so a later change is seen to set it again."""
    moved = update(UrlState).where(UrlState.site_id == site_id).values(last_changed_at=func.now() - DAY)
    return (await conn.execute(moved.returning(UrlState.last_changed_at))).scalar_one()


async def test_a_first_fingerprint_is_a_change(conn: AsyncConnection) -> None:
    site_id = await _site(conn)

    assert await record_content(conn, site_id, URL, FINGERPRINT) is True

    now = (await conn.execute(select(func.now()))).scalar_one()
    assert await _content(conn, site_id) == ("0123456789abcdef", now)


async def test_a_fingerprint_within_three_bits_is_unchanged_and_keeps_the_stored_one(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    await record_content(conn, site_id, URL, FINGERPRINT)
    changed_at = await _a_day_ago(conn, site_id)

    assert await record_content(conn, site_id, URL, FINGERPRINT ^ 0b111) is False

    assert await _content(conn, site_id) == ("0123456789abcdef", changed_at)


async def test_a_fingerprint_four_bits_away_is_a_change(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    await record_content(conn, site_id, URL, FINGERPRINT)
    await _a_day_ago(conn, site_id)

    assert await record_content(conn, site_id, URL, FINGERPRINT ^ 0b1111 << 60) is True

    now = (await conn.execute(select(func.now()))).scalar_one()
    assert await _content(conn, site_id) == ("f123456789abcdef", now)


async def test_small_changes_do_not_add_up_unseen(conn: AsyncConnection) -> None:
    # Each step is 2 bits from the last, but the stored fingerprint stays the first: the second step is 4 from it.
    site_id = await _site(conn)
    await record_content(conn, site_id, URL, FINGERPRINT)

    assert await record_content(conn, site_id, URL, FINGERPRINT ^ 0b11) is False
    assert await record_content(conn, site_id, URL, FINGERPRINT ^ 0b1111) is True


async def test_a_fingerprint_keeps_the_validators(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    await record_fetch(conn, site_id, URL, fetch_result(URL, 200, b"", VALIDATORS))

    await record_content(conn, site_id, URL, FINGERPRINT)

    assert await stored_validators(conn, site_id, URL) == Validators(etag=ETAG, last_modified=LAST_MODIFIED)
