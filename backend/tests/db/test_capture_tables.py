from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from snowcrawl.db.models import (
    Candidate,
    Extraction,
    ExtractionConfig,
    ExtractionId,
    Job,
    JobId,
    Project,
    SchemaDef,
    SchemaId,
    Site,
    SiteId,
    UrlTask,
    UrlTaskId,
)
from snowcrawl.services.page_store import storable

pytestmark = pytest.mark.anyio


async def _site(conn: AsyncConnection, host: str = "example.test") -> SiteId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    site_id: SiteId = (
        await conn.execute(insert(Site).values(project_id=default_project, host=host).returning(Site.id))
    ).scalar_one()
    return site_id


async def _schema(conn: AsyncConnection) -> SchemaId:
    values = {"name": "s", "page_kind": "detail", "fields": {}, "origin": "user"}
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


def _config_values(site_id: SiteId, schema_id: SchemaId, /, **columns: Any) -> dict[str, Any]:
    values = {
        "site_id": site_id,
        "schema_id": schema_id,
        "page_kind": "detail",
        "version": 1,
        "ir": {},
        "origin": "induced",
    }
    return {**values, **columns}


async def test_a_raw_value_with_nul_or_a_lone_surrogate_is_stored_once_made_storable(conn: AsyncConnection) -> None:
    extraction_id = await _extraction(conn)
    raw: JsonValue = {"name\x00": ["a\x00b", "c\ud800"], "n": 3}

    await conn.execute(insert(Candidate), [_candidate_values(extraction_id, raw_value=storable(raw))])

    stored: JsonValue = (await conn.execute(select(Candidate.raw_value))).scalar_one()
    assert stored == {"name\ufffd": ["a\ufffdb", "c\ufffd"], "n": 3}


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
