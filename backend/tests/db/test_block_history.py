"""The block history (acquisition spec, "Acquisition contract and block history"): refused HTTP requests start a
browser-first window only when the browser then passed, and a browser the site refuses too ends one."""

from collections.abc import Callable

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.memory import learn_fetch, remembered
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.db.models import Project, Site, SiteId

pytestmark = pytest.mark.anyio

_URL = "https://blocks.example.test/p"
_REFUSED = AttemptRecord(method="http", status=403, block_class="blocked", duration_ms=1)
# A job's own method teaches the contract nothing (`acquire.memory.lesson`): only the block history is under test.
_POLICY = FetchPolicy(method_hint="browser")


async def _site(conn: AsyncConnection) -> SiteId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": project, "host": "blocks.example.test"}
    site_id: SiteId = (await conn.execute(insert(Site).values(values).returning(Site.id))).scalar_one()
    return site_id


async def test_refused_http_starts_the_browser_only_once_the_browser_passed(
    conn: AsyncConnection, fetch_result: Callable[..., FetchResult]
) -> None:
    def refused_then(browser: BlockClass) -> FetchResult:
        status = 403 if browser == "blocked" else 200
        result = fetch_result(_URL, status, method="browser", block_class=browser, policy=_POLICY)
        return result.model_copy(update={"attempts": (_REFUSED, *result.attempts)})

    site_id = await _site(conn)
    for _ in range(3):
        await learn_fetch(conn, site_id, refused_then("blocked"))
    assert (await remembered(conn, site_id, "detail")).method == "http"

    await learn_fetch(conn, site_id, refused_then("ok"))
    assert (await remembered(conn, site_id, "detail")).method == "browser"

    await learn_fetch(conn, site_id, fetch_result(_URL, 403, method="browser", block_class="blocked", policy=_POLICY))
    assert (await remembered(conn, site_id, "detail")).method == "http"
