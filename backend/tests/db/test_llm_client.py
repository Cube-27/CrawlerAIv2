"""The LLM client's budget and usage (llm spec, INV-23): every call is checked against the job's `llm_calls`
budget first and writes its usage afterwards, in a transaction of its own, so a task that then fails keeps it."""

from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.db.models import Job, JobId, Project, UsageEvent
from crawlerai.llm.client import (
    BudgetExhausted,
    LLMRequest,
    MeteredClient,
    ProviderReply,
    request_hash,
)
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"n": {"type": "integer"}},
    "required": ["n"],
    "additionalProperties": False,
}


def request(job_id: JobId) -> LLMRequest:
    return LLMRequest(
        prompt_kind="c_extract_detail",
        model_class="fast",
        system="system prompt",
        user="user prompt",
        output_schema=SCHEMA,
        max_output_tokens=64,
        job_id=job_id,
    )


def reply(text: str, tokens_in: int, tokens_out: int) -> ProviderReply:
    return ProviderReply(model="fake-model", text=text, tokens_in=tokens_in, tokens_out=tokens_out)


async def _job(engine: AsyncEngine, budget: dict[str, int] | None = None) -> JobId:
    default_project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {
        "project_id": default_project,
        "kind": "scrape",
        "request": {"budget": budget} if budget is not None else {},
        "engine_version": "0+cal.0",
    }
    async with engine.begin() as conn:
        job_id: JobId = (await conn.execute(insert(Job).values(**values).returning(Job.id))).scalar_one()
    return job_id


async def _events(engine: AsyncEngine, job_id: JobId) -> list[tuple[Any, ...]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(
                UsageEvent.resource,
                UsageEvent.provider,
                UsageEvent.model_or_pool,
                UsageEvent.quantity,
                UsageEvent.metadata_,
            )
            .where(UsageEvent.job_id == job_id)
            .order_by(UsageEvent.id)
        )
        return [tuple(row) for row in rows]


async def _usage(engine: AsyncEngine, job_id: JobId) -> dict[str, int]:
    async with engine.connect() as conn:
        usage: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == job_id))).scalar_one()
        return usage


async def test_a_call_writes_its_usage_events_and_counters(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    client = MeteredClient([FakeProvider([reply('{"n": 1}', tokens_in=120, tokens_out=7)])], engine)

    response = await client.complete_json(request(job_id))

    metadata = {
        "prompt_kind": "c_extract_detail",
        "model": "fake-model",
        "request_hash": request_hash(request(job_id)),
        "latency_ms": response.latency_ms,
        # The call's prompt length, which a price tiered by prompt length needs for the output tokens too (§4.8).
        "tokens_in": 120,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    assert await _events(engine, job_id) == [
        ("llm_calls", "fake", "fake-model", 1, metadata),
        ("llm_tokens_in", "fake", "fake-model", 120, metadata),
        ("llm_tokens_out", "fake", "fake-model", 7, metadata),
    ]
    assert await _usage(engine, job_id) == {"llm_calls": 1, "llm_tokens_in": 120, "llm_tokens_out": 7}


async def test_an_exhausted_budget_raises_before_the_provider_is_called(engine: AsyncEngine) -> None:
    job_id = await _job(engine, {"llm_calls": 0})
    provider = FakeProvider([reply('{"n": 1}', 1, 1)])
    call = MeteredClient([provider], engine).complete_json(request(job_id))

    with pytest.raises(BudgetExhausted):
        await call

    assert provider.calls == []
    assert await _events(engine, job_id) == []
