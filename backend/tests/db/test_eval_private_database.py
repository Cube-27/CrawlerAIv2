"""The private eval database (SPEC-03 §4.2, C1, INV-01): `app` cannot reach the one `infra/postgres/init.sql`
provisions, and the private revisions build the shape the private models declare, in a throwaway database."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.db.private_models import PrivateBase

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
PRIVATE_DATABASE = "crawlerai_eval_private"  # infra/postgres/init.sql


@pytest.mark.anyio
async def test_the_app_role_cannot_connect_to_the_private_database(database_url: str) -> None:
    """The test database's credentials are `app`'s (as in CI and `make check`); only the database name changes."""
    url = make_url(database_url).set(database=PRIVATE_DATABASE)
    assert url.username == "app"
    engine = create_async_engine(url)

    with pytest.raises(DBAPIError, match=f'permission denied for database "{PRIVATE_DATABASE}"'):
        async with engine.connect():
            pass
    await engine.dispose()


def _diff(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    diff: list[Any] = compare_metadata(context, PrivateBase.metadata)
    return diff


async def _private_diff_and_tables(url: str) -> tuple[list[Any], set[str]]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)
        query = text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        names: list[str] = list((await conn.execute(query)).scalars())
    await engine.dispose()
    return diff, set(names)


def _private_config(url: str) -> Config:
    config = Config(ALEMBIC_INI, ini_section="private")
    config.attributes["database_url"] = url
    return config


# Sync: Alembic's env runs its own event loop.
def test_private_revisions_round_trip_to_the_private_models(private_database_url: str) -> None:
    try:
        command.downgrade(_private_config(private_database_url), "base")
        _, emptied = asyncio.run(_private_diff_and_tables(private_database_url))
    finally:
        command.upgrade(_private_config(private_database_url), "head")
    diff, tables = asyncio.run(_private_diff_and_tables(private_database_url))

    assert emptied == {"alembic_version"}
    assert diff == []
    assert tables == {"alembic_version", "eval_capture", "eval_page", "eval_run", "eval_llm_cache"}
