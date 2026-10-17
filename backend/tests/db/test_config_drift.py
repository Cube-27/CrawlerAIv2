"""Drift recorded against a real Postgres (SPEC-08 §4.9): each run of an active config extends its window, a field
that falls below its validated yield is suspended in the IR and `field_status`, the suspension is a
`drift_suspended` job event, and the site re-learns while its config keeps serving."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.drift import DriftMargins, record_run
from crawlerai.config_ir.executor import EngineExecutor
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import StateKey, learning_activated, request_learning
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import (
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobEvent,
    JobId,
    ProgressiveState,
    Project,
    SchemaDef,
    SchemaId,
    Site,
)
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType
from crawlerai.schemas.types import SchemaDef as Schema

pytestmark = pytest.mark.anyio

MARGINS = DriftMargins.model_validate({"yield": 0.25, "validity": 0.25, "source_split": "dev", "fit": "test"})
OLD = "<html><body><h1 class='title'>A lamp</h1></body></html>"
NEW = "<html><body><h2 class='heading'>A lamp</h2></body></html>"
IR: dict[str, Any] = {
    "ir_version": "1",
    "site": "shop.example.test",
    "schema": {"name": "synthetic", "digest": "0" * 64},
    "page_kind": "detail",
    "fetch": {"method": "http"},
    "fields": {
        "title": {"steps": [{"xpath": "//h1[@class='title']"}], "status": "corroborated", "yield": 1.0, "validity": 1.0}
    },
    "provenance": {
        "origin": "induced",
        "validated_on": [],
        "learned_at": "2026-10-01T00:00:00Z",
        "engine_version": "t",
    },
}
SCHEMA = Schema.model_validate(
    {
        "id": SchemaId(uuid7()),
        "origin": "user",
        "status": "active",
        "name": "synthetic",
        "page_kind": "detail",
        "fields": {"title": FieldSpec(type=FieldType.TEXT, description="d")},
    }
)


async def _active_config(
    conn: AsyncConnection, ir: dict[str, Any] = IR, field_status: dict[str, str] | None = None
) -> tuple[StateKey, ExtractionConfigId, JobId]:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id = (await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))).scalar_one()
    values = {"name": f"s_{uuid.uuid4().hex[:12]}", "page_kind": "detail", "fields": {}}
    schema_id = (
        await conn.execute(insert(SchemaDef).values(**values, origin="user", status="active").returning(SchemaDef.id))
    ).scalar_one()
    key = StateKey(site_id=site_id, schema_id=schema_id, page_kind="detail")
    await request_learning(conn, key)
    config = {**key.columns(), "version": 1, "ir": ir, "origin": "induced", "status": "active"}
    config_id = (
        await conn.execute(
            insert(ExtractionConfig)
            .values(**config, field_status=field_status or {"title": "corroborated"})
            .returning(ExtractionConfig.id)
        )
    ).scalar_one()
    await learning_activated(conn, key, config_id)
    job = {"project_id": project, "kind": "scrape", "request": {}, "engine_version": "t"}
    job_id = (await conn.execute(insert(Job).values(**job).returning(Job.id))).scalar_one()
    return key, config_id, job_id


async def _run(conn: AsyncConnection, config_id: ExtractionConfigId, job_id: JobId, html: str, **kw: Any) -> list[str]:
    row: dict[str, Any] = (
        await conn.execute(select(ExtractionConfig.ir).where(ExtractionConfig.id == config_id))
    ).scalar_one()
    executor = EngineExecutor(ExtractionConfigIR.model_validate(row), Vocabulary(supertypes={}))
    executed = executor.execute(ParsedPage(html), SCHEMA, Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC)))
    found = await record_run(conn, config_id, executed.candidates, job_id=job_id, **{"margins": MARGINS, **kw})
    return [d.field for d in found]


async def _config(conn: AsyncConnection, config_id: ExtractionConfigId) -> Any:
    return (await conn.execute(select(ExtractionConfig).where(ExtractionConfig.id == config_id))).one()


async def test_a_layout_change_suspends_the_field_and_starts_a_forced_relearn(conn: AsyncConnection) -> None:
    key, config_id, job_id = await _active_config(conn)
    for _ in range(3):
        assert await _run(conn, config_id, job_id, OLD) == []
    assert await _run(conn, config_id, job_id, NEW) == []  # 3 of 4 = 0.75: not below 1.0 - 0.25

    assert await _run(conn, config_id, job_id, NEW) == ["title"]

    config = await _config(conn, config_id)
    assert config.drift_window == {"title": [[True, True]] * 3 + [[False, False]] * 2}
    assert (config.field_status, config.ir["fields"]["title"]["status"]) == ({"title": "suspended"}, "suspended")
    [event] = (await conn.execute(select(JobEvent).where(JobEvent.job_id == job_id))).all()
    assert (event.kind, event.payload) == (
        "drift_suspended",
        {
            "config_id": str(config_id),
            "field": "title",
            "pages": 5,
            "yield": 0.6,
            "validity": 1.0,
            "validated_yield": 1.0,
            "validated_validity": 1.0,
        },
    )
    learn = select(Job.request).where(Job.kind == "learn", Job.schema_id == key.schema_id).order_by(Job.id)
    requests: list[dict[str, Any]] = list((await conn.execute(learn)).scalars())
    assert [request["force"] for request in requests] == [False, True]
    state = (await conn.execute(select(ProgressiveState).where(*key.where()))).one()
    assert (state.mode, state.active_config_id, state.learning_started_at is not None) == ("active", config_id, True)


async def test_a_suspended_field_no_longer_runs_or_drifts_again(conn: AsyncConnection) -> None:
    _, config_id, job_id = await _active_config(conn)
    for html in (OLD, OLD, OLD, NEW, NEW):
        await _run(conn, config_id, job_id, html)

    assert await _run(conn, config_id, job_id, NEW) == []
    assert len((await _config(conn, config_id)).drift_window["title"]) == 5


async def test_without_margins_the_window_is_recorded_and_nothing_is_suspended(conn: AsyncConnection) -> None:
    _, config_id, job_id = await _active_config(conn)
    for _ in range(5):
        assert await _run(conn, config_id, job_id, NEW, margins=None) == []

    config = await _config(conn, config_id)
    assert (len(config.drift_window["title"]), config.field_status) == (5, {"title": "corroborated"})


async def test_a_config_that_is_not_active_records_nothing(conn: AsyncConnection) -> None:
    key, _, job_id = await _active_config(conn)
    replaced = {**key.columns(), "version": 2, "ir": IR, "origin": "induced", "status": "suspended"}
    other: ExtractionConfigId = (
        await conn.execute(insert(ExtractionConfig).values(**replaced).returning(ExtractionConfig.id))
    ).scalar_one()

    for _ in range(5):
        assert await _run(conn, other, job_id, NEW) == []
    assert (await _config(conn, other)).drift_window == {}


# A field the config lists as absent (D-1341).
ABSENT_IR = {**IR, "absent": ["price"]}
ABSENT_STATUS = {"title": "corroborated", "price": "absent"}


async def test_a_page_publishing_an_absent_field_re_tests_it(conn: AsyncConnection) -> None:
    key, config_id, job_id = await _active_config(conn, ABSENT_IR, ABSENT_STATUS)

    assert await _run(conn, config_id, job_id, OLD, published=["title", "price"]) == []

    config = await _config(conn, config_id)
    assert (config.ir["absent"], config.field_status) == ([], {"title": "corroborated"})
    [event] = (await conn.execute(select(JobEvent).where(JobEvent.job_id == job_id))).all()
    assert (event.kind, event.payload) == ("absent_stated", {"config_id": str(config_id), "field": "price"})
    learn = select(Job.request).where(Job.kind == "learn", Job.schema_id == key.schema_id).order_by(Job.id)
    requests: list[dict[str, Any]] = list((await conn.execute(learn)).scalars())
    assert [request["force"] for request in requests] == [False, True]


async def test_a_page_not_publishing_an_absent_field_leaves_it_absent(conn: AsyncConnection) -> None:
    key, config_id, job_id = await _active_config(conn, ABSENT_IR, ABSENT_STATUS)

    assert await _run(conn, config_id, job_id, OLD, published=["title"]) == []

    config = await _config(conn, config_id)
    assert (config.ir["absent"], config.field_status) == (["price"], ABSENT_STATUS)
    learn = select(Job.id).where(Job.kind == "learn", Job.schema_id == key.schema_id)
    assert len((await conn.execute(learn)).all()) == 1
