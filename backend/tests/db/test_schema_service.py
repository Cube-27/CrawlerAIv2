"""The schemas service (SPEC-07 §4.6, §4.7), without HTTP: callers create user schemas, an edit replaces a schema's
document in place, a delete retires it, and presets change only through their files."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaContent
from crawlerai.services import schemas
from crawlerai.services.schemas import InvalidSchema, NewSchema, SchemaConflict

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


async def test_two_first_uses_of_an_inline_schema_at_once_share_one_schema(
    engine: AsyncEngine, schema_name: str
) -> None:
    inline = _new(schema_name)
    async with engine.connect() as first, engine.connect() as second:
        created = await schemas.inline(first, inline)
        # The second insert waits on the first transaction's row of the same name.
        racing = asyncio.create_task(schemas.inline(second, inline))
        _, pending = await asyncio.wait({racing}, timeout=0.5)
        await first.commit()
        reused = await racing
        await second.commit()

    assert pending == {racing}
    assert reused == created


async def test_update_replaces_the_whole_content_in_place(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new(required_groups=[["title"]]))

    second = await schemas.update(conn, first.id, _content())

    assert second == first.model_copy(update={"required_groups": []})
    assert await schemas.list_all(conn, name="event_detail") == [second]


async def test_update_of_a_retired_schema_is_refused(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())
    retired = await schemas.retire(conn, first.id)
    edit = _content(required_groups=[["title"]])

    with pytest.raises(SchemaConflict, match="event_detail is retired"):
        await schemas.update(conn, first.id, edit)
    assert await schemas.list_all(conn, name="event_detail") == [retired]


async def test_update_reports_a_broken_result_with_its_field(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())
    row_scope_only = _content(fields={"title": {**TITLE, "scope": "page"}})

    with pytest.raises(InvalidSchema) as refused:
        await schemas.update(conn, first.id, row_scope_only)

    assert refused.value.errors == [("", "title: a detail page has one entity, so every field is `row` (§5.2)")]
    assert await schemas.list_all(conn, name="event_detail") == [first]


async def test_presets_are_neither_edited_nor_retired(conn: AsyncConnection) -> None:
    [preset, *_] = await registry.sync_presets(conn)
    edit = _content()

    with pytest.raises(SchemaConflict, match="preset"):
        await schemas.update(conn, preset.id, edit)
    with pytest.raises(SchemaConflict, match="preset"):
        await schemas.retire(conn, preset.id)
    assert await schemas.list_all(conn, name=preset.name) == [preset]


async def test_retire_marks_the_schema_and_is_repeatable(conn: AsyncConnection) -> None:
    first = await schemas.create(conn, _new())

    retired = await schemas.retire(conn, first.id)
    again = await schemas.retire(conn, first.id)

    assert retired == again == first.model_copy(update={"status": "retired"})
    assert await schemas.list_all(conn, name="event_detail", status="active") == []
    assert await schemas.list_all(conn, name="event_detail", status="retired") == [retired]
