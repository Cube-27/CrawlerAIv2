"""Role S against Postgres (llm spec): a prompt's draft is stored once as `prompt_draft`, a repeat of the
prompt reuses it without a call, and an invalid document is retried once, then refused. A schema's label synonyms are
drafted off the request path, once, and stored with it."""

import asyncio
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import Job, JobId, Project, UsageEvent
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.llm.client import (
    NO_LLM,
    LLMRequest,
    LLMResponse,
    MeteredClient,
    OutputInvalid,
    ProviderReply,
    ReplyCheck,
)
from crawlerai.llm.roles.s_labels import draft_labels, with_labels
from crawlerai.llm.roles.s_schema import draft_name, draft_schema
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

DRAFT: dict[str, Any] = {
    "page_kind": "detail",
    "fields": {
        "title": {"type": "text", "required": True, "description": "Name of the event"},
        "starts": {"type": "datetime", "description": "When the event starts"},
    },
}
# Valid JSON for the output schema, but a field without a description, which only `SchemaDocument` refuses.
UNDESCRIBED: dict[str, Any] = {"page_kind": "detail", "fields": {"title": {"type": "text"}}}


def reply(document: dict[str, Any]) -> ProviderReply:
    return ProviderReply(model="fake-strong", text=json.dumps(to_wire(document)), tokens_in=900, tokens_out=80)


async def _job(engine: AsyncEngine) -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": default_project, "kind": "scrape", "request": {}, "engine_version": "0+cal.0"}
    async with engine.begin() as conn:
        job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    return job_id


async def _rows(engine: AsyncEngine, name: str) -> int:
    async with engine.connect() as conn:
        count: int = (
            await conn.execute(select(func.count()).select_from(SchemaRow).where(SchemaRow.name == name))
        ).scalar_one()
    return count


def _prompt() -> str:
    return f"Event names and start times {uuid.uuid4()}"


async def test_a_draft_is_stored_as_version_1_of_the_prompt_name(engine: AsyncEngine) -> None:
    job_id, prompt = await _job(engine), _prompt()
    provider = FakeProvider([reply(DRAFT)])

    schema = await draft_schema(
        engine, MeteredClient([provider], engine), prompt=prompt, samples=["Spring fair, 2 May"], job_id=job_id
    )

    assert (schema.name, schema.origin, schema.status) == (
        draft_name(prompt),
        "prompt_draft",
        "active",
    )
    assert schema.model_dump(include={"page_kind", "fields"}, exclude_none=True, exclude_defaults=True) == DRAFT
    async with engine.connect() as conn:
        kinds = select(UsageEvent.metadata_["prompt_kind"].astext).where(UsageEvent.job_id == job_id)
        assert set((await conn.execute(kinds)).scalars()) == {"s_draft"}


async def test_a_prompt_submitted_twice_yields_one_row_and_one_call(engine: AsyncEngine) -> None:
    job_id, prompt = await _job(engine), _prompt()
    provider = FakeProvider([reply(DRAFT)])
    client = MeteredClient([provider], engine)

    first = await draft_schema(engine, client, prompt=prompt, samples=["page one"], job_id=job_id)
    second = await draft_schema(engine, client, prompt=f"  {prompt}\n", samples=["another page"], job_id=job_id)

    assert second == first
    assert len(provider.calls) == 1
    assert await _rows(engine, draft_name(prompt)) == 1


async def test_concurrent_drafts_of_one_prompt_return_one_row(engine: AsyncEngine) -> None:
    job_id, prompt = await _job(engine), _prompt()
    clients = [MeteredClient([FakeProvider([reply(DRAFT)])], engine) for _ in range(2)]

    schemas = await asyncio.gather(
        *(draft_schema(engine, c, prompt=prompt, samples=["page"], job_id=job_id) for c in clients)
    )

    assert schemas[0] == schemas[1]
    assert await _rows(engine, draft_name(prompt)) == 1


async def test_an_invalid_document_is_retried_once_with_the_error(engine: AsyncEngine) -> None:
    job_id, prompt = await _job(engine), _prompt()
    provider = FakeProvider([reply(UNDESCRIBED), reply(DRAFT)])

    schema = await draft_schema(
        engine, MeteredClient([provider], engine), prompt=prompt, samples=["page"], job_id=job_id
    )

    assert set(schema.fields) == {"title", "starts"}
    assert len(provider.calls) == 2
    assert "rejected: at root: Value error, title: every field needs a description" in provider.calls[1].user


async def test_a_document_invalid_twice_is_refused_and_not_stored(engine: AsyncEngine) -> None:
    job_id, prompt = await _job(engine), _prompt()
    client = MeteredClient([FakeProvider([reply(UNDESCRIBED), reply(UNDESCRIBED)])], engine)

    with pytest.raises(OutputInvalid, match="every field needs a description"):
        await draft_schema(engine, client, prompt=prompt, samples=["page"], job_id=job_id)

    assert await _rows(engine, draft_name(prompt)) == 0


async def _stored_draft(engine: AsyncEngine) -> SchemaDef:
    document = SchemaDocument.model_validate({**DRAFT, "name": f"draft_{uuid.uuid4().hex[:12]}"})
    async with engine.begin() as conn:
        return await registry.create(conn, document, "prompt_draft")


def _labels_reply(labels: dict[str, list[str]]) -> ProviderReply:
    fields = [{"name": name, "labels": given} for name, given in labels.items()]
    return ProviderReply(model="fake-strong", text=json.dumps({"fields": fields}), tokens_in=300, tokens_out=40)


async def test_label_synonyms_are_drafted_once_stored_with_the_schema_and_cleared_by_an_edit(
    engine: AsyncEngine,
) -> None:
    schema = await _stored_draft(engine)
    labels = {"title": ["Event", "Veranstaltung", "event", "Title"], "starts": ["Begins", "Beginn"]}
    provider = FakeProvider([_labels_reply(labels)])
    client = MeteredClient([provider], engine)

    drafted = await draft_labels(engine, client, schema)
    assert drafted is not None
    again = with_labels(engine, client, drafted)

    # A label repeating another's words, or the field's own name, is dropped.
    assert drafted.labels == {"title": ["Event", "Veranstaltung"], "starts": ["Begins", "Beginn"]}
    assert again == drafted
    assert len(provider.calls) == 1
    async with engine.begin() as conn:
        edited = await registry.update_schema(conn, drafted, SchemaChanges(required_groups=[["starts"]]))
    assert edited.labels is None


class _Broken:
    """A client failing with an error that is no `LLMFailure`."""

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        raise RuntimeError("broken")


async def test_a_failed_draft_stores_nothing_and_fails_no_request(engine: AsyncEngine) -> None:
    schema = await _stored_draft(engine)

    assert with_labels(engine, _Broken(), schema) == schema
    assert await draft_labels(engine, _Broken(), schema) is None
    assert await draft_labels(engine, NO_LLM, schema) is None
    async with engine.connect() as conn:
        assert (await registry.get_by_id(conn, schema.id)).labels is None
