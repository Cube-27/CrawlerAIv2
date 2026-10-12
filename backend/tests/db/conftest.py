"""Tests against a real Postgres. They need `CRAWLERAI_DATABASE_URL`; CI provides one, and locally `make db` does.

The database is migrated to head once per session. Each test runs in a transaction that is rolled back.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.core.settings import DatabaseSettings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        settings = DatabaseSettings()
    except ValidationError:
        pytest.skip("CRAWLERAI_DATABASE_URL is not set")
    command.upgrade(Config(ALEMBIC_INI), "head")
    return settings.database_url.get_secret_value()


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()
