"""The schema registry against Postgres (SPEC-04 §4.1, §4.2): presets synced, rows immutable per version."""

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.cli import main
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.schemas import registry
from crawlerai.schemas.registry import PresetConflict, load_presets
from crawlerai.schemas.types import SchemaDocument

pytestmark = pytest.mark.anyio

PRESETS = ["commerce_detail", "commerce_listing", "job_detail", "job_listing"]


def _custom(name: str = "event_detail") -> SchemaDocument:
    return SchemaDocument.model_validate(
        {
            "name": name,
            "version": 1,
            "page_kind": "detail",
            "fields": {
                "title": {"type": "text", "required": True, "description": "Name of the event"},
                "starts": {"type": "datetime", "description": "When the event starts"},
            },
        }
    )


async def test_synced_presets_read_back_as_written_with_every_field_described(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)

    for preset in load_presets():
        stored = await registry.get(conn, preset.name, preset.version)
        assert SchemaDocument.model_validate(stored.model_dump(include=set(SchemaDocument.model_fields))) == preset
        assert all(spec.description for spec in stored.fields.values())


async def test_a_changed_preset_without_a_version_bump_is_refused(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)
    preset = load_presets()[0]
    changed = preset.model_copy(update={"required_groups": []})
    bumped = changed.model_copy(update={"version": preset.version + 1})
    new_preset = _custom("event_listing")

    with pytest.raises(PresetConflict, match="bump"):
        await registry.sync_presets(conn, [new_preset, changed])
    assert [s.name for s in await registry.list_schemas(conn)] == PRESETS  # nothing inserted
    assert [(s.name, s.version) for s in await registry.sync_presets(conn, [bumped])] == [
        (preset.name, preset.version + 1)
    ]


async def test_a_preset_older_than_a_stored_preset_version_is_refused(conn: AsyncConnection) -> None:
    await registry.sync_presets(conn)
    preset = load_presets()[0]
    newer = preset.version + 1
    await registry.sync_presets(conn, [preset.model_copy(update={"version": newer, "required_groups": []})])

    with pytest.raises(PresetConflict, match=f"version {newer} is stored"):
        await registry.sync_presets(conn, [preset])


async def test_a_preset_version_taken_by_a_user_schema_is_refused(conn: AsyncConnection) -> None:
    await registry.create(conn, _custom(), "user")

    presets = [_custom()]
    with pytest.raises(PresetConflict, match="event_detail version 1"):
        await registry.sync_presets(conn, presets)


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

    assert first.splitlines() == [f"inserted preset {p.name} version {p.version}" for p in load_presets()] + [
        "4 preset version(s) inserted"
    ]
    assert second == "0 preset version(s) inserted\n"


async def _delete_presets(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(delete(SchemaRow).where(SchemaRow.origin == "preset"))
    await engine.dispose()
