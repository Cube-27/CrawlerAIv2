"""Alembic environment: runs migrations online over the async engine, against `CRAWLERAI_DATABASE_URL`."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.settings import Settings

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# SPEC-01 sets this to the models' metadata when the first table lands.
target_metadata = None


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(Settings().database_url.get_secret_value(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported.")
asyncio.run(_run_online())
