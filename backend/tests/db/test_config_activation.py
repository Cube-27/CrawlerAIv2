"""Activation: a validated config is stored active as the next version, the previous active
config is suspended, and the learning run ends with the state `active` on it; nothing activates without validation."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.activation import activate
from crawlerai.config_ir.executor import ConfigMismatch
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import StateKey, request_learning
from crawlerai.config_ir.validation import Facts, HeldOutPage, Validated, validate
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import CaptureId, ExtractionConfig, ProgressiveState, Project, SchemaDef, Site
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef as SchemaDefinition
from crawlerai.schemas.types import SchemaDocument, document_digest

pytestmark = pytest.mark.anyio

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
FIELDS = {"title": {"type": "text", "description": "d"}}


def _digest(name: str) -> str:
    document = SchemaDocument.model_validate({"name": name, "page_kind": "detail", "fields": FIELDS})
    return document_digest(document)


async def _key(conn: AsyncConnection) -> tuple[StateKey, str, str]:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id = (await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))).scalar_one()
    name = f"s_{uuid.uuid4().hex[:12]}"
    values = {"name": name, "page_kind": "detail", "fields": FIELDS, "origin": "user", "status": "active"}
    schema_id = (await conn.execute(insert(SchemaDef).values(**values).returning(SchemaDef.id))).scalar_one()
    return StateKey(site_id=site_id, schema_id=schema_id, page_kind="detail"), host, name


def _validated(host: str, name: str, *, pages: int = 3) -> Validated:
    ir = ExtractionConfigIR.model_validate(
        {
            "ir_version": "1",
            "site": host,
            "schema": {"name": name, "digest": _digest(name)},
            "page_kind": "detail",
            "fetch": {"method": "http"},
            "fields": {"title": {"steps": [{"xpath": "normalize-space(//h1)"}], "status": "uncorroborated"}},
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "test",
            },
        }
    )
    schema = SchemaDefinition.model_validate(
        {"id": uuid7(), "origin": "user", "status": "active", "name": name, "page_kind": "detail"} | {"fields": FIELDS}
    )
    held_out = [
        HeldOutPage(CaptureId(uuid7()), ParsedPage(f"<h1>Item {n}</h1>"), CTX, Facts(published={"title": f"Item {n}"}))
        for n in range(pages)
    ]
    return validate(ir, schema, held_out, VOCABULARY)


async def _configs(conn: AsyncConnection, key: StateKey) -> list[Any]:
    rows = select(ExtractionConfig).where(ExtractionConfig.site_id == key.site_id).order_by(ExtractionConfig.version)
    return list((await conn.execute(rows)).all())


async def _state(conn: AsyncConnection, key: StateKey) -> Any:
    return (await conn.execute(select(ProgressiveState).where(*key.where()))).one()


async def test_a_validated_config_activates_and_the_state_becomes_active(conn: AsyncConnection) -> None:
    key, host, name = await _key(conn)
    await request_learning(conn, key)
    validated = _validated(host, name)

    config_id = await activate(conn, key, validated)

    [config] = await _configs(conn, key)
    assert (config.id, config.version, config.status, config.origin) == (config_id, 1, "active", "induced")
    assert config.field_status == {"title": "uncorroborated"}
    assert config.validation_report == validated.report.model_dump(mode="json", by_alias=True)
    assert validated.ir is not None
    assert config.ir == validated.ir.model_dump(mode="json", by_alias=True)
    state = await _state(conn, key)
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("active", config_id, None)


async def test_a_new_activation_suspends_the_previous_config(conn: AsyncConnection) -> None:
    key, host, name = await _key(conn)
    await request_learning(conn, key)
    first = await activate(conn, key, _validated(host, name))
    await request_learning(conn, key, force=True)

    second = await activate(conn, key, _validated(host, name))

    configs = await _configs(conn, key)
    assert [(c.id, c.version, c.status) for c in configs] == [(first, 1, "suspended"), (second, 2, "active")]
    assert (await _state(conn, key)).active_config_id == second


@pytest.mark.parametrize("other", ["site", "schema"])
async def test_a_config_learned_for_another_key_is_refused(conn: AsyncConnection, other: str) -> None:
    key, host, name = await _key(conn)
    await request_learning(conn, key)
    validated = _validated("other.example.test", name) if other == "site" else _validated(host, "other_schema")

    with pytest.raises(ConfigMismatch):
        await activate(conn, key, validated)

    assert await _configs(conn, key) == []
