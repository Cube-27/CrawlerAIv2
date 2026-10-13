"""CHECK constraint names in the migrated database: `ck_<table>_<name>`, prefixed once.

Migrations 0002-0004 passed full names that the naming convention prefixed again; 0006 renames them. Alembic's
`compare_metadata` does not compare CHECK constraints, so these tests read the names from `pg_constraint`.
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, text
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.db.models import Base

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

CHECKS = text(
    "SELECT conrelid::regclass::text, conname FROM pg_constraint"
    " WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
)


async def _checks(database_url: str, *tables: str) -> set[str]:
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        rows = (await conn.execute(CHECKS)).tuples().all()
    await engine.dispose()
    return {str(name) for table, name in rows if not tables or table in tables}


def _migrate(database_url: str, direction: str, revision: str) -> None:
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = database_url
    getattr(command, direction)(config, revision)


def test_checks_of_the_first_tables_are_prefixed_once(database_url: str) -> None:
    assert asyncio.run(_checks(database_url, "site", "schema_def", "job", "url_task")) == {
        "ck_site_host_lowercase",
        "ck_site_fetch_method",
        "ck_site_crawl_delay_ms_non_negative",
        "ck_schema_def_version_positive",
        "ck_schema_def_page_kind",
        "ck_schema_def_origin",
        "ck_schema_def_status",
        "ck_job_kind",
        "ck_job_status",
        "ck_url_task_page_kind",
        "ck_url_task_status",
        "ck_url_task_outcome",
        "ck_url_task_attempts_non_negative",
        "ck_url_task_depth_non_negative",
    }


def test_usage_event_checks_are_prefixed_once(database_url: str) -> None:
    assert asyncio.run(_checks(database_url, "usage_event")) == {
        "ck_usage_event_resource",
        "ck_usage_event_quantity_non_negative",
    }


def test_every_check_in_the_database_has_the_name_the_models_give_it(database_url: str) -> None:
    modelled = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert asyncio.run(_checks(database_url)) == modelled


def test_downgrading_0006_restores_the_names_0005_had(database_url: str) -> None:
    try:
        _migrate(database_url, "downgrade", "0005")
        downgraded = asyncio.run(_checks(database_url, "job"))
    finally:
        _migrate(database_url, "upgrade", "head")

    assert downgraded == {"ck_job_ck_job_kind", "ck_job_ck_job_status"}
    assert asyncio.run(_checks(database_url, "job")) == {"ck_job_kind", "ck_job_status"}
