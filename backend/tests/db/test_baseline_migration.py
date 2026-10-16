"""The baseline migration against Postgres: its CHECK constraint names are `ck_<table>_<name>`, prefixed once, and it
downgrades to an empty schema and upgrades again (the CI step upgrade, downgrade, upgrade).

Alembic's `compare_metadata` does not compare CHECK constraints, so these tests read the names from `pg_constraint`.
"""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.db.models import Base

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

CHECKS = text(
    "SELECT conrelid::regclass::text AS table_name, conname FROM pg_constraint"
    " WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
)


async def _checks(conn: AsyncConnection, *tables: str) -> set[str]:
    rows = (await conn.execute(CHECKS)).all()
    return {str(row.conname) for row in rows if not tables or row.table_name in tables}


@pytest.mark.anyio
async def test_every_check_in_the_database_has_the_name_the_models_give_it(conn: AsyncConnection) -> None:
    modelled = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert await _checks(conn) == modelled


TABLES = text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'")


async def _state(database_url: str) -> tuple[set[str], int, list[str]]:
    """The tables, CHECK constraints and project names of the database."""
    engine = create_async_engine(database_url)
    async with engine.connect() as conn:
        tables = {str(row[0]) for row in (await conn.execute(TABLES)).all()}
        checks = len(await _checks(conn))
        projects: list[str] = []
        if tables:
            projects = [str(row[0]) for row in (await conn.execute(text("SELECT name FROM project"))).all()]
    await engine.dispose()
    return tables, checks, projects


def _migrate(database_url: str, direction: str, revision: str) -> None:
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = database_url
    getattr(command, direction)(config, revision)


# Sync: Alembic's env runs its own event loop. Downgrading drops what other tests stored; they delete what they store
# anyway, and find the default project by name.
def test_the_baseline_downgrades_to_an_empty_schema_and_upgrades_again(database_url: str) -> None:
    try:
        upgraded = asyncio.run(_state(database_url))
        _migrate(database_url, "downgrade", "base")
        downgraded = asyncio.run(_state(database_url))
    finally:
        _migrate(database_url, "upgrade", "head")

    assert upgraded[0] == set(Base.metadata.tables)
    assert upgraded[2] == ["default"]
    assert downgraded == (set(), 0, [])
    assert asyncio.run(_state(database_url)) == upgraded
