import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import (
    Candidate,
    Capture,
    CaptureId,
    ConfigOrigin,
    Extraction,
    ExtractionConfig,
    ExtractionId,
    Job,
    JobId,
    NormalizeStatus,
    ProgressiveMode,
    ProgressiveState,
    Project,
    SchemaDef,
    SchemaId,
    Site,
    SiteId,
    SourceKind,
    UrlTask,
    UrlTaskId,
)

pytestmark = pytest.mark.anyio

FETCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)
SHA256 = "0" * 64


async def _site(conn: AsyncConnection, host: str = "example.test") -> SiteId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=default_project, host=host).returning(Site.id))
    ).scalar_one()
    return site_id


async def _schema(conn: AsyncConnection, version: int = 1) -> SchemaId:
    values = {"name": "s", "version": version, "page_kind": "detail", "fields": {}, "origin": "user"}
    schema_id: SchemaId = (
        await conn.execute(insert(SchemaDef).values(**values, status="active").returning(SchemaDef.id))
    ).scalar_one()
    return schema_id


async def _task(conn: AsyncConnection) -> UrlTaskId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    job_id: JobId = (
        await conn.execute(
            insert(Job)
            .values(project_id=default_project, kind="scrape", request={}, engine_version="0+cal.0")
            .returning(Job.id)
        )
    ).scalar_one()
    url = "https://example.test/p/1"
    task_id: UrlTaskId = (
        await conn.execute(insert(UrlTask).values(job_id=job_id, url=url, canonical_url=url).returning(UrlTask.id))
    ).scalar_one()
    return task_id


async def _capture(conn: AsyncConnection, site_id: SiteId, /, **columns: Any) -> CaptureId:
    url = "https://example.test/p/1"
    values = {
        "site_id": site_id,
        "url": url,
        "fetched_at": FETCHED_AT,
        "method": "http",
        "status_code": 200,
        "final_url": url,
        "block_class": "ok",
        "object_key": f"captures/2026/10/{uuid.uuid4()}.bundle.zst",
        "html_sha256": SHA256,
        "size_bytes": 10,
        "duration_ms": 5,
    }
    capture_id: CaptureId = (
        await conn.execute(insert(Capture).values(**{**values, **columns}).returning(Capture.id))
    ).scalar_one()
    return capture_id


async def _extraction(conn: AsyncConnection, **columns: Any) -> ExtractionId:
    values = {"url_task_id": await _task(conn), "engine_version": "0+cal.0", "mode": "adhoc", **columns}
    extraction_id: ExtractionId = (
        await conn.execute(insert(Extraction).values(**values).returning(Extraction.id))
    ).scalar_one()
    return extraction_id


def _candidate_values(extraction_id: ExtractionId, /, **columns: Any) -> dict[str, Any]:
    values = {
        "extraction_id": extraction_id,
        "entity_ref": "page",
        "field": "title",
        "raw_value": "A title",
        "normalized_value": "A title",
        "normalize_status": "ok",
        "source_kind": "jsonld",
        "independent": True,
        "locator": "jsonld:0:$.name",
    }
    return {**values, **columns}


def _progressive_values(site_id: SiteId, schema_id: SchemaId, /, **columns: Any) -> dict[str, Any]:
    return {"site_id": site_id, "schema_id": schema_id, "schema_version": 1, "page_kind": "detail", **columns}


def _config_values(site_id: SiteId, schema_id: SchemaId, /, **columns: Any) -> dict[str, Any]:
    values = {
        "site_id": site_id,
        "schema_id": schema_id,
        "schema_version": 1,
        "page_kind": "detail",
        "version": 1,
        "ir": {},
        "origin": "induced",
    }
    return {**values, **columns}


async def test_capture_accepts_every_method_and_block_class(conn: AsyncConnection) -> None:
    site_id = await _site(conn)
    for method in get_args(CaptureMethod):
        await _capture(conn, site_id, method=method)
    for block_class in get_args(BlockClass):
        await _capture(conn, site_id, block_class=block_class)

    rows = (await conn.execute(select(Capture.method, Capture.block_class))).all()

    assert {row.method for row in rows} == set(get_args(CaptureMethod))
    assert {row.block_class for row in rows} == set(get_args(BlockClass))


async def test_deleting_an_expired_capture_keeps_its_task_and_extraction(conn: AsyncConnection) -> None:
    capture_id = await _capture(conn, await _site(conn))
    extraction_id = await _extraction(conn, capture_id=capture_id)
    await conn.execute(update(UrlTask).values(capture_id=capture_id))

    await conn.execute(delete(Capture).where(Capture.id == capture_id))

    assert (await conn.execute(select(UrlTask.capture_id))).scalar_one() is None
    assert (await conn.execute(select(Extraction.id, Extraction.capture_id))).one() == (extraction_id, None)


async def test_candidate_accepts_every_source_kind_and_normalize_status(conn: AsyncConnection) -> None:
    extraction_id = await _extraction(conn)
    rows = [_candidate_values(extraction_id, source_kind=kind) for kind in get_args(SourceKind)]
    rows += [_candidate_values(extraction_id, normalize_status=status) for status in get_args(NormalizeStatus)]

    await conn.execute(insert(Candidate), rows)

    stored = (await conn.execute(select(Candidate.source_kind, Candidate.normalize_status))).all()
    assert {row.source_kind for row in stored} == set(get_args(SourceKind))
    assert {row.normalize_status for row in stored} == set(get_args(NormalizeStatus))


@pytest.mark.parametrize("mode", get_args(ProgressiveMode))
async def test_progressive_state_accepts_every_mode(conn: AsyncConnection, mode: str) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    config = insert(ExtractionConfig).values(**_config_values(site_id, schema_id)).returning(ExtractionConfig.id)
    # A learning state has a run in flight and an active one its config (SPEC-08 §4.4, §4.8).
    plumbing = {"learning_started_at": FETCHED_AT, "active_config_id": (await conn.execute(config)).scalar_one()}
    values = _progressive_values(site_id, schema_id, mode=mode, **plumbing)

    await conn.execute(insert(ProgressiveState).values(**values))

    assert (await conn.execute(select(ProgressiveState.mode))).scalar_one() == mode


async def test_config_accepts_every_origin(conn: AsyncConnection) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    origins = get_args(ConfigOrigin)
    rows = [_config_values(site_id, schema_id, origin=origin, version=n) for n, origin in enumerate(origins, 1)]

    await conn.execute(insert(ExtractionConfig), rows)

    assert set((await conn.execute(select(ExtractionConfig.origin))).scalars()) == set(origins)


async def test_a_site_has_one_active_config_per_schema_and_page_kind(conn: AsyncConnection) -> None:
    site_id, schema_id = await _site(conn), await _schema(conn)
    await conn.execute(insert(ExtractionConfig).values(**_config_values(site_id, schema_id, status="active")))
    await conn.execute(insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=2)))
    await conn.execute(
        insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=3, status="suspended"))
    )
    await conn.execute(
        insert(ExtractionConfig).values(**_config_values(site_id, schema_id, page_kind="listing", status="active"))
    )

    statement = insert(ExtractionConfig).values(**_config_values(site_id, schema_id, version=4, status="active"))
    with pytest.raises(IntegrityError, match="uq_extraction_config_active"):
        await conn.execute(statement)
