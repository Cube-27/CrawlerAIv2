import uuid
from typing import Any, get_args

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Insert, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import (
    ApiKey,
    Base,
    FetchMethod,
    PageKind,
    Project,
    ProjectId,
    SchemaDef,
    SchemaOrigin,
    SchemaStatus,
    Site,
)

pytestmark = pytest.mark.anyio


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    diff: list[Any] = compare_metadata(context, Base.metadata)
    return diff


async def _default_project_id(conn: AsyncConnection) -> ProjectId:
    project_id: ProjectId = (await conn.execute(select(Project.id).where(Project.name == "default"))).scalar_one()
    return project_id


def _site(project_id: ProjectId, host: str, **columns: Any) -> Insert:
    return insert(Site).values(project_id=project_id, host=host, **columns)


def _schema(**columns: Any) -> Insert:
    values = {"name": "s", "version": 1, "page_kind": "detail", "fields": {}, "origin": "user", "status": "active"}
    return insert(SchemaDef).values(**{**values, **columns})


async def test_migrated_database_matches_the_models(conn: AsyncConnection) -> None:
    assert await conn.run_sync(_diff) == []


async def test_migration_creates_exactly_one_default_project(conn: AsyncConnection) -> None:
    names = (await conn.execute(select(Project.name))).scalars().all()

    assert names == ["default"]


async def test_new_rows_get_uuid7_ids_and_utc_creation_times(conn: AsyncConnection) -> None:
    project_id = await _default_project_id(conn)

    row = (await conn.execute(_site(project_id, "example.test").returning(Site.id, Site.created_at))).one()

    assert row.id.version == 7
    assert row.created_at.utcoffset().total_seconds() == 0


async def test_site_defaults_to_http_fetch_method_with_no_overrides(conn: AsyncConnection) -> None:
    project_id = await _default_project_id(conn)
    await conn.execute(_site(project_id, "example.test"))

    site = (await conn.execute(select(Site).where(Site.host == "example.test"))).one()

    assert (site.fetch_method, site.platform, site.proxy_pool, site.robots_snapshot, site.crawl_delay_ms) == (
        "http",
        None,
        None,
        None,
        None,
    )


async def test_site_host_is_unique(conn: AsyncConnection) -> None:
    project_id = await _default_project_id(conn)
    await conn.execute(_site(project_id, "example.test"))

    with pytest.raises(IntegrityError, match="uq_site_host"):
        await conn.execute(_site(project_id, "example.test"))


async def test_hosts_differing_only_by_a_www_label_are_two_sites(conn: AsyncConnection) -> None:
    project_id = await _default_project_id(conn)
    await conn.execute(_site(project_id, "example.test"))
    await conn.execute(_site(project_id, "www.example.test"))

    count = (await conn.execute(select(func.count()).select_from(Site))).scalar_one()

    assert count == 2


async def test_site_host_must_be_lowercase(conn: AsyncConnection) -> None:
    project_id = await _default_project_id(conn)

    with pytest.raises(IntegrityError, match="ck_site_host_lowercase"):
        await conn.execute(_site(project_id, "Example.test"))


async def test_site_requires_an_existing_project(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="fk_site_project_id_project"):
        await conn.execute(_site(ProjectId(uuid.UUID("00000000-0000-7000-8000-000000000000")), "example.test"))


@pytest.mark.parametrize("fetch_method", get_args(FetchMethod))
async def test_site_accepts_every_fetch_method(conn: AsyncConnection, fetch_method: str) -> None:
    project_id = await _default_project_id(conn)
    await conn.execute(_site(project_id, "example.test", fetch_method=fetch_method))

    stored = (await conn.execute(select(Site.fetch_method))).scalar_one()

    assert stored == fetch_method


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"fetch_method": "ftp"}, "ck_site_fetch_method"),
        ({"crawl_delay_ms": -1}, "ck_site_crawl_delay_ms_non_negative"),
    ],
)
async def test_site_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    project_id = await _default_project_id(conn)

    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(_site(project_id, "example.test", **columns))


async def test_schema_def_name_and_version_are_unique(conn: AsyncConnection) -> None:
    await conn.execute(_schema(name="commerce_detail", version=1))
    await conn.execute(_schema(name="commerce_detail", version=2))

    with pytest.raises(IntegrityError, match="uq_schema_def_name_version"):
        await conn.execute(_schema(name="commerce_detail", version=1))


async def test_schema_def_required_groups_default_to_empty(conn: AsyncConnection) -> None:
    await conn.execute(_schema(name="job_detail"))

    groups = (await conn.execute(select(SchemaDef.required_groups).where(SchemaDef.name == "job_detail"))).scalar_one()

    assert groups == []


@pytest.mark.parametrize(
    "columns",
    [{"page_kind": value} for value in get_args(PageKind)]
    + [{"origin": value} for value in get_args(SchemaOrigin)]
    + [{"status": value} for value in get_args(SchemaStatus)],
)
async def test_schema_def_accepts_every_enumeration_member(conn: AsyncConnection, columns: dict[str, Any]) -> None:
    await conn.execute(_schema(**columns))

    column = next(iter(columns))
    stored: str = (await conn.execute(select(SchemaDef.__table__.c[column]))).scalar_one()

    assert stored == columns[column]


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"page_kind": "index"}, "ck_schema_def_page_kind"),
        ({"origin": "llm"}, "ck_schema_def_origin"),
        ({"status": "draft"}, "ck_schema_def_status"),
        ({"version": 0}, "ck_schema_def_version_positive"),
    ],
)
async def test_schema_def_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(_schema(**columns))


async def test_api_key_hash_is_unique_and_starts_unrevoked(conn: AsyncConnection) -> None:
    key = {"hashed_key": "a" * 64, "label": "ci", "webhook_secret": "s"}
    row = (await conn.execute(insert(ApiKey).values(**key).returning(ApiKey.last_used_at, ApiKey.revoked_at))).one()

    assert (row.last_used_at, row.revoked_at) == (None, None)
    with pytest.raises(IntegrityError, match="uq_api_key_hashed_key"):
        await conn.execute(insert(ApiKey).values(**key))
