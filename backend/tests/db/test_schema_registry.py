"""The schema registry against Postgres (SPEC-04 §4.1, §4.2): presets synced, rows immutable per version."""

import asyncio
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.cli import main
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.db.models import SchemaId
from crawlerai.schemas import registry
from crawlerai.schemas.registry import PresetConflict, SchemaExists, SchemaNotFound, load_presets
from crawlerai.schemas.types import FieldSpec, SchemaChanges, SchemaDocument

pytestmark = pytest.mark.anyio

PRESETS = ["commerce_detail", "commerce_listing", "job_detail", "job_listing"]


def _custom(name: str = "event_detail", version: int = 1) -> SchemaDocument:
    return SchemaDocument.model_validate(
        {
            "name": name,
            "version": version,
            "page_kind": "detail",
            "fields": {
                "title": {"type": "text", "required": True, "description": "Name of the event"},
                "starts": {"type": "datetime", "description": "When the event starts"},
            },
        }
    )


async def test_sync_inserts_the_presets_once(conn: AsyncConnection) -> None:
    inserted = await registry.sync_presets(conn)
    again = await registry.sync_presets(conn)

    assert [(s.name, s.version, s.origin, s.status) for s in inserted] == [(n, 1, "preset", "active") for n in PRESETS]
    assert again == []


async def test_synced_presets_read_back_as_written_with_every_field_described(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)

    for preset in load_presets():
        stored = await registry.get(conn, preset.name, 1)
        assert SchemaDocument.model_validate(stored.model_dump(include=set(SchemaDocument.model_fields))) == preset
        assert all(spec.description for spec in stored.fields.values())


async def test_a_changed_preset_without_a_version_bump_is_refused(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)
    preset = load_presets()[0]
    changed = preset.model_copy(update={"required_groups": []})
    bumped = changed.model_copy(update={"version": 2})
    new_preset = _custom("event_listing")

    with pytest.raises(PresetConflict, match="bump"):
        await registry.sync_presets(conn, [new_preset, changed])
    assert [s.name for s in await registry.list_schemas(conn)] == PRESETS  # nothing inserted
    assert [(s.name, s.version) for s in await registry.sync_presets(conn, [bumped])] == [(preset.name, 2)]


async def test_a_preset_older_than_a_stored_preset_version_is_refused(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)
    preset = load_presets()[0]
    await registry.sync_presets(conn, [preset.model_copy(update={"version": 2, "required_groups": []})])

    with pytest.raises(PresetConflict, match="version 2 is stored"):
        await registry.sync_presets(conn, [preset])


async def test_a_preset_version_taken_by_a_user_schema_is_refused(conn: AsyncConnection) -> None:
    await registry.create(conn, _custom(), "user")

    presets = [_custom()]
    with pytest.raises(PresetConflict, match="event_detail version 1"):
        await registry.sync_presets(conn, presets)


async def test_create_starts_a_name_at_version_1_once(conn: AsyncConnection) -> None:
    created = await registry.create(conn, _custom(), "user")
    second_version = _custom(version=2)

    assert (created.version, created.origin, created.status) == (1, "user", "active")
    assert await registry.get_by_id(conn, created.id) == created
    again = _custom()
    with pytest.raises(SchemaExists):
        await registry.create(conn, again, "prompt_draft")
    with pytest.raises(ValueError, match="starts at version 1"):
        await registry.create(conn, second_version, "user")


async def test_new_version_applies_changes_and_leaves_the_old_version(conn: AsyncConnection) -> None:
    first = await registry.create(conn, _custom(), "user")
    fields = {**first.fields, "url": FieldSpec.model_validate({"type": "url", "description": "Event page URL"})}
    changes = SchemaChanges(fields=fields, required_groups=[["url", "title"]])

    second = await registry.new_version(conn, "event_detail", changes, "user")

    assert (second.version, second.page_kind, sorted(second.fields)) == (2, "detail", ["starts", "title", "url"])
    assert second.required_groups == [["url", "title"]]
    assert second.id != first.id
    assert await registry.get(conn, "event_detail", 1) == first
    assert [s.version for s in await registry.list_schemas(conn) if s.name == "event_detail"] == [1, 2]


async def test_new_version_validates_the_whole_result(conn: AsyncConnection) -> None:
    await registry.create(conn, _custom(), "user")
    dangling_group = SchemaChanges(required_groups=[["sku"]])

    with pytest.raises(ValidationError, match="unknown fields"):
        await registry.new_version(conn, "event_detail", dangling_group, "user")


async def test_missing_schemas_raise_not_found(conn: AsyncConnection) -> None:
    missing_id = SchemaId(uuid.uuid4())

    with pytest.raises(SchemaNotFound):
        await registry.get(conn, "event_detail", 1)
    with pytest.raises(SchemaNotFound):
        await registry.get_by_id(conn, missing_id)
    no_changes = SchemaChanges()
    with pytest.raises(SchemaNotFound):
        await registry.new_version(conn, "event_detail", no_changes, "user")


async def test_list_filters_by_status(conn: AsyncConnection) -> None:
    created = await registry.create(conn, _custom(), "user")
    await conn.execute(update(SchemaRow).where(SchemaRow.id == created.id).values(status="retired"))
    await registry.create(conn, _custom("event_listing"), "user")

    assert [s.name for s in await registry.list_schemas(conn, status="active")] == ["event_listing"]
    assert [s.name for s in await registry.list_schemas(conn, status="retired")] == ["event_detail"]


def test_the_sync_command_inserts_the_presets(
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

    assert first.splitlines() == [f"inserted preset {n} version 1" for n in PRESETS] + ["4 preset version(s) inserted"]
    assert second == "0 preset version(s) inserted\n"


async def _delete_presets(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(delete(SchemaRow).where(SchemaRow.origin == "preset"))
    await engine.dispose()
