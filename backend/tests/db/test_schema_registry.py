"""The schema registry against Postgres (schemas spec): presets synced, and one row per name edited in place,
the edit sending the schema's configs back to learning (`services.schemas`, `progressive.relearn_schema`)."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.config_ir.progressive import StateKey
from crawlerai.db.models import ExtractionConfig, ProgressiveState
from crawlerai.schemas import registry
from crawlerai.schemas.registry import PresetConflict, load_presets
from crawlerai.schemas.types import SchemaChanges, SchemaContent, SchemaDef, SchemaDocument, document_digest
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


async def test_the_price_role_predicates_edit_the_commerce_preset_in_place_without_changing_what_it_requires(
    conn: AsyncConnection,
) -> None:
    # Schemas spec, "Presets": only the price path gains its predicates (struck, member and unit prices left out).
    current = next(p for p in load_presets() if p.name == "commerce_detail")
    plain = current.fields["price"].model_copy(update={"schema_org": "Offer.price+priceCurrency"})
    before = current.model_copy(update={"fields": {**current.fields, "price": plain}})
    [stored] = await registry.sync_presets(conn, [before])

    [edited] = await registry.sync_presets(conn, [current])

    assert edited.id == stored.id
    assert document_digest(edited) != document_digest(stored)
    assert edited.model_copy(update={"fields": {**edited.fields, "price": plain}}) == stored
    assert [n for n, s in edited.fields.items() if s.required] == [n for n, s in stored.fields.items() if s.required]


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


async def test_the_fields_keep_the_order_the_document_gave_them_when_stored_and_edited(conn: AsyncConnection) -> None:
    # JSONB orders keys by length, then bytes: this document's order is not the one it would come back in.
    names = ["starts", "title", "sku", "an_extra_long_name"]
    spec = {"type": "text", "description": "A field"}
    document = SchemaDocument.model_validate(
        {"name": "ordered_detail", "page_kind": "detail", "fields": dict.fromkeys(names, spec)}
    )

    created = await registry.create(conn, document, "user")
    read_back = await registry.get(conn, "ordered_detail")
    reordered = SchemaDocument.model_validate({**document.model_dump(), "fields": dict.fromkeys(reversed(names), spec)})
    edited = await registry.update_schema(conn, read_back, SchemaChanges(fields=reordered.fields))

    assert list(created.fields) == list(read_back.fields) == read_back.field_order == names
    assert list(edited.fields) == edited.field_order == list(reversed(names))
