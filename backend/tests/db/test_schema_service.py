"""The schemas service (SPEC-07 §4.6, §4.7), without HTTP: callers create user schemas at version 1, an edit adds a
version on top of the latest one, a delete retires one version, and presets change only through their files."""

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.schemas import registry
from crawlerai.services import schemas
from crawlerai.services.schemas import InvalidSchema, NewSchema, SchemaConflict, SchemaContent

pytestmark = pytest.mark.anyio

TITLE = {"type": "text", "required": True, "description": "Name of the event"}


def _new(name: str = "event_detail", **content: object) -> NewSchema:
    return NewSchema.model_validate({"name": name, "page_kind": "detail", "fields": {"title": TITLE}, **content})


def _content(**content: object) -> SchemaContent:
    return SchemaContent.model_validate({"page_kind": "detail", "fields": {"title": TITLE}, **content})


async def test_create_refuses_a_preset_name_even_before_the_presets_are_synced(conn: AsyncConnection) -> None:
    preset_name = _new(registry.load_presets()[0].name)

    with pytest.raises(SchemaConflict, match="preset"):
        await schemas.create(conn, preset_name)
    assert await registry.list_schemas(conn, name=preset_name.name) == []


async def test_update_replaces_the_whole_content(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new(required_groups=[["title"]]))

    second = await schemas.update(conn, first.id, _content())

    assert second.required_groups == []


async def test_update_of_a_retired_version_is_refused(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())
    await schemas.retire(conn, first.id)
    edit = _content()

    with pytest.raises(SchemaConflict, match="retired"):
        await schemas.update(conn, first.id, edit)


async def test_update_reports_a_broken_result_with_its_field(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())
    row_scope_only = _content(fields={"title": {**TITLE, "scope": "page"}})

    with pytest.raises(InvalidSchema) as refused:
        await schemas.update(conn, first.id, row_scope_only)

    [(field, reason)] = refused.value.errors
    assert field == ""
    assert "title: a detail page has one entity, so every field is `row`" in reason
    assert await schemas.list_all(conn, name="event_detail") == [first]


async def test_presets_are_neither_edited_nor_retired(conn: AsyncConnection) -> None:
    [preset, *_] = await registry.sync_presets(conn)
    edit = _content()

    with pytest.raises(SchemaConflict, match="preset"):
        await schemas.update(conn, preset.id, edit)
    with pytest.raises(SchemaConflict, match="preset"):
        await schemas.retire(conn, preset.id)
    assert await schemas.list_all(conn, name=preset.name) == [preset]


async def test_retire_marks_one_version_and_is_repeatable(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())
    second = await schemas.update(conn, first.id, _content())

    retired = await schemas.retire(conn, first.id)
    again = await schemas.retire(conn, first.id)

    assert retired == again == first.model_copy(update={"status": "retired"})
    assert await schemas.list_all(conn, name="event_detail", status="active") == [second]
    assert await schemas.list_all(conn, name="event_detail", status="retired") == [retired]
