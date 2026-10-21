"""Fetching a task's page politely (acquisition spec): robots.txt, the site's rate and backoff through the queue
(`worker.handlers.steps.fetch_queued`, the one polite fetch as a worker runs it)."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import Admit, HostLimiter
from crawlerai.acquire.robots import RobotsSnapshot
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Job, JobId, Project, Site, SiteId, UrlTask
from crawlerai.db.queue import ClaimedTask, Failed, Finished, claim_tasks
from crawlerai.services.polite import QUEUED, HostRules, PageFetch, Turns, rules_of
from crawlerai.worker.handlers.steps import fetch_queued
from crawlerai.worker.loop import TaskResult

pytestmark = pytest.mark.anyio

ORIGIN = "https://shop.example.test"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
PAGE = b"<html><body><h1>Item</h1></body></html>"
DEFAULT_PROJECT = select(Project.id).where(Project.name == "default").scalar_subquery()
OBEYS = FetchPolicy(respect_robots=True)


@dataclass
class Web:
    """Answers each URL from `pages`, as (status, body, response headers); anything else is a 404. A page fetch's
    `Admit` goes unused: it makes one request."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes, tuple[tuple[str, str], ...]]] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    async def rung(self, url: str, _policy: FetchPolicy) -> FetchResult:
        return await self(url)

    async def __call__(self, url: str, _admit: Admit | None = None, _known: HostRules | None = None) -> FetchResult:
        self.fetched.append(url)
        status, body, headers = self.pages.get(url, (404, b"no such page", ()))
        return self.fetch_result(url, status, body, headers, block_class="ok" if status < 400 else "blocked")


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult]) -> Web:
    return Web(fetch_result, {f"{ORIGIN}/robots.txt": (200, ROBOTS.encode(), ())})


@pytest.fixture
async def site_id(engine: AsyncEngine) -> AsyncIterator[SiteId]:
    """The site of `ORIGIN`, deleted after the test: its row and robots.txt snapshot are written in transactions of
    their own (`rules_of`)."""
    host = urlsplit(ORIGIN).hostname
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.host == host))
        values = {"project_id": DEFAULT_PROJECT, "host": host}
        site: SiteId = (await conn.execute(insert(Site).values(**values).returning(Site.id))).scalar_one()
    yield site
    async with engine.begin() as conn:
        await conn.execute(delete(Site).where(Site.id == site))


async def _tasks(engine: AsyncEngine, *paths: str) -> list[ClaimedTask]:
    values = {"project_id": DEFAULT_PROJECT, "kind": "scrape", "request": {}, "engine_version": "0+cal.0"}
    async with engine.begin() as conn:
        job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
        rows = [{"job_id": job_id, "url": ORIGIN + path, "canonical_url": ORIGIN + path} for path in paths]
        await conn.execute(insert(UrlTask), rows)
        tasks = await claim_tasks(conn, "w1", len(paths))
    return sorted(tasks, key=lambda task: paths.index(task.url.removeprefix(ORIGIN)))


async def _polite(
    engine: AsyncEngine,
    task: ClaimedTask,
    policy: FetchPolicy,
    page: PageFetch,
    limiter: HostLimiter,
    *,
    robots: "Web | None" = None,
    by_adapter: bool = False,
) -> FetchResult | TaskResult:
    """`fetch_queued` with `page`, and robots.txt fetched from `robots`, else from `page` (then a `Web`)."""
    web = robots or page
    assert isinstance(web, Web)
    return await fetch_queued(
        task, policy, rules_of(engine, web.rung, [], Turns(limiter, QUEUED)), page, limiter, by_adapter=by_adapter
    )


async def _snapshot(engine: AsyncEngine, site_id: SiteId, origin: str = ORIGIN) -> RobotsSnapshot | None:
    async with engine.connect() as conn:
        stored = (await conn.execute(select(Site.robots_snapshot).where(Site.id == site_id))).scalar_one()
    snapshot = None if stored is None else json.loads(stored).get(f"{origin}/robots.txt")
    return None if snapshot is None else RobotsSnapshot.model_validate(snapshot)


async def test_a_disallowed_page_is_blocked_by_robots_without_being_fetched(
    engine: AsyncEngine, site_id: SiteId, web: Web
) -> None:
    [task] = await _tasks(engine, "/private/a")

    result = await _polite(engine, task, OBEYS, web, HostLimiter())

    assert result == Finished("blocked", reason="robots")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    snapshot = await _snapshot(engine, site_id)
    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (200, ROBOTS)


@pytest.mark.usefixtures("site_id")
async def test_by_default_a_disallowed_page_is_fetched_without_reading_robots(engine: AsyncEngine, web: Web) -> None:
    web.pages[f"{ORIGIN}/private/a"] = (200, PAGE, ())
    [task] = await _tasks(engine, "/private/a")

    result = await _polite(engine, task, FetchPolicy(), web, HostLimiter())

    assert isinstance(result, FetchResult)
    assert web.fetched == [f"{ORIGIN}/private/a"]
    assert result.bundle.manifest.url == f"{ORIGIN}/private/a"


async def test_an_unreachable_robots_file_fails_the_attempt_and_stores_nothing(
    engine: AsyncEngine, site_id: SiteId, web: Web
) -> None:
    web.pages[f"{ORIGIN}/robots.txt"] = (503, b"", ())
    [task] = await _tasks(engine, "/item/1")

    result = await _polite(engine, task, OBEYS, web, HostLimiter())

    assert result == Failed("robots_unreachable", transient=True, exhausted="blocked")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    assert await _snapshot(engine, site_id) is None
