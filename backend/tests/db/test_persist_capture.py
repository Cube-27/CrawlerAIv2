"""`store_capture` (SPEC-02 §4.10): the bundle goes to the object store under the production key, and a `capture`
row describes it."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Capture, Project, Site, SiteId
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, capture_key, decode, sha256_hex
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

FETCHED_AT = datetime(2026, 10, 1, 12, 30, tzinfo=UTC)
BODY = b"<html><body><h1>Item</h1></body></html>"
ATTEMPTS = (
    AttemptRecord(method="http", status=200, block_class="shell", duration_ms=120),
    AttemptRecord(method="browser", status=200, block_class="ok", duration_ms=1830),
)


def _result() -> FetchResult:
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url="https://shop.example.test/p/1",
        final_url="https://shop.example.test/p/1?ref=a",
        fetched_at=FETCHED_AT,
        method="browser",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(("Accept", "text/html"),), response=(("Content-Type", "text/html"),)),
        timings_ms={"total": 1950},
        html_sha256=sha256_hex(BODY),
        network_bodies=(),
        fetch_policy=FetchPolicy(timeout_s=12.0).model_dump(mode="json"),
        engine_version="0+cal.0",
    )
    return FetchResult(
        bundle=CaptureBundle(manifest=manifest, body=BODY, network=()), duration_ms=1950, attempts=ATTEMPTS
    )


async def _site(conn: AsyncConnection) -> SiteId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=default_project, host="shop.example.test").returning(Site.id))
    ).scalar_one()
    return site_id


async def test_the_bundle_is_stored_under_the_production_key_and_a_row_describes_it(
    conn: AsyncConnection, tmp_path: Path
) -> None:
    store = FsStore(tmp_path)
    site_id = await _site(conn)
    result = _result()
    manifest = result.bundle.manifest

    capture_id = await store_capture(conn, store, result, site_id)

    key = capture_key(manifest.capture_id, FETCHED_AT)
    assert capture_id == manifest.capture_id
    assert store.list("") == [key]
    assert decode(store.get(key)) == result.bundle
    row = (await conn.execute(select(Capture.__table__).where(Capture.id == capture_id))).one()
    assert (row.site_id, row.url, row.final_url, row.fetched_at) == (
        site_id,
        "https://shop.example.test/p/1",
        "https://shop.example.test/p/1?ref=a",
        FETCHED_AT,
    )
    assert (row.method, row.status_code, row.block_class) == ("browser", 200, "ok")
    assert (row.object_key, row.html_sha256, row.size_bytes) == (key, sha256_hex(BODY), len(store.get(key)))
    assert row.duration_ms == 1950
    assert row.expires_at == datetime(2026, 10, 31, 12, 30, tzinfo=UTC)


async def test_the_row_keeps_the_policy_and_every_attempt(conn: AsyncConnection, tmp_path: Path) -> None:
    capture_id = await store_capture(conn, FsStore(tmp_path), _result(), await _site(conn))

    row = (await conn.execute(select(Capture.__table__).where(Capture.id == capture_id))).one()
    assert row.fetch_policy == {
        **FetchPolicy(timeout_s=12.0).model_dump(mode="json"),
        "attempts": [
            {
                "method": "http",
                "status": 200,
                "block_class": "shell",
                "duration_ms": 120,
                "error": None,
                "challenge": None,
                "steps": [],
            },
            {
                "method": "browser",
                "status": 200,
                "block_class": "ok",
                "duration_ms": 1830,
                "error": None,
                "challenge": None,
                "steps": [],
            },
        ],
    }


@pytest.mark.parametrize(
    ("expires_in", "expires_at"),
    [(None, None), (timedelta(days=1), datetime(2026, 10, 2, 12, 30, tzinfo=UTC))],
)
async def test_expiry_counts_from_the_fetch(
    conn: AsyncConnection, tmp_path: Path, expires_in: timedelta | None, expires_at: datetime | None
) -> None:
    capture_id = await store_capture(conn, FsStore(tmp_path), _result(), await _site(conn), expires_in=expires_in)

    row = (await conn.execute(select(Capture.__table__).where(Capture.id == capture_id))).one()
    assert row.expires_at == expires_at


async def test_no_row_is_written_when_the_object_store_fails(conn: AsyncConnection, tmp_path: Path) -> None:
    # A row never points at a bundle that isn't there.
    class FailingStore(FsStore):
        def put(self, key: str, data: bytes) -> None:
            raise OSError("disk full")

    site_id = await _site(conn)
    store, result = FailingStore(tmp_path), _result()
    with pytest.raises(OSError, match="disk full"):
        await store_capture(conn, store, result, site_id)

    assert (await conn.execute(select(Capture).where(Capture.site_id == site_id))).all() == []
