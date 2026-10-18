"""A scored crawl's frontier replacing a queued task (jobs spec, "Crawl strategy and best-first scoring") while a worker
claims it, over two connections: a task being claimed is never the one evicted, so its worker keeps its lease. Hosts are
RFC 2606 names."""

import asyncio

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.crawl.frontier import Frontier
from crawlerai.crawl.rules import Scope
from crawlerai.db.models import Job, JobId, Project, UrlTask

pytestmark = pytest.mark.anyio

BASE = "https://shop.example.test"


async def _waiting_or_done(engine: AsyncEngine, task: asyncio.Task[int]) -> None:
    """Return once `task` is done or another session of the database waits on a lock (`pg_stat_activity`)."""
    waiting = (
        select(func.count())
        .select_from(text("pg_stat_activity"))
        .where(text("datname = current_database() AND wait_event_type = 'Lock'"))
    )
    async with engine.connect() as conn:
        for _ in range(500):
            if task.done() or (await conn.execute(waiting)).scalar_one():
                return
            await asyncio.sleep(0.01)
    raise AssertionError("the enqueue neither ended nor waited on a lock")


async def test_a_task_being_claimed_is_not_evicted_by_a_better_candidate(engine: AsyncEngine) -> None:
    frontier = Frontier(Scope("shop.example.test"), (), 5, 1, "dfs")  # capacity 5 tasks: the start task and 4 more
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"project_id": project, "kind": "crawl", "request": {}, "engine_version": "test"}
        job: JobId = (await conn.execute(insert(Job).values(values).returning(Job.id))).scalar_one()
        await conn.execute(insert(UrlTask).values(job_id=job, url=f"{BASE}/", canonical_url=f"{BASE}/"))
        await frontier.enqueue(conn, job, [f"{BASE}/shallow{n}" for n in range(4)], depth=1, parent=None)
    weakest = UrlTask.canonical_url == f"{BASE}/shallow3"  # of equal scores, the newest is evicted first

    async with engine.connect() as claiming:
        # A worker's claim in progress: the row locked as `claim_tasks` locks it, and leased.
        await claiming.begin()
        await claiming.execute(select(UrlTask.id).where(weakest).with_for_update())
        await claiming.execute(update(UrlTask).where(weakest).values(status="claimed"))

        async def enqueue_better() -> int:
            async with engine.begin() as conn:
                return await frontier.enqueue(conn, job, [f"{BASE}/deep0"], depth=4, parent=None)

        enqueuing = asyncio.create_task(enqueue_better())
        await _waiting_or_done(engine, enqueuing)
        await claiming.commit()
        added = await enqueuing

    async with engine.connect() as conn:
        rows = await conn.execute(select(UrlTask.url, UrlTask.status).where(UrlTask.job_id == job))
        tasks: dict[str, str] = {url: status for url, status in rows}
    assert added == 1
    assert tasks[f"{BASE}/shallow3"] == "claimed"
    assert sorted(tasks) == sorted([f"{BASE}/", f"{BASE}/deep0", *(f"{BASE}/shallow{n}" for n in range(4) if n != 2)])
