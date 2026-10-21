"""The block history (acquisition spec, "Acquisition contract and block history"): refused HTTP requests start a
browser-first window only when the browser then passed, and a browser the site refuses too ends one."""

from collections.abc import AsyncIterator, Callable

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.memory import learn_fetch, remembered
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.db.models import Project, Site, SiteId

pytestmark = pytest.mark.anyio

_HOST = "blocks.example.test"
_URL = f"https://{_HOST}/p"
_REFUSED = AttemptRecord(method="http", status=403, block_class="blocked", duration_ms=1)
# A job's own method teaches the contract nothing (`acquire.memory.lesson`): only the block history is under test.
_POLICY = FetchPolicy(method_hint="browser")


@pytest.fixture
async def site_id(engine: AsyncEngine) -> AsyncIterator[SiteId]:
    """A site of its own, deleted with its memory after the test: memory is learned in transactions of its own."""
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.host == _HOST))
        values = {"project_id": project, "host": _HOST}
        site: SiteId = (await conn.execute(insert(Site).values(values).returning(Site.id))).scalar_one()
    yield site
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.id == site))


async def _method(engine: AsyncEngine, site_id: SiteId) -> str:
    async with engine.connect() as conn:
        return (await remembered(conn, site_id, "detail")).method


async def test_refused_http_starts_the_browser_only_once_the_browser_passed(
    engine: AsyncEngine, site_id: SiteId, fetch_result: Callable[..., FetchResult]
) -> None:
    def refused_then(browser: BlockClass) -> FetchResult:
        status = 403 if browser == "blocked" else 200
        result = fetch_result(_URL, status, method="browser", block_class=browser, policy=_POLICY)
        return result.model_copy(update={"attempts": (_REFUSED, *result.attempts)})

    for _ in range(3):
        await learn_fetch(engine, site_id, refused_then("blocked"))
    assert await _method(engine, site_id) == "http"

    await learn_fetch(engine, site_id, refused_then("ok"))
    assert await _method(engine, site_id) == "browser"

    await learn_fetch(engine, site_id, fetch_result(_URL, 403, method="browser", block_class="blocked", policy=_POLICY))
    assert await _method(engine, site_id) == "http"
