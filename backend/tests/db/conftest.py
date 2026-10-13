"""Tests against a real Postgres, in a database of their own: `CRAWLERAI_TEST_DATABASE_URL`. CI provides one, and
`make check` recreates one each run. Without it these tests are skipped.

The tests own that database: they delete every job and task in it, and the queue tests claim and run every due task
in it, not only their own, which is why they never use `CRAWLERAI_DATABASE_URL`. Never point it at data you want.

`CRAWLERAI_TEST_PRIVATE_DATABASE_URL` names a second throwaway database, migrated with the private eval revisions
(`alembic -n private`), for the private eval store's tests. It is never the private eval database itself (C1), and
without it those tests are skipped.

The database is migrated to head once per session. Each test runs in a transaction that is rolled back (`conn`),
or, when several connections must see each other's work, commits through `engine`, which deletes every job afterwards.
"""

import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Capture, Job, JobEvent, Site, UrlTask, UsageEvent
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, HeaderList, Headers, sha256_hex

TEST_DATABASE_URL = "CRAWLERAI_TEST_DATABASE_URL"
TEST_PRIVATE_DATABASE_URL = "CRAWLERAI_TEST_PRIVATE_DATABASE_URL"
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


@pytest.fixture(scope="session")
def private_database_url() -> str:
    url = os.environ.get(TEST_PRIVATE_DATABASE_URL)
    if not url:
        pytest.skip(f"{TEST_PRIVATE_DATABASE_URL} is not set")
    config = Config(ALEMBIC_INI, ini_section="private")
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


@pytest.fixture
async def own_origin(database_url: str) -> AsyncIterator[str]:
    """An https origin on a host no other test uses, for tests that commit a site for it. The site and its captures
    are deleted afterwards (a task that named a capture keeps a NULL, SPEC-01 §4.2)."""
    host = f"shop-{uuid7().hex[-12:]}.example.test"
    yield f"https://{host}"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        site_ids = select(Site.id).where(Site.host == host).scalar_subquery()
        await connection.execute(delete(Capture).where(Capture.site_id.in_(site_ids)))
        await connection.execute(delete(Site).where(Site.host == host))
    await engine.dispose()


@pytest.fixture
def fetch_result() -> Callable[..., FetchResult]:
    """A factory for the result of one fetch of `url` by one rung, as `fetch_http` reports it."""

    def make(
        url: str,
        status: int = 200,
        body: bytes = b"",
        headers: HeaderList = (),
        *,
        block_class: BlockClass = "ok",
        error: str | None = None,
        method: CaptureMethod = "http",
    ) -> FetchResult:
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            method=method,
            status_code=status,
            block_class=block_class,
            headers=Headers(request=(), response=headers),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(body),
            network_bodies=(),
            fetch_policy=FetchPolicy().model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(
            method=method, status=status or None, block_class=block_class, duration_ms=1, error=error
        )
        return FetchResult(
            bundle=CaptureBundle(manifest=manifest, body=body, network=()), duration_ms=1, attempts=(attempt,)
        )

    return make
