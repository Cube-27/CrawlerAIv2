"""The schema registry against Postgres (SPEC-04 §4.1, §4.2): presets synced, and one row per name edited in place,
the edit sending the schema's configs back to learning (`services.schemas`, `progressive.relearn_schema`)."""

import asyncio
import uuid
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.cli import main
from crawlerai.config_ir.progressive import StateKey
from crawlerai.db.models import ExtractionConfig, ProgressiveState
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.schemas import registry
from crawlerai.schemas.registry import PresetConflict, load_presets
from crawlerai.schemas.types import SchemaContent, SchemaDef, SchemaDocument
from crawlerai.services import schemas
from tests.db.conftest import learned_site

pytestmark = pytest.mark.anyio

PRESETS = ["commerce_detail", "commerce_listing", "job_detail", "job_listing"]
TITLE = {"type": "text", "required": True, "description": "Name of the event"}
STARTS = {"type": "datetime", "description": "When the event starts"}


def _custom(name: str = "event_detail") -> SchemaDocument:
    return SchemaDocument.model_validate(
        {"name": name, "page_kind": "detail", "fields": {"title": TITLE, "starts": STARTS}}
    )


async def _edit(conn: AsyncConnection, schema: SchemaDef, groups: list[list[str]]) -> SchemaDef:
    """`schema` with its required groups replaced, through the service a caller's edit goes through."""
    content = SchemaContent(page_kind=schema.page_kind, fields=schema.fields, required_groups=groups)
    return await schemas.update(conn, schema.id, content)


async def _statuses(conn: AsyncConnection, key: StateKey) -> list[str]:
    query = select(ExtractionConfig.status).where(*key.config_scope()).order_by(ExtractionConfig.version)
    return list((await conn.execute(query)).scalars())


async def _state(conn: AsyncConnection, key: StateKey) -> tuple[Any, ...]:
    state = ProgressiveState
    query = select(
        state.mode, state.active_config_id, state.learning_started_at, state.retry_at_pages, state.pages_extracted
    ).where(*key.where())
    return tuple((await conn.execute(query)).one())


async def test_synced_presets_read_back_as_written_with_every_field_described(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)

    for preset in load_presets():
        stored = await registry.get(conn, preset.name)
        assert SchemaDocument.model_validate(stored.model_dump(include=set(SchemaDocument.model_fields))) == preset
        assert all(spec.description for spec in stored.fields.values())


async def test_a_changed_preset_is_updated_in_place_and_its_sites_learn_again(conn: AsyncConnection) -> None:
    [stored, *_] = await registry.sync_presets(conn)
    key = await learned_site(conn, stored, ["active"])
    changed = load_presets()[0].model_copy(update={"required_groups": []})

    written = await schemas.sync_presets(conn, [changed])

    assert written == [stored.model_copy(update={"required_groups": []})]
    assert await _statuses(conn, key) == ["suspended"]
    assert [s.name for s in await registry.list_schemas(conn)] == PRESETS
    assert await registry.sync_presets(conn, [changed]) == []


async def test_a_preset_name_taken_by_a_user_schema_is_refused(conn: AsyncConnection) -> None:
    user = await registry.create(conn, _custom(), "user")

    presets = [_custom("event_listing"), _custom()]
    with pytest.raises(PresetConflict, match="event_detail"):
        await registry.sync_presets(conn, presets)
    assert await registry.list_schemas(conn) == [user]  # nothing written


async def test_an_edit_suspends_the_active_configs_and_sends_the_states_back_to_cold(conn: AsyncConnection) -> None:
    schema = await registry.create(conn, _custom(), "user")
    key = await learned_site(conn, schema, ["suspended", "draft", "active"])

    edited = await _edit(conn, schema, [["starts"]])

    assert edited == schema.model_copy(update={"required_groups": [["starts"]]})
    assert await registry.list_schemas(conn, name=schema.name) == [edited]
    assert await _statuses(conn, key) == ["suspended", "draft", "suspended"]
    assert await _state(conn, key) == ("cold", None, None, None, 12)


async def test_an_edit_that_changes_nothing_keeps_what_was_learned(conn: AsyncConnection) -> None:
    schema = await registry.create(conn, _custom(), "user")
    key = await learned_site(conn, schema, ["active"])
    before = await _state(conn, key)

    assert await _edit(conn, schema, []) == schema

    assert await _statuses(conn, key) == ["active"]
    assert await _state(conn, key) == before


async def test_an_edit_leaves_other_schemas_configs_alone(conn: AsyncConnection) -> None:
    edited, other = [await registry.create(conn, _custom(name), "user") for name in ("event_detail", "talk_detail")]
    kept = await learned_site(conn, other, ["active"])
    before = await _state(conn, kept)

    await _edit(conn, edited, [["title"]])

    assert await _statuses(conn, kept) == ["active"]
    assert await _state(conn, kept) == before


_groups = st.lists(st.lists(st.sampled_from(["title", "starts"]), min_size=1, max_size=2, unique=True), max_size=2)


async def _edit_in_place(database_url: str, groups: list[list[str]]) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            schema = await registry.create(conn, _custom(f"synthetic_{uuid.uuid4().hex[:12]}"), "user")
            key = await learned_site(conn, schema, ["active"])

            edited = await _edit(conn, schema, groups)

            changed = groups != schema.required_groups
            assert (edited.id, edited.name, edited.required_groups) == (schema.id, schema.name, groups)
            assert await registry.list_schemas(conn, name=schema.name) == [edited]
            assert await _statuses(conn, key) == ["suspended" if changed else "active"]
            assert (await _state(conn, key))[0] == ("cold" if changed else "active")
            await conn.rollback()
    finally:
        await engine.dispose()


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(groups=_groups)
def test_any_edit_keeps_one_row_and_sends_only_a_changed_schema_back_to_learning(
    database_url: str, groups: list[list[str]]
) -> None:
    asyncio.run(_edit_in_place(database_url, groups))


def test_the_sync_command_upserts_the_presets(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    try:
        main(["schemas", "sync"])
        first = capsys.readouterr().out
        main(["schemas", "sync"])
        second = capsys.readouterr().out
    finally:
        asyncio.run(_delete_presets(database_url))

    assert first.splitlines() == [f"wrote preset {p.name}" for p in load_presets()] + [
        "4 preset(s) inserted or updated"
    ]
    assert second == "0 preset(s) inserted or updated\n"


async def _delete_presets(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(delete(SchemaRow).where(SchemaRow.origin == "preset"))
    await engine.dispose()
