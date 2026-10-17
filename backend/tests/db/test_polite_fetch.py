"""Fetching a task's page politely (SPEC-02 §4.6): robots.txt, the site's rate and backoff through the queue.

The web is a stub that answers synthetic pages on RFC 2606 hosts; no network.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.politeness import Admit, HostLimiter
from crawlerai.acquire.robots import RobotsSnapshot
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.models import Job, JobId, Project, Site, SiteId, UrlTask
from crawlerai.db.queue import LEASE, ClaimedTask, claim_tasks
from crawlerai.recurring.conditional import Unchanged
from crawlerai.worker.loop import Failed, Finished, Postpone, TaskResult, run_worker
from crawlerai.worker.polite import fetch_politely

pytestmark = pytest.mark.anyio

ORIGIN = "https://shop.example.test"
ROBOTS = "User-agent: *\nDisallow: /private/\n"
OPEN_ROBOTS = "User-agent: *\nDisallow:\n"
PAGE = b"<html><body><h1>Item</h1></body></html>"
DEFAULT_PROJECT = select(Project.id).where(Project.name == "default").scalar_subquery()
OVERRIDE = FetchPolicy(respect_robots=False, robots_override_reason="the site's operator asked for it")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class Web:
    """Answers each URL from `pages`, as (status, body, response headers); anything else is a 404. A page fetch's
    `Admit` goes unused: it makes one request."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes, tuple[tuple[str, str], ...]]] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    async def __call__(self, url: str, _admit: Admit | None = None) -> FetchResult:
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
    conn: AsyncConnection, task: ClaimedTask, site_id: SiteId, policy: FetchPolicy, web: Web, limiter: HostLimiter
) -> FetchResult | Unchanged | TaskResult:
    """`fetch_politely` with `web` for both robots.txt and the page."""
    return await fetch_politely(conn, task, site_id, policy, web, limiter, fetch_robots=web)


def _stored(snapshots: dict[str, RobotsSnapshot]) -> str:
    """`site.robots_snapshot` holding `snapshots`, by the URL of the robots.txt each was fetched from."""
    return json.dumps({url: snapshot.model_dump(mode="json") for url, snapshot in snapshots.items()})


async def _snapshot(conn: AsyncConnection, site_id: SiteId, origin: str = ORIGIN) -> RobotsSnapshot | None:
    stored = (await conn.execute(select(Site.robots_snapshot).where(Site.id == site_id))).scalar_one()
    snapshot = None if stored is None else json.loads(stored).get(f"{origin}/robots.txt")
    return None if snapshot is None else RobotsSnapshot.model_validate(snapshot)


async def test_a_disallowed_page_is_blocked_by_robots_without_being_fetched(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    [task] = await _tasks(conn, "/private/a")

    result = await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter())

    assert result == Finished("blocked", reason="robots")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    snapshot = await _snapshot(conn, site_id)
    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (200, ROBOTS)


async def test_an_allowed_page_is_fetched_after_robots(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    [task] = await _tasks(conn, "/item/1")

    result = await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter())

    assert isinstance(result, FetchResult)
    assert (result.bundle.manifest.url, result.bundle.body) == (f"{ORIGIN}/item/1", PAGE)
    assert web.fetched == [f"{ORIGIN}/robots.txt", f"{ORIGIN}/item/1"]


async def test_robots_and_the_page_are_fetched_each_with_their_own_rung(
    conn: AsyncConnection, web: Web, fetch_result: Callable[..., FetchResult]
) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    page_rung = Web(fetch_result, dict(web.pages))
    [task] = await _tasks(conn, "/item/1")

    result = await fetch_politely(conn, task, site_id, FetchPolicy(), page_rung, HostLimiter(), fetch_robots=web)

    assert isinstance(result, FetchResult)
    assert (web.fetched, page_rung.fetched) == ([f"{ORIGIN}/robots.txt"], [f"{ORIGIN}/item/1"])


async def test_the_override_fetches_a_disallowed_page_without_reading_robots(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/private/a"] = (200, PAGE, ())
    [task] = await _tasks(conn, "/private/a")

    result = await _polite(conn, task, site_id, OVERRIDE, web, HostLimiter())

    assert isinstance(result, FetchResult)
    assert web.fetched == [f"{ORIGIN}/private/a"]
    assert result.bundle.manifest.url == f"{ORIGIN}/private/a"


async def test_a_fresh_snapshot_is_used_and_a_stale_one_refetched(conn: AsyncConnection, web: Web) -> None:
    fresh = RobotsSnapshot(fetched_at=datetime.now(UTC) - timedelta(hours=23), status_code=200, body="")
    site_id = await _site(conn, robots_snapshot=_stored({f"{ORIGIN}/robots.txt": fresh}))
    first, second = await _tasks(conn, "/private/a", "/private/b")

    # The fresh snapshot allows everything: no robots fetch, the page is fetched.
    assert isinstance(await _polite(conn, first, site_id, FetchPolicy(), web, HostLimiter()), FetchResult)
    assert web.fetched == [f"{ORIGIN}/private/a"]

    stale = fresh.model_copy(update={"fetched_at": datetime.now(UTC) - timedelta(hours=25)})
    stored = _stored({f"{ORIGIN}/robots.txt": stale})
    await conn.execute(update(Site).where(Site.id == site_id).values(robots_snapshot=stored))
    result = await _polite(conn, second, site_id, FetchPolicy(), web, HostLimiter())

    assert result == Finished("blocked", reason="robots")
    assert web.fetched[1:] == [f"{ORIGIN}/robots.txt"]
    snapshot = await _snapshot(conn, site_id)
    assert snapshot is not None
    assert snapshot.body == ROBOTS


async def test_each_origin_of_the_site_is_governed_by_its_own_robots_file(conn: AsyncConnection, web: Web) -> None:
    # RFC 9309 §2.3: robots.txt governs its scheme, host and port only.
    other = "http://shop.example.test:8080"
    web.pages[f"{other}/robots.txt"] = (200, OPEN_ROBOTS.encode(), ())
    web.pages[f"{other}/private/a"] = (200, PAGE, ())
    site_id = await _site(conn)
    [task] = await _tasks(conn, "/private/a")

    assert await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter()) == Finished("blocked", reason="robots")
    other_task = replace(task, url=f"{other}/private/a")
    assert isinstance(await _polite(conn, other_task, site_id, FetchPolicy(), web, HostLimiter()), FetchResult)

    assert web.fetched == [f"{ORIGIN}/robots.txt", f"{other}/robots.txt", f"{other}/private/a"]
    snapshots = [await _snapshot(conn, site_id, origin) for origin in (ORIGIN, other)]
    assert [None if snapshot is None else snapshot.body for snapshot in snapshots] == [ROBOTS, OPEN_ROBOTS]


async def test_a_snapshot_stored_before_origins_were_kept_apart_is_fetched_again(
    conn: AsyncConnection, web: Web
) -> None:
    unkeyed = RobotsSnapshot(fetched_at=datetime.now(UTC), status_code=200, body="")
    site_id = await _site(conn, robots_snapshot=unkeyed.model_dump_json())
    [task] = await _tasks(conn, "/private/a")

    assert await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter()) == Finished("blocked", reason="robots")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    snapshot = await _snapshot(conn, site_id)
    assert snapshot is not None
    assert snapshot.body == ROBOTS


async def test_a_missing_robots_file_allows_everything(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    del web.pages[f"{ORIGIN}/robots.txt"]
    web.pages[f"{ORIGIN}/private/a"] = (200, PAGE, ())
    [task] = await _tasks(conn, "/private/a")

    assert isinstance(await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter()), FetchResult)
    snapshot = await _snapshot(conn, site_id)
    assert snapshot is not None
    assert (snapshot.status_code, snapshot.body) == (404, "")


async def test_an_unreachable_robots_file_fails_the_attempt_and_stores_nothing(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/robots.txt"] = (503, b"", ())
    [task] = await _tasks(conn, "/item/1")

    result = await _polite(conn, task, site_id, FetchPolicy(), web, HostLimiter())

    assert result == Failed("robots_unreachable", transient=True, exhausted="blocked")
    assert web.fetched == [f"{ORIGIN}/robots.txt"]
    assert await _snapshot(conn, site_id) is None


@pytest.mark.parametrize(
    ("crawl_delay_ms", "robots", "wait"),
    [
        (None, ROBOTS, timedelta(seconds=1)),
        (5000, ROBOTS, timedelta(seconds=5)),
        (500, ROBOTS + "Crawl-delay: 10\n", timedelta(seconds=10)),
    ],
)
async def test_a_second_page_of_the_site_waits_out_the_interval_in_the_queue(
    conn: AsyncConnection, web: Web, crawl_delay_ms: int | None, robots: str, wait: timedelta
) -> None:
    site_id = await _site(conn, crawl_delay_ms=crawl_delay_ms)
    web.pages[f"{ORIGIN}/robots.txt"] = (200, robots.encode(), ())
    first, second = await _tasks(conn, "/item/1", "/item/2")
    clock = Clock()
    limiter = HostLimiter(clock)

    assert isinstance(await _polite(conn, first, site_id, FetchPolicy(), web, limiter), FetchResult)
    clock.now += 0.25
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(wait - timedelta(seconds=0.25))
    clock.now += (wait - timedelta(seconds=0.25)).total_seconds()
    assert isinstance(await _polite(conn, second, site_id, FetchPolicy(), web, limiter), FetchResult)
    assert web.fetched == [f"{ORIGIN}/robots.txt", f"{ORIGIN}/item/1", f"{ORIGIN}/item/2"]


@pytest.mark.parametrize(
    ("status", "headers", "attempts", "asked", "pause"),
    [
        (429, (("Retry-After", "120"),), 0, timedelta(seconds=120), timedelta(seconds=120)),
        # Without Retry-After the queue's backoff applies: 30 s, doubling per attempt.
        (429, (), 0, None, timedelta(seconds=30)),
        (503, (), 1, None, timedelta(seconds=60)),
    ],
)
async def test_a_slow_down_response_retries_after_retry_after_or_the_backoff(
    conn: AsyncConnection,
    web: Web,
    status: int,
    headers: tuple[tuple[str, str], ...],
    attempts: int,
    asked: timedelta | None,
    pause: timedelta,
) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (status, b"", headers)
    first, second = await _tasks(conn, "/item/1", "/item/2", attempts=attempts)
    clock = Clock()
    limiter = HostLimiter(clock)

    result = await _polite(conn, first, site_id, FetchPolicy(), web, limiter)

    assert result == Failed(f"http {status}", transient=True, after=asked, exhausted="blocked")
    # The site's other pages wait out the same pause.
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(pause)


async def test_after_a_slow_down_the_sites_pages_come_at_twice_the_interval(conn: AsyncConnection, web: Web) -> None:
    # D-1327: once the asked pause is over, the host's spacing stays doubled until a run of `ok` answers shrinks it.
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (429, b"", (("Retry-After", "5"),))
    web.pages[f"{ORIGIN}/item/2"] = (200, PAGE, ())
    first, second, third = await _tasks(conn, "/item/1", "/item/2", "/item/3")
    clock = Clock()
    limiter = HostLimiter(clock)

    await _polite(conn, first, site_id, FetchPolicy(), web, limiter)
    clock.now += 5
    assert isinstance(await _polite(conn, second, site_id, FetchPolicy(), web, limiter), FetchResult)
    clock.now += 1

    assert await _polite(conn, third, site_id, FetchPolicy(), web, limiter) == Postpone(timedelta(seconds=1))


async def test_an_api_requests_slow_down_does_not_slow_the_pages_host(conn: AsyncConnection, web: Web) -> None:
    # D-1327: an adapter's or recipe's request goes to its endpoint, whose host's rate observes it (`_polite_json`).
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    first, second, third = await _tasks(conn, "/item/1", "/item/2", "/item/3")
    clock = Clock()
    limiter = HostLimiter(clock)

    async def after_an_endpoint(url: str, admit: Admit) -> FetchResult:
        page = await web(url)
        endpoint = AttemptRecord(method="api", status=429, block_class="blocked", duration_ms=1)
        return page.model_copy(update={"attempts": (endpoint, *page.attempts)})

    await fetch_politely(conn, first, site_id, FetchPolicy(), after_an_endpoint, limiter, fetch_robots=web)
    clock.now += 1
    await _polite(conn, second, site_id, FetchPolicy(), web, limiter)
    clock.now += 1

    assert isinstance(await _polite(conn, third, site_id, FetchPolicy(), web, limiter), FetchResult)


async def test_a_further_request_of_the_fetch_takes_a_turn_at_the_sites_rate(conn: AsyncConnection, web: Web) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    first, second = await _tasks(conn, "/item/1", "/item/2")
    clock = Clock()
    limiter = HostLimiter(clock)

    async def retried(url: str, admit: Admit) -> FetchResult:
        # The first request takes a second; its retry is admitted as it ends, at the next turn.
        clock.now += 1.0
        await admit()
        return await web(url)

    first_result = await fetch_politely(conn, first, site_id, FetchPolicy(), retried, limiter, fetch_robots=web)

    assert isinstance(first_result, FetchResult)
    clock.now += 0.25
    # The retry took the turn at 1 s, so the site's next page waits until 2 s, not 1 s.
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(timedelta(seconds=0.75))


async def test_a_slow_down_answering_a_request_whose_outcome_was_not_kept_backs_off(
    conn: AsyncConnection, web: Web
) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (403, b"", ())
    first, second = await _tasks(conn, "/item/1", "/item/2")
    clock = Clock()
    limiter = HostLimiter(clock)
    browser = AttemptRecord(method="browser", status=503, block_class="blocked", duration_ms=1)

    async def retried(url: str, _admit: Admit) -> FetchResult:
        # The HTTP outcome is kept; the browser retry was answered 503.
        kept = await web(url)
        return kept.model_copy(update={"attempts": (*kept.attempts, browser)})

    result = await fetch_politely(conn, first, site_id, FetchPolicy(), retried, limiter, fetch_robots=web)

    assert result == Failed("http 503", transient=True, after=None, exhausted="blocked")
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(timedelta(seconds=30))


async def test_a_page_kept_ok_after_a_slow_down_to_an_earlier_request_is_the_tasks_page(
    conn: AsyncConnection, web: Web
) -> None:
    # SPEC-15 §4.9: an adapter's endpoint asked for fewer requests, and the page fetched after it on its turn is `ok`.
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/robots.txt"] = (200, OPEN_ROBOTS.encode(), ())
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    (task,) = await _tasks(conn, "/item/1")
    endpoint = AttemptRecord(method="api", status=429, block_class="blocked", duration_ms=1)

    async def fallen_back(url: str, _admit: Admit) -> FetchResult:
        page = await web(url)
        return page.model_copy(update={"attempts": (endpoint, *page.attempts)})

    result = await fetch_politely(
        conn, task, site_id, FetchPolicy(), fallen_back, HostLimiter(Clock()), fetch_robots=web
    )

    assert isinstance(result, FetchResult)
    assert [(a.method, a.status) for a in result.attempts] == [("api", 429), ("http", 200)]


async def test_a_retry_after_answering_a_request_whose_outcome_was_not_kept_is_read(
    conn: AsyncConnection, web: Web
) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (403, b"", ())
    first, second = await _tasks(conn, "/item/1", "/item/2")
    limiter = HostLimiter(Clock())
    asked = timedelta(seconds=120)
    browser = AttemptRecord(method="browser", status=429, block_class="blocked", duration_ms=1, retry_after=asked)

    async def retried(url: str, _admit: Admit) -> FetchResult:
        kept = await web(url)
        return kept.model_copy(update={"attempts": (*kept.attempts, browser)})

    result = await fetch_politely(conn, first, site_id, FetchPolicy(), retried, limiter, fetch_robots=web)

    assert result == Failed("http 429", transient=True, after=asked, exhausted="blocked")
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(asked)


async def test_a_further_request_whose_turn_would_outlast_the_claim_is_not_waited_for(
    conn: AsyncConnection, web: Web
) -> None:
    # A robots Crawl-delay as long as the lease: waiting in place for the turn would lose the task's claim.
    site_id = await _site(conn, crawl_delay_ms=int(LEASE.total_seconds() * 1000))
    web.pages[f"{ORIGIN}/item/1"] = (200, PAGE, ())
    [task] = await _tasks(conn, "/item/1")
    clock = Clock()
    answers: list[bool] = []

    async def retried(url: str, admit: Admit) -> FetchResult:
        answers.append(await admit())
        return await web(url)

    result = await fetch_politely(conn, task, site_id, FetchPolicy(), retried, HostLimiter(clock), fetch_robots=web)

    assert answers == [False]
    assert isinstance(result, FetchResult)


@pytest.mark.parametrize("value", ["901", "99999999999999", "9" * 5000])
async def test_a_retry_after_beyond_15_min_blocks_the_task(conn: AsyncConnection, web: Web, value: str) -> None:
    site_id = await _site(conn)
    web.pages[f"{ORIGIN}/item/1"] = (429, b"", (("Retry-After", value),))
    first, second = await _tasks(conn, "/item/1", "/item/2")
    clock = Clock()
    limiter = HostLimiter(clock)

    assert await _polite(conn, first, site_id, FetchPolicy(), web, limiter) == Finished("blocked", reason="http 429")
    assert await _polite(conn, second, site_id, FetchPolicy(), web, limiter) == Postpone(timedelta(minutes=15))


async def test_through_the_worker_retry_after_sets_the_next_attempt_and_robots_end_the_task(
    engine: AsyncEngine, web: Web
) -> None:
    web.pages[f"{ORIGIN}/item/1"] = (429, b"", (("Retry-After", "120"),))
    async with engine.begin() as conn:
        site_id = await _site(conn)
        await _job(conn, "/private/a", "/item/1")
    limiter = HostLimiter()

    async def handler(task: ClaimedTask, conn: AsyncConnection) -> TaskResult:
        result = await _polite(conn, task, site_id, FetchPolicy(), web, limiter)
        return Finished("extracted") if isinstance(result, FetchResult | Unchanged) else result

    query = select(
        UrlTask.url,
        UrlTask.status,
        UrlTask.outcome,
        UrlTask.attempts,
        UrlTask.last_error,
        UrlTask.next_attempt_at - func.now(),
    ).order_by(UrlTask.url)

    async def rows() -> list[Any]:
        async with engine.connect() as conn:
            return list(await conn.execute(query))

    async def both_ran() -> bool:
        return [row.status for row in await rows()] == ["queued", "done"] and len(web.fetched) == 2

    stop = asyncio.Event()
    settings = Settings(
        database_url=SecretStr(engine.url.render_as_string(hide_password=False)), object_store="fs:///unused"
    )
    worker = asyncio.create_task(run_worker(settings, {"scrape": handler}, stop))
    try:
        async with asyncio.timeout(60):
            while not await both_ran():
                await asyncio.sleep(0.1)
    finally:
        stop.set()
        await worker

    try:
        item, private = await rows()
        assert tuple(private)[:5] == (f"{ORIGIN}/private/a", "done", "blocked", 1, "robots")
        assert tuple(item)[:5] == (f"{ORIGIN}/item/1", "queued", None, 1, "http 429")
        assert timedelta(seconds=100) < item[5] <= timedelta(seconds=120)
        assert web.fetched == [f"{ORIGIN}/robots.txt", f"{ORIGIN}/item/1"]
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(UrlTask))
            await conn.execute(delete(Job))
            await conn.execute(delete(Site).where(Site.id == site_id))


async def test_a_page_an_adapter_serves_first_is_fetched_with_no_fallback_robots_disallows(
    conn: AsyncConnection, web: Web
) -> None:
    # SPEC-15 §4.6: the adapter requests its API, whose own robots.txt `send` reads; the page's robots.txt governs only
    # the page rungs the fetch would fall back to, which it then admits none of.
    site_id = await _site(conn)
    [task] = await _tasks(conn, "/private/a")
    admitted: list[bool] = []

    async def adapter_first(url: str, admit: Admit) -> FetchResult:
        admitted.append(await admit())
        return await web(url)

    web.pages[f"{ORIGIN}/private/a"] = (200, PAGE, ())
    served = await fetch_politely(
        conn, task, site_id, FetchPolicy(), adapter_first, HostLimiter(), fetch_robots=web, by_adapter=True
    )
    assert isinstance(served, FetchResult)
    assert admitted == [False]

    web.pages[f"{ORIGIN}/private/a"] = (503, b"", ())
    unserved = await fetch_politely(
        conn, task, site_id, FetchPolicy(), adapter_first, HostLimiter(), fetch_robots=web, by_adapter=True
    )
    assert unserved == Finished("blocked", reason="robots")
