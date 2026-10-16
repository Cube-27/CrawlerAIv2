"""Progressive state, the learning trigger and the `learn` job (SPEC-08 §4.4, §4.8), against a real Postgres."""

import uuid
from typing import Any

import pytest
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.progressive import (
    NotLearning,
    StateKey,
    learning_activated,
    learning_failed,
    request_learning,
    trigger_learning,
)
from crawlerai.db.models import ExtractionConfig, ExtractionConfigId, Job, ProgressiveState, Project, SchemaDef, Site

pytestmark = pytest.mark.anyio

BATCH = 10


async def _key(conn: AsyncConnection) -> StateKey:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id = (await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))).scalar_one()
    values = {"name": f"s_{uuid.uuid4().hex[:12]}", "page_kind": "detail", "fields": {}}
    schema_id = (
        await conn.execute(insert(SchemaDef).values(**values, origin="user", status="active").returning(SchemaDef.id))
    ).scalar_one()
    return StateKey(site_id=site_id, schema_id=schema_id, page_kind="detail")


async def _pages(conn: AsyncConnection, key: StateKey, pages: int) -> None:
    """`key`'s state with `pages` extracted pages, inserted cold or updated as it is."""
    row = select(ProgressiveState).where(*key.where())
    if (await conn.execute(row)).first() is None:
        await conn.execute(insert(ProgressiveState).values(**key.columns(), pages_extracted=pages))
    else:
        await conn.execute(update(ProgressiveState).where(*key.where()).values(pages_extracted=pages))


async def _state(conn: AsyncConnection, key: StateKey) -> Any:
    return (await conn.execute(select(ProgressiveState).where(*key.where()))).one()


async def _learn_jobs(conn: AsyncConnection, key: StateKey) -> list[Any]:
    jobs = select(Job).where(Job.kind == "learn", Job.schema_id == key.schema_id).order_by(Job.created_at)
    return list((await conn.execute(jobs)).all())


async def _config(conn: AsyncConnection, key: StateKey) -> ExtractionConfigId:
    values = {**key.columns(), "version": 1, "ir": {}, "origin": "induced"}
    config_id: ExtractionConfigId = (
        await conn.execute(insert(ExtractionConfig).values(**values).returning(ExtractionConfig.id))
    ).scalar_one()
    return config_id


async def test_seven_extracted_pages_do_not_trigger_learning(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await _pages(conn, key, 7)

    assert await trigger_learning(conn, batch=BATCH) == 0

    assert (await _state(conn, key)).mode == "cold"
    assert await _learn_jobs(conn, key) == []


async def test_eight_extracted_pages_start_one_learn_job(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await _pages(conn, key, 8)

    assert await trigger_learning(conn, batch=BATCH) == 1
    assert await trigger_learning(conn, batch=BATCH) == 0

    state = await _state(conn, key)
    assert (state.mode, state.learning_started_at is not None) == ("learning", True)
    [job] = await _learn_jobs(conn, key)
    project = (await conn.execute(select(Site.project_id).where(Site.id == key.site_id))).scalar_one()
    assert (job.status, job.project_id, job.schema_id) == ("queued", project, key.schema_id)
    assert job.request == {
        "site_id": str(key.site_id),
        "schema_id": str(key.schema_id),
        "page_kind": "detail",
        "force": False,
    }


async def test_a_failed_run_goes_cold_and_retries_after_eight_more_pages(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await _pages(conn, key, 9)
    await trigger_learning(conn, batch=BATCH)

    await learning_failed(conn, key)

    state = await _state(conn, key)
    assert (state.mode, state.learning_started_at, state.retry_at_pages) == ("cold", None, 17)
    await _pages(conn, key, 16)
    assert await trigger_learning(conn, batch=BATCH) == 0
    await _pages(conn, key, 17)
    assert await trigger_learning(conn, batch=BATCH) == 1
    assert len(await _learn_jobs(conn, key)) == 2


async def test_an_activated_config_makes_the_state_active(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await _pages(conn, key, 8)
    await trigger_learning(conn, batch=BATCH)
    config_id = await _config(conn, key)

    await learning_activated(conn, key, config_id)

    state = await _state(conn, key)
    now = (await conn.execute(select(func.now()))).scalar_one()
    assert (state.mode, state.active_config_id, state.learning_started_at, state.last_learned_at) == (
        "active",
        config_id,
        None,
        now,
    )
    await _pages(conn, key, 30)
    assert await trigger_learning(conn, batch=BATCH) == 0


async def test_an_explicit_learn_call_starts_learning_before_eight_pages(conn: AsyncConnection) -> None:
    key = await _key(conn)

    job_id = await request_learning(conn, key)

    assert [job.id for job in await _learn_jobs(conn, key)] == [job_id]
    state = await _state(conn, key)
    assert (state.mode, state.pages_extracted) == ("learning", 0)


async def test_a_learning_state_gets_no_second_job(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await request_learning(conn, key)

    assert await request_learning(conn, key) is None
    assert await request_learning(conn, key, force=True) is None
    assert len(await _learn_jobs(conn, key)) == 1


async def test_an_active_state_relearns_only_when_forced_and_keeps_its_config(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await request_learning(conn, key)
    config_id = await _config(conn, key)
    await learning_activated(conn, key, config_id)

    assert await request_learning(conn, key) is None
    forced = await request_learning(conn, key, force=True)
    assert [job.id for job in await _learn_jobs(conn, key)][1:] == [forced]
    state = await _state(conn, key)
    assert (state.mode, state.active_config_id, state.learning_started_at is not None) == ("active", config_id, True)

    await learning_failed(conn, key)

    state = await _state(conn, key)
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("active", config_id, None)
    assert state.retry_at_pages is None


async def test_ending_a_run_that_was_not_started_is_refused(conn: AsyncConnection) -> None:
    key = await _key(conn)
    await _pages(conn, key, 3)
    config_id = await _config(conn, key)

    with pytest.raises(NotLearning):
        await learning_failed(conn, key)
    with pytest.raises(NotLearning):
        await learning_activated(conn, key, config_id)
    assert (await _state(conn, key)).mode == "cold"


async def test_the_trigger_handles_at_most_one_batch(conn: AsyncConnection) -> None:
    keys = [await _key(conn) for _ in range(3)]
    for key in keys:
        await _pages(conn, key, 8)

    assert await trigger_learning(conn, batch=2) == 2
    assert await trigger_learning(conn, batch=2) == 1


@pytest.mark.parametrize(
    ("columns", "constraint"),
    [
        ({"mode": "learning"}, "ck_progressive_state_learning_has_started"),
        ({"mode": "active"}, "ck_progressive_state_active_has_config"),
    ],
)
async def test_inconsistent_states_are_refused(conn: AsyncConnection, columns: dict[str, Any], constraint: str) -> None:
    key = await _key(conn)

    statement = insert(ProgressiveState).values(**key.columns(), **columns)
    with pytest.raises(IntegrityError, match=constraint):
        await conn.execute(statement)
