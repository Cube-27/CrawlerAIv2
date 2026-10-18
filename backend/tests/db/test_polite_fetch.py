"""Fetching a task's page politely (SPEC-02 §4.6): robots.txt, the site's rate and backoff through the queue
(`worker.handlers.steps.fetch_queued`, the one polite fetch as a worker runs it)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import Admit, HostLimiter
from crawlerai.acquire.robots import RobotsSnapshot
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import Job, JobId, Project, Site, SiteId, UrlTask
from crawlerai.db.queue import ClaimedTask, claim_tasks
from crawlerai.recurring.conditional import Unchanged
from crawlerai.services.polite import HostRules, PageFetch, rules_in
from crawlerai.worker.handlers.steps import fetch_queued
from crawlerai.worker.loop import Failed, Finished, TaskResult

pytestmark = pytest.mark.anyio

ORIGIN = "https://shop.example.test"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
PAGE = b"<html><body><h1>Item</h1></body></html>"
DEFAULT_PROJECT = select(Project.id).where(Project.name == "default").scalar_subquery()
OVERRIDE = FetchPolicy(respect_robots=False, robots_override_reason="the site's operator asked for it")


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


async def _site(conn: AsyncConnection, **columns: Any) -> SiteId:
    values = {"project_id": DEFAULT_PROJECT, "host": "shop.example.test", **columns}
    site_id: SiteId = (await conn.execute(insert(Site).values(**values).returning(Site.id))).scalar_one()
    return site_id


async def _job(conn: AsyncConnection, *paths: str) -> JobId:
    values = {"project_id": DEFAULT_PROJECT, "kind": "scrape", "request": {}, "engine_version": "0+cal.0"}
    job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    rows = [{"job_id": job_id, "url": ORIGIN + path, "canonical_url": ORIGIN + path} for path in paths]
    await conn.execute(insert(UrlTask), rows)
    return job_id


async def _tasks(conn: AsyncConnection, *paths: str, attempts: int = 0) -> list[ClaimedTask]:
    job_id = await _job(conn, *paths)
    await conn.execute(update(UrlTask).where(UrlTask.job_id == job_id).values(attempts=attempts))
    tasks = await claim_tasks(conn, "w1", len(paths))
    return sorted(tasks, key=lambda task: paths.index(task.url.removeprefix(ORIGIN)))


async def _polite(
    conn: AsyncConnection,
    task: ClaimedTask,
    policy: FetchPolicy,
    page: PageFetch,
    limiter: HostLimiter,
    *,
    robots: "Web | None" = None,
    by_adapter: bool = False,
) -> FetchResult | Unchanged | TaskResult:
    """`fetch_queued` with `page`, and robots.txt fetched from `robots`, else from `page` (then a `Web`)."""
    web = robots or page
    assert isinstance(web, Web)
    return await fetch_queued(task, policy, rules_in(conn, web.rung, []), page, limiter, by_adapter=by_adapter)


async def _snapshot(conn: AsyncConnection, site_id: SiteId, origin: str = ORIGIN) -> RobotsSnapshot | None:
    stored = (await conn.execute(select(Site.robots_snapshot).where(Site.id == site_id))).scalar_one()
    snapshot = None if stored is None else json.loads(stored).get(f"{origin}/robots.txt")
    return None if snapshot is None else RobotsSnapshot.model_validate(snapshot)


async def test_a_disallowed_page_is_blocked_by_robots_without_being_fetched(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    [task] = await _tasks(conn, "/private/a")

    result = await _polite(conn, task, FetchPolicy(), web, HostLimiter())

    assert result == Finished("blocked", reason="robots")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    snapshot = await _snapshot(conn, site_id)
    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (200, ROBOTS)


async def test_the_override_fetches_a_disallowed_page_without_reading_robots(conn: AsyncConnection, web: Web) -> None:
    await _site(conn)
    web.pages[f"{ORIGIN}/private/a"] = (200, PAGE, ())
    [task] = await _tasks(conn, "/private/a")

    result = await _polite(conn, task, OVERRIDE, web, HostLimiter())

    assert isinstance(result, FetchResult)
    assert web.fetched == [f"{ORIGIN}/private/a"]
    assert result.bundle.manifest.url == f"{ORIGIN}/private/a"


async def test_an_unreachable_robots_file_fails_the_attempt_and_stores_nothing(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/robots.txt"] = (503, b"", ())
    [task] = await _tasks(conn, "/item/1")

    result = await _polite(conn, task, FetchPolicy(), web, HostLimiter())

    assert result == Failed("robots_unreachable", transient=True, exhausted="blocked")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    assert await _snapshot(conn, site_id) is None
