"""Tests against a real Postgres, in a database of their own: `CRAWLERAI_TEST_DATABASE_URL`. CI provides one, and
`make check` recreates one each run. Without it these tests are skipped.

The tests own that database: they delete every job and task in it, and the queue tests claim and run every due task
in it, not only their own, which is why they never use `CRAWLERAI_DATABASE_URL`. Never point it at data you want.

The database is migrated to head once per session. Each test runs in a transaction that is rolled back (`conn`),
or, when several connections must see each other's work, commits through `engine`, which deletes every job afterwards.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.db.models import Job, JobEvent, UrlTask, UsageEvent

TEST_DATABASE_URL = "CRAWLERAI_TEST_DATABASE_URL"
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(TEST_DATABASE_URL)
    if not url:
        pytest.skip(f"{TEST_DATABASE_URL} is not set")
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    async with engine.begin() as connection:
        for model in (UsageEvent, JobEvent, UrlTask, Job):
            await connection.execute(delete(model))
    await engine.dispose()
