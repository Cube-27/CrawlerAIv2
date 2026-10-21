"""A learning run's recipe replays (adapters spec) go out as politely as a served recipe's request (acquisition spec,
D-0731): at the endpoint host's rate, with no robots.txt request (owner decision #75); counted as the learn job's usage
(D-1381)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Job, JobId, Project, UsageEvent
from crawlerai.services.fetching import Fetching, learning_replay
from tests.db.support import fetching_from

pytestmark = pytest.mark.anyio


@dataclass
class Web:
    """Answers every endpoint with one JSON object; neither a page, robots.txt nor the browser is ever fetched."""

    fetch_result: Callable[..., FetchResult]
    requested: list[str] = field(default_factory=list)
    pools: list[str | None] = field(default_factory=list)  # the proxy pool of each request
    transferred: int = 0  # the bytes each answer says it moved

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("a replay fetches no page, and by default no robots.txt (owner decision #75)")

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("a replay never needs a browser")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request.url)
        self.pools.append(policy.proxy_pool)
        answer = self.fetch_result(request.page_url, 200, json.dumps({"data": {}}).encode(), method="api")
        return self._moved(answer)

    def _moved(self, result: FetchResult) -> FetchResult:
        attempts = tuple(attempt.model_copy(update={"transferred": self.transferred}) for attempt in result.attempts)
        return result.model_copy(update={"attempts": attempts})


@pytest.fixture
def api_host() -> str:
    """An endpoint host no other test uses."""
    return f"api-{uuid7().hex[-12:]}.example.test"


@pytest.fixture
async def job_id(engine: AsyncEngine) -> JobId:
    """A learn job whose usage the replays count as."""
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": project, "kind": "learn", "request": {}, "engine_version": "test"}
    async with engine.begin() as conn:
        created: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    return created


def _fetching(web: Web, tmp_path: Path) -> Fetching:
    return fetching_from(Rungs(http=web.http, browser=web.browser, json=web.json), tmp_path / "objects")


async def test_a_replay_counts_as_the_jobs_usage(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], api_host: str, tmp_path: Path, job_id: JobId
) -> None:
    web = Web(fetch_result, transferred=700)
    replays = learning_replay(engine, _fetching(web, tmp_path))
    assert replays is not None

    result = await replays(job_id)(JsonRequest(f"https://{api_host}/v1/p/a", "https://shop.example.test/p/a"))

    assert result.block_class == "ok"
    assert web.pools == [None]
    async with engine.connect() as conn:
        usage: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
        pools = set((await conn.execute(select(UsageEvent.model_or_pool).where(UsageEvent.job_id == job_id))).scalars())
    assert usage == {"http_requests": 1}
    assert pools == {None}
