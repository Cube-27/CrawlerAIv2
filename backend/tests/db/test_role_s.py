"""Role S against Postgres (SPEC-06 §4.5, §7): a prompt's draft is stored once as `prompt_draft`, a repeat of the
prompt reuses it without a call, and an invalid document is retried once, then refused."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import Job, JobId, Project, UsageEvent
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.llm.client import MeteredClient, OutputInvalid, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.llm.roles.s_schema import draft_name, draft_schema
from crawlerai.llm.roles.s_wire import to_wire

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


@pytest.fixture
async def drafts(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The engine; the draft schemas the test stored are deleted afterwards."""
    yield engine
    async with engine.begin() as conn:
        await conn.execute(delete(SchemaRow).where(SchemaRow.origin == "prompt_draft"))


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


async def test_a_draft_is_stored_as_version_1_of_the_prompt_name(drafts: AsyncEngine) -> None:
    job_id, prompt = await _job(drafts), _prompt()
    provider = FakeProvider([reply(DRAFT)])

    schema = await draft_schema(
        drafts, MeteredClient([provider], drafts), prompt=prompt, samples=["Spring fair, 2 May"], job_id=job_id
    )

    assert (schema.name, schema.origin, schema.status) == (
        draft_name(prompt),
        "prompt_draft",
        "active",
    )
    assert schema.model_dump(include={"page_kind", "fields"}, exclude_none=True, exclude_defaults=True) == DRAFT
    async with drafts.connect() as conn:
        kinds = select(UsageEvent.metadata_["prompt_kind"].astext).where(UsageEvent.job_id == job_id)
        assert set((await conn.execute(kinds)).scalars()) == {"s_draft"}


async def test_a_prompt_submitted_twice_yields_one_row_and_one_call(drafts: AsyncEngine) -> None:
    job_id, prompt = await _job(drafts), _prompt()
    provider = FakeProvider([reply(DRAFT)])
    client = MeteredClient([provider], drafts)

    first = await draft_schema(drafts, client, prompt=prompt, samples=["page one"], job_id=job_id)
    second = await draft_schema(drafts, client, prompt=f"  {prompt}\n", samples=["another page"], job_id=job_id)

    assert second == first
    assert len(provider.calls) == 1
    assert await _rows(drafts, draft_name(prompt)) == 1


async def test_concurrent_drafts_of_one_prompt_return_one_row(drafts: AsyncEngine) -> None:
    job_id, prompt = await _job(drafts), _prompt()
    clients = [MeteredClient([FakeProvider([reply(DRAFT)])], drafts) for _ in range(2)]

    schemas = await asyncio.gather(
        *(draft_schema(drafts, c, prompt=prompt, samples=["page"], job_id=job_id) for c in clients)
    )

    assert schemas[0] == schemas[1]
    assert await _rows(drafts, draft_name(prompt)) == 1


async def test_an_invalid_document_is_retried_once_with_the_error(drafts: AsyncEngine) -> None:
    job_id, prompt = await _job(drafts), _prompt()
    provider = FakeProvider([reply(UNDESCRIBED), reply(DRAFT)])

    schema = await draft_schema(
        drafts, MeteredClient([provider], drafts), prompt=prompt, samples=["page"], job_id=job_id
    )

    assert set(schema.fields) == {"title", "starts"}
    assert len(provider.calls) == 2
    assert "rejected: at root: Value error, title: every field needs a description" in provider.calls[1].user


async def test_a_document_invalid_twice_is_refused_and_not_stored(drafts: AsyncEngine) -> None:
    job_id, prompt = await _job(drafts), _prompt()
    client = MeteredClient([FakeProvider([reply(UNDESCRIBED), reply(UNDESCRIBED)])], drafts)

    with pytest.raises(OutputInvalid, match="every field needs a description"):
        await draft_schema(drafts, client, prompt=prompt, samples=["page"], job_id=job_id)

    assert await _rows(drafts, draft_name(prompt)) == 0
