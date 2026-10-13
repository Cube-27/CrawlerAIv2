"""Retention (SPEC-01 §2, §4.3, §4.4; ARCHITECTURE §6): production captures go once past `expires_at`, bundle and row;
candidates go after 30 days; dev eval captures under `eval/` stay."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Candidate, Capture, CaptureId, Extraction, ExtractionId, Job, Project, Site, UrlTask
from crawlerai.scheduler.retention import expire_candidates, expire_captures
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

FETCHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
URL = "https://example.test/p/1"
DEFAULT_PROJECT = select(Project.id).where(Project.name == "default").scalar_subquery()


async def _capture(conn: AsyncConnection, store: FsStore, key: str, expires_at: Any) -> CaptureId:
    """A capture row and the object it names. `expires_at` is a SQL expression or None."""
    site_id = (
        await conn.execute(
            insert(Site).values(project_id=DEFAULT_PROJECT, host=f"{uuid.uuid4()}.example.test").returning(Site.id)
        )
    ).scalar_one()
    values = {
        "site_id": site_id,
        "url": URL,
        "fetched_at": FETCHED_AT,
        "method": "http",
        "status_code": 200,
        "final_url": URL,
        "block_class": "ok",
        "object_key": key,
        "html_sha256": "0" * 64,
        "size_bytes": 4,
        "duration_ms": 5,
        "expires_at": expires_at,
    }
    store.put(key, b"blob")
    capture_id: CaptureId = (await conn.execute(insert(Capture).values(**values).returning(Capture.id))).scalar_one()
    return capture_id


async def _extraction(conn: AsyncConnection) -> ExtractionId:
    job_id = (
        await conn.execute(
            insert(Job)
            .values(project_id=DEFAULT_PROJECT, kind="scrape", request={}, engine_version="0+cal.0")
            .returning(Job.id)
        )
    ).scalar_one()
    task_id = (
        await conn.execute(insert(UrlTask).values(job_id=job_id, url=URL, canonical_url=URL).returning(UrlTask.id))
    ).scalar_one()
    extraction_id: ExtractionId = (
        await conn.execute(
            insert(Extraction)
            .values(url_task_id=task_id, engine_version="0+cal.0", mode="adhoc")
            .returning(Extraction.id)
        )
    ).scalar_one()
    return extraction_id


async def test_production_captures_past_expires_at_lose_bundle_and_row_and_the_rest_stay(
    conn: AsyncConnection, tmp_path: Path
) -> None:
    store = FsStore(tmp_path)
    past, future = func.now() - timedelta(seconds=1), func.now() + timedelta(days=1)
    expired = await _capture(conn, store, "captures/2026/09/expired.bundle.zst", past)
    due_now = await _capture(conn, store, "captures/2026/09/due-now.bundle.zst", func.now())
    live = await _capture(conn, store, "captures/2026/09/live.bundle.zst", future)
    forever = await _capture(conn, store, "captures/2026/09/forever.bundle.zst", None)
    dev_eval = await _capture(conn, store, "eval/dev/never-expires.bundle.zst", None)
    store.put("eval/dev/no-row.bundle.zst", b"blob")

    assert await expire_captures(conn, store) == 1

    ids = [expired, due_now, live, forever, dev_eval]
    remaining = set((await conn.execute(select(Capture.id).where(Capture.id.in_(ids)))).scalars())
    assert remaining == {due_now, live, forever, dev_eval}
    assert store.list("") == [
        "captures/2026/09/due-now.bundle.zst",
        "captures/2026/09/forever.bundle.zst",
        "captures/2026/09/live.bundle.zst",
        "eval/dev/never-expires.bundle.zst",
        "eval/dev/no-row.bundle.zst",
    ]


async def test_a_row_under_an_eval_prefix_is_kept_with_its_bundle_even_past_expires_at(
    conn: AsyncConnection, tmp_path: Path
) -> None:
    store = FsStore(tmp_path)
    dev_eval = await _capture(conn, store, "eval/dev/mislabelled.bundle.zst", func.now() - timedelta(days=1))

    assert await expire_captures(conn, store) == 0

    assert (await conn.execute(select(Capture.id).where(Capture.id == dev_eval))).scalar_one() == dev_eval
    assert store.list("") == ["eval/dev/mislabelled.bundle.zst"]


async def test_expiring_captures_is_idempotent_when_the_bundle_is_already_gone(
    conn: AsyncConnection, tmp_path: Path
) -> None:
    store = FsStore(tmp_path)
    key = "captures/2026/09/gone.bundle.zst"
    capture_id = await _capture(conn, store, key, func.now() - timedelta(seconds=1))
    store.delete(key)

    assert await expire_captures(conn, store) == 1
    assert await expire_captures(conn, store) == 0

    assert (await conn.execute(select(Capture.id).where(Capture.id == capture_id))).scalar_one_or_none() is None


async def test_candidates_older_than_30_days_are_deleted_and_younger_ones_kept(conn: AsyncConnection) -> None:
    extraction_id = await _extraction(conn)
    values = {
        "extraction_id": extraction_id,
        "entity_ref": "page",
        "field": "title",
        "raw_value": "A title",
        "normalize_status": "ok",
        "source_kind": "jsonld",
        "independent": True,
        "locator": "jsonld:0:$.name",
    }
    ages = {"old": timedelta(days=30, seconds=1), "young": timedelta(days=29, hours=23), "new": timedelta(0)}
    ids = {
        name: (
            await conn.execute(insert(Candidate).values(**values, created_at=func.now() - age).returning(Candidate.id))
        ).scalar_one()
        for name, age in ages.items()
    }

    assert await expire_candidates(conn) == 1

    query = select(Candidate.id).where(Candidate.extraction_id == extraction_id)
    remaining = set((await conn.execute(query)).scalars())
    assert remaining == {ids["young"], ids["new"]}
    assert await expire_candidates(conn) == 0
