import uuid
from typing import Any, get_args

import pytest
from sqlalchemy import Insert, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.db.models import Job, JobEvent, JobId, JobKind, Project, TaskOutcome, UrlTask

pytestmark = pytest.mark.anyio

MISSING_ID = uuid.UUID("00000000-0000-7000-8000-000000000000")


def _job(**columns: Any) -> Insert:
    """An insert of a job in the `default` project."""
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "scrape", "request": {}, "engine_version": "0+cal.0"}
    return insert(Job).values(**{**values, **columns})


async def _job_id(conn: AsyncConnection, **columns: Any) -> JobId:
    job_id: JobId = (await conn.execute(_job(**columns).returning(Job.id))).scalar_one()
    return job_id


def _task(job_id: JobId, **columns: Any) -> Insert:
    url = "https://example.test/p/1"
    return insert(UrlTask).values(**{"job_id": job_id, "url": url, "canonical_url": url, **columns})


async def test_a_new_job_is_queued_with_no_usage_and_no_cancel(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    job = (await conn.execute(select(Job).where(Job.id == job_id))).one()

    assert job.id.version == 7
    assert (job.status, job.usage, job.cancel_requested, job.started_at, job.finished_at, job.schema_id) == (
        "queued",
        {},
        False,
        None,
        None,
        None,
    )


async def test_a_new_task_is_queued_and_due_now(conn: AsyncConnection) -> None:
    task_id = (await conn.execute(_task(await _job_id(conn)).returning(UrlTask.id))).scalar_one()

    task = (await conn.execute(select(UrlTask).where(UrlTask.id == task_id))).one()
    created = (await conn.execute(select(Job.created_at))).scalar_one()

    assert (task.status, task.attempts, task.priority, task.depth, task.outcome, task.claimed_by) == (
        "queued",
        0,
        0,
        0,
        None,
        None,
    )
    assert task.next_attempt_at == created  # both are now(): the start of the same transaction


async def test_a_task_links_to_its_parent(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)
    parent = (await conn.execute(_task(job_id).returning(UrlTask.id))).scalar_one()

    child_url = "https://example.test/p/2"
    child = (
        await conn.execute(
            _task(job_id, url=child_url, canonical_url=child_url, parent_task_id=parent, depth=1).returning(UrlTask.id)
        )
    ).scalar_one()

    assert (await conn.execute(select(UrlTask.parent_task_id).where(UrlTask.id == child))).scalar_one() == parent


@pytest.mark.parametrize("kind", get_args(JobKind))
async def test_job_accepts_every_kind(conn: AsyncConnection, kind: str) -> None:
    await conn.execute(_job(kind=kind))

    assert (await conn.execute(select(Job.kind))).scalar_one() == kind


@pytest.mark.parametrize("outcome", get_args(TaskOutcome))
async def test_task_accepts_every_outcome(conn: AsyncConnection, outcome: str) -> None:
    await conn.execute(_task(await _job_id(conn), outcome=outcome))

    assert (await conn.execute(select(UrlTask.outcome))).scalar_one() == outcome


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"kind": "index"}, "ck_job_kind"),
        ({"status": "paused"}, "ck_job_status"),
        ({"project_id": MISSING_ID}, "fk_job_project_id_project"),
        ({"schema_id": MISSING_ID}, "fk_job_schema_id_schema_def"),
    ],
)
async def test_job_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(_job(**columns))


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"status": "running"}, "ck_url_task_status"),
        ({"outcome": "skipped"}, "ck_url_task_outcome"),
        ({"page_kind": "index"}, "ck_url_task_page_kind"),
        ({"attempts": -1}, "ck_url_task_attempts_non_negative"),
        ({"depth": -1}, "ck_url_task_depth_non_negative"),
        ({"parent_task_id": MISSING_ID}, "fk_url_task_parent_task_id_url_task"),
    ],
)
async def test_task_rejects_values_outside_its_domain(
    conn: AsyncConnection, columns: dict[str, Any], constraint: str
) -> None:
    job_id = await _job_id(conn)

    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(_task(job_id, **columns))


async def test_a_job_holds_each_canonical_url_once(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)
    await conn.execute(_task(job_id, url="https://example.test/p/1?ref=a"))

    with pytest.raises(IntegrityError, match="uq_url_task_job_id_canonical_url"):
        await conn.execute(_task(job_id, url="https://example.test/p/1?ref=b"))


async def test_two_jobs_may_hold_the_same_canonical_url(conn: AsyncConnection) -> None:
    await conn.execute(_task(await _job_id(conn)))
    await conn.execute(_task(await _job_id(conn)))

    assert (await conn.execute(select(func.count()).select_from(UrlTask))).scalar_one() == 2


async def test_task_requires_an_existing_job(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError, match="fk_url_task_job_id_job"):
        await conn.execute(_task(JobId(MISSING_ID)))


async def test_job_event_defaults_to_an_empty_payload_and_requires_its_job(conn: AsyncConnection) -> None:
    job_id = await _job_id(conn)

    await conn.execute(insert(JobEvent).values(job_id=job_id, kind="progress"))

    assert (await conn.execute(select(JobEvent.kind, JobEvent.payload))).one() == ("progress", {})
    with pytest.raises(IntegrityError, match="fk_job_event_job_id_job"):
        await conn.execute(insert(JobEvent).values(job_id=MISSING_ID, kind="progress"))
