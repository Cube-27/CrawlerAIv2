"""The LLM client's budget and usage (SPEC-06 §4.2, INV-23): every call is checked against the job's `llm_calls`
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
    OutputInvalid,
    ProviderError,
    ProviderReply,
    ProviderUnavailable,
    request_hash,
)
from crawlerai.llm.providers.fake import FakeProvider

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


async def test_cache_tokens_are_recorded_in_the_calls_metadata_and_its_prompt_length(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    answer = ProviderReply(
        model="fake-model", text='{"n": 1}', tokens_in=20, tokens_out=7, cache_read_tokens=300, cache_write_tokens=50
    )
    client = MeteredClient([FakeProvider([answer])], engine)

    response = await client.complete_json(request(job_id))

    assert (response.cache_read_tokens, response.cache_write_tokens) == (300, 50)
    assert [(c.tokens_in, c.cache_read_tokens, c.cache_write_tokens) for c in response.answered] == [(20, 300, 50)]
    rows = await _events(engine, job_id)
    assert {resource: quantity for resource, _, _, quantity, _ in rows} == {
        "llm_calls": 1,
        "llm_tokens_in": 20,
        "llm_tokens_out": 7,
    }
    for *_, metadata in rows:
        assert (metadata["tokens_in"], metadata["cache_read_tokens"], metadata["cache_write_tokens"]) == (370, 300, 50)


async def test_a_retry_is_a_second_call(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    provider = FakeProvider([reply("not json", 100, 2), reply('{"n": 1}', 110, 3)])

    await MeteredClient([provider], engine).complete_json(request(job_id))

    assert await _usage(engine, job_id) == {"llm_calls": 2, "llm_tokens_in": 210, "llm_tokens_out": 5}


async def test_an_exhausted_budget_raises_before_the_provider_is_called(engine: AsyncEngine) -> None:
    job_id = await _job(engine, {"llm_calls": 0})
    provider = FakeProvider([reply('{"n": 1}', 1, 1)])
    call = MeteredClient([provider], engine).complete_json(request(job_id))

    with pytest.raises(BudgetExhausted):
        await call

    assert provider.calls == []
    assert await _events(engine, job_id) == []


async def test_the_budget_is_checked_again_before_the_retry(engine: AsyncEngine) -> None:
    job_id = await _job(engine, {"llm_calls": 1})
    provider = FakeProvider([reply("not json", 5, 1), reply('{"n": 1}', 5, 1)])
    call = MeteredClient([provider], engine).complete_json(request(job_id))

    with pytest.raises(BudgetExhausted):
        await call

    assert len(provider.calls) == 1
    assert await _usage(engine, job_id) == {"llm_calls": 1, "llm_tokens_in": 5, "llm_tokens_out": 1}


async def test_calls_proceed_while_the_budget_lasts(engine: AsyncEngine) -> None:
    job_id = await _job(engine, {"llm_calls": 2})
    client = MeteredClient([FakeProvider([reply('{"n": 1}', 1, 1), reply('{"n": 2}', 1, 1)])], engine)

    assert [(await client.complete_json(request(job_id))).data for _ in range(2)] == [{"n": 1}, {"n": 2}]
    third = client.complete_json(request(job_id))
    with pytest.raises(BudgetExhausted):
        await third


async def test_usage_survives_a_task_transaction_that_rolls_back(engine: AsyncEngine) -> None:
    # The note from SPEC-01 PR 7 (D-0151): a handler that raises rolls back its task's transaction. Usage committed
    # by the client on its own connection stays, so the budget still counts the calls the failed task made.
    job_id = await _job(engine)
    client = MeteredClient([FakeProvider([reply("not json", 9, 1), reply("still not json", 9, 1)])], engine)

    async with engine.connect() as conn:
        task = await conn.begin()
        call = client.complete_json(request(job_id))
        with pytest.raises(OutputInvalid):
            await call
        await task.rollback()

    assert await _usage(engine, job_id) == {"llm_calls": 2, "llm_tokens_in": 18, "llm_tokens_out": 2}


async def test_a_failed_provider_call_records_no_usage(engine: AsyncEngine) -> None:
    # No reply means no tokens and nothing charged; the job's budget is for calls that answered.
    job_id = await _job(engine)
    call = MeteredClient([FakeProvider([ProviderError("timeout")])], engine).complete_json(request(job_id))

    with pytest.raises(ProviderUnavailable, match="timeout"):
        await call

    assert await _events(engine, job_id) == []


async def test_a_failover_charges_only_the_provider_that_answered(engine: AsyncEngine) -> None:
    job_id = await _job(engine)
    down = FakeProvider([ProviderError("429")], name="first")
    up = FakeProvider([reply('{"n": 1}', 30, 2)], name="second")

    await MeteredClient([down, up], engine).complete_json(request(job_id))

    assert [(resource, provider) for resource, provider, *_ in await _events(engine, job_id)] == [
        ("llm_calls", "second"),
        ("llm_tokens_in", "second"),
        ("llm_tokens_out", "second"),
    ]
    assert await _usage(engine, job_id) == {"llm_calls": 1, "llm_tokens_in": 30, "llm_tokens_out": 2}
