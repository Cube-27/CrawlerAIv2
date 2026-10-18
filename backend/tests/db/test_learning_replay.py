"""A learning run's recipe replays (SPEC-09 §4.6, §4.7) go out as politely as a served recipe's request (SPEC-02 §4.6,
D-0731): only where the endpoint host's robots.txt allows, at that host's rate; through the site's proxy pool, counted
as the learn job's usage (D-1381)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.db.models import Job, JobId, Project, Site, UsageEvent
from crawlerai.services.fetching import Fetching, learning_replay
from crawlerai.storage.fs import FsStore
from tests.db.conftest import resolve

pytestmark = pytest.mark.anyio


@dataclass
class Web:
    """Answers robots.txt from `robots` and every endpoint with one JSON object; the browser is never used."""

    fetch_result: Callable[..., FetchResult]
    robots: bytes
    requested: list[str] = field(default_factory=list)
    pools: list[str | None] = field(default_factory=list)  # the proxy pool of each request, robots.txt's too
    transferred: int = 0  # the bytes each answer says it moved

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        assert url.endswith("/robots.txt"), "a replay fetches no page"
        self.pools.append(policy.proxy_pool)
        return self._moved(self.fetch_result(url, 200, self.robots))

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
async def api_host(engine: AsyncEngine) -> AsyncIterator[str]:
    """An endpoint host no other test uses; the site row the replay creates for it is deleted afterwards."""
    host = f"api-{uuid7().hex[-12:]}.example.test"
    yield host
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.host == host))


@pytest.fixture
async def job_id(engine: AsyncEngine) -> JobId:
    """A learn job whose usage the replays count as; the `engine` fixture deletes it afterwards."""
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": project, "kind": "learn", "request": {}, "engine_version": "test"}
    async with engine.begin() as conn:
        created: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    return created


def _fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.http, browser=web.browser, json=web.json)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


async def test_a_replay_robots_txt_disallows_is_not_sent(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], api_host: str, tmp_path: Path, job_id: JobId
) -> None:
    web = Web(fetch_result, b"User-agent: *\nDisallow: /v1/\n")
    replays = learning_replay(engine, _fetching(web, tmp_path))
    assert replays is not None

    result = await replays(job_id, None)(
        JsonRequest(f"https://{api_host}/v1/products/item-a", "https://shop.example.test/p/item-a")
    )

    assert (result.block_class, result.attempts[-1].error, web.requested) == ("blocked", "robots", [])


async def test_a_replay_goes_through_the_sites_proxy_pool_and_counts_its_bytes_as_the_jobs_usage(
    engine: AsyncEngine, fetch_result: Callable[..., FetchResult], api_host: str, tmp_path: Path, job_id: JobId
) -> None:
    web = Web(fetch_result, b"User-agent: *\nAllow: /\n", transferred=700)
    replays = learning_replay(engine, _fetching(web, tmp_path))
    assert replays is not None

    result = await replays(job_id, "dc")(JsonRequest(f"https://{api_host}/v1/p/a", "https://shop.example.test/p/a"))

    assert result.block_class == "ok"
    assert web.pools == ["dc", "dc"]  # robots.txt, then the endpoint
    async with engine.connect() as conn:
        usage: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
        pools = set((await conn.execute(select(UsageEvent.model_or_pool).where(UsageEvent.job_id == job_id))).scalars())
    assert usage == {"http_requests": 2, "proxy_bytes": 1400}
    assert pools == {"dc"}
