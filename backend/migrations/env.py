"""Alembic environment: runs migrations online over the async engine.

Two databases share it. The default section migrates the main database (`CRAWLERAI_DATABASE_URL`); the `private`
section (`alembic -n private`) migrates the private eval database (`CRAWLERAI_EVAL_PRIVATE_DATABASE_URL`, SPEC-03
§4.2) from its own revisions. A caller may name another database on the Config (`attributes["database_url"]`), as
the DB tests do.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, MetaData, pool
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.settings import DatabaseSettings, EvalPrivateDatabaseSettings
from crawlerai.db.models import Base
from crawlerai.db.private_models import PrivateBase

if context.config.config_file_name is not None:
    # Migrations also run inside a process that logs (the test session): its loggers stay enabled.
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

PRIVATE = context.config.config_ini_section == "private"
target_metadata: MetaData = PrivateBase.metadata if PRIVATE else Base.metadata


def _url() -> str:
    url = context.config.attributes.get("database_url")
    if url:
        return str(url)
    if PRIVATE:
        return EvalPrivateDatabaseSettings().eval_private_database_url.get_secret_value()
    return DatabaseSettings().database_url.get_secret_value()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported.")
asyncio.run(_run_online())
