import itertools
from typing import get_args

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.jobs import (
    JOB_TRANSITIONS,
    TASK_TRANSITIONS,
    InvalidTransition,
    record_event,
    transition_job,
    transition_task,
)
from crawlerai.db.models import Job, JobEvent, JobId, JobStatus, Project, TaskStatus, UrlTask, UrlTaskId

pytestmark = pytest.mark.anyio


async def _job(conn: AsyncConnection, status: JobStatus = "queued") -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "crawl", "request": {}, "engine_version": "0+cal.0"}
    job_id: JobId = (await conn.execute(insert(Job).values(**values, status=status).returning(Job.id))).scalar_one()
    return job_id


async def _task(conn: AsyncConnection, status: TaskStatus = "queued") -> UrlTaskId:
    url = "https://example.test/p/1"
    values = {"job_id": await _job(conn, "running"), "url": url, "canonical_url": url, "status": status}
    task_id: UrlTaskId = (await conn.execute(insert(UrlTask).values(**values).returning(UrlTask.id))).scalar_one()
    return task_id


async def _events(conn: AsyncConnection, job_id: JobId) -> list[tuple[str, dict[str, object]]]:
    rows = await conn.execute(select(JobEvent.kind, JobEvent.payload).where(JobEvent.job_id == job_id))
    return [(row.kind, row.payload) for row in rows]


@pytest.mark.parametrize(("current", "target"), itertools.product(get_args(JobStatus), repeat=2))
async def test_job_moves_only_along_the_state_machine(
    conn: AsyncConnection, current: JobStatus, target: JobStatus
) -> None:
    job_id = await _job(conn, current)

    if target in JOB_TRANSITIONS[current]:
        await transition_job(conn, job_id, target)
    else:
        with pytest.raises(InvalidTransition, match=f"job {job_id}: {current} -> {target}"):
            await transition_job(conn, job_id, target)

    expected = target if target in JOB_TRANSITIONS[current] else current
    assert (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one() == expected


@pytest.mark.parametrize(("current", "target"), itertools.product(get_args(TaskStatus), repeat=2))
async def test_task_moves_only_along_the_state_machine(
    conn: AsyncConnection, current: TaskStatus, target: TaskStatus
) -> None:
    task_id = await _task(conn, current)

    if target in TASK_TRANSITIONS[current]:
        await transition_task(conn, task_id, target)
    else:
        with pytest.raises(InvalidTransition, match=f"url_task {task_id}: {current} -> {target}"):
            await transition_task(conn, task_id, target)

    expected = target if target in TASK_TRANSITIONS[current] else current
    assert (await conn.execute(select(UrlTask.status).where(UrlTask.id == task_id))).scalar_one() == expected


async def test_a_completed_job_cannot_be_restarted(conn: AsyncConnection) -> None:
    job_id = await _job(conn, "completed")

    with pytest.raises(InvalidTransition):
        await transition_job(conn, job_id, "running")


async def test_a_queued_job_cannot_complete_without_running(conn: AsyncConnection) -> None:
    job_id = await _job(conn)

    with pytest.raises(InvalidTransition):
        await transition_job(conn, job_id, "completed")


async def test_starting_a_job_stamps_started_at_only(conn: AsyncConnection) -> None:
    job_id = await _job(conn)

    await transition_job(conn, job_id, "running")

    job = (await conn.execute(select(Job.started_at, Job.finished_at, Job.created_at))).one()
    assert (job.started_at, job.finished_at) == (job.created_at, None)
    assert await _events(conn, job_id) == []


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
async def test_ending_a_job_stamps_finished_at_and_records_one_event(
    conn: AsyncConnection, terminal: JobStatus
) -> None:
    job_id = await _job(conn, "running")

    await transition_job(conn, job_id, terminal)

    finished_at, created_at = (await conn.execute(select(Job.finished_at, Job.created_at))).one()
    assert finished_at == created_at
    assert await _events(conn, job_id) == [(terminal, {})]


async def test_requeueing_a_claimed_task_releases_its_lease(conn: AsyncConnection) -> None:
    task_id = await _task(conn, "claimed")
    await conn.execute(update(UrlTask).values(claimed_by="worker-1", lease_until=UrlTask.next_attempt_at))

    await transition_task(conn, task_id, "queued")

    assert (await conn.execute(select(UrlTask.status, UrlTask.claimed_by, UrlTask.lease_until))).one() == (
        "queued",
        None,
        None,
    )


async def test_finishing_a_claimed_task_keeps_who_claimed_it(conn: AsyncConnection) -> None:
    task_id = await _task(conn, "claimed")
    await conn.execute(update(UrlTask).values(claimed_by="worker-1"))

    await transition_task(conn, task_id, "done")

    assert (await conn.execute(select(UrlTask.status, UrlTask.claimed_by))).one() == ("done", "worker-1")


async def test_record_event_appends_in_order(conn: AsyncConnection) -> None:
    job_id = await _job(conn, "running")

    await record_event(conn, job_id, "task_fetched", {"method": "http", "block_class": "ok"})
    await record_event(conn, job_id, "progress", {"done": 1})

    assert await _events(conn, job_id) == [
        ("task_fetched", {"method": "http", "block_class": "ok"}),
        ("progress", {"done": 1}),
    ]
