"""Alembic environment: runs migrations online over the async engine, against `CRAWLERAI_DATABASE_URL` unless the
caller's Config names another database (`attributes["database_url"]`)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from crawlerai.core.settings import DatabaseSettings
from crawlerai.db.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    # A caller may name the database on the Config (the DB tests do); otherwise it is the app's.
    url = context.config.attributes.get("database_url") or DatabaseSettings().database_url.get_secret_value()
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported.")
asyncio.run(_run_online())
