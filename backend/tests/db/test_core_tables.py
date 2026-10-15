from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Insert, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Base, Job, JobId, Project, SchemaDef, Site, UrlTask

pytestmark = pytest.mark.anyio


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    diff: list[Any] = compare_metadata(context, Base.metadata)
    return diff


def _site(host: str, **columns: Any) -> Insert:
    """An insert of a site in the `default` project, unless `project_id` is given."""
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    return insert(Site).values(**{"project_id": default_project, "host": host, **columns})


async def _job_id(conn: AsyncConnection) -> JobId:
    """A job in the `default` project."""
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "scrape", "request": {}, "engine_version": "0+cal.0"}
    job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    return job_id


def _task(job_id: JobId, url: str) -> Insert:
    return insert(UrlTask).values(job_id=job_id, url=url, canonical_url="https://example.test/p/1")


def _schema(**columns: Any) -> Insert:
    values = {"name": "s", "version": 1, "page_kind": "detail", "fields": {}, "origin": "user", "status": "active"}
    return insert(SchemaDef).values(**{**values, **columns})


async def test_migrated_database_matches_the_models(conn: AsyncConnection) -> None:
    assert await conn.run_sync(_diff) == []


async def test_migration_creates_exactly_one_default_project(conn: AsyncConnection) -> None:
    names = (await conn.execute(select(Project.name))).scalars().all()

    assert names == ["default"]


async def test_new_rows_get_uuid7_ids_and_utc_creation_times(conn: AsyncConnection) -> None:
    row = (await conn.execute(_site("example.test").returning(Site.id, Site.created_at))).one()

    assert row.id.version == 7
    assert row.created_at.utcoffset().total_seconds() == 0


async def test_site_host_is_unique(conn: AsyncConnection) -> None:
    await conn.execute(_site("example.test"))

    duplicate = _site("example.test")
    with pytest.raises(IntegrityError, match="uq_site_host"):
        await conn.execute(duplicate)


async def test_site_host_must_be_lowercase(conn: AsyncConnection) -> None:
    statement = _site("Example.test")
    with pytest.raises(IntegrityError, match="ck_site_host_lowercase"):
        await conn.execute(statement)


async def test_schema_def_name_and_version_are_unique(conn: AsyncConnection) -> None:
    await conn.execute(_schema(name="commerce_detail", version=1))
    await conn.execute(_schema(name="commerce_detail", version=2))

    duplicate = _schema(name="commerce_detail", version=1)
    with pytest.raises(IntegrityError, match="uq_schema_def_name_version"):
        await conn.execute(duplicate)


async def test_a_job_holds_each_canonical_url_once_and_another_job_may_hold_it_too(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)
    await conn.execute(_task(job_id, "https://example.test/p/1?ref=a"))
    await conn.execute(_task(await _job_id(conn), "https://example.test/p/1?ref=a"))

    duplicate = _task(job_id, "https://example.test/p/1?ref=b")
    with pytest.raises(IntegrityError, match="uq_url_task_job_id_canonical_url"):
        await conn.execute(duplicate)
