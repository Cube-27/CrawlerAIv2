"""The LLM cost history (SPEC-06 §4.8, SPEC-10 §4.2): usage events of LLM calls priced by the price that applied to
each call, summed by day, by provider, model and prompt kind, and by job; through the service and then over HTTP
(`GET /v1/usage/llm`, `GET /v1/usage/llm/jobs`).

Calls are written as `usage_event` rows the way the LLM client writes them, with ids made at chosen times (an event's
time is its UUIDv7 id's, RFC 9562 §5.7), in 2031 so that no other test's events fall in the ranges asked for. Prices
are a synthetic list of made-up models; the HTTP tests run on the shipped prices, which list none of them.
"""

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.api.app import create_app
from crawlerai.core.ids import uuid7_floor
from crawlerai.db.models import ApiKey, Job, JobId, Project, UsageEvent, UsageResource
from crawlerai.llm.pricing import PriceList, Pricing
from crawlerai.services import jobs, llm_costs
from crawlerai.services.keys import create_key
from crawlerai.services.llm_costs import CostQuery

pytestmark = pytest.mark.anyio

PROVIDER = "fakeai"
JAN = date(2031, 1, 1)


def _day(n: int) -> datetime:
    """Noon UTC on 2031-01-`n`."""
    return datetime(2031, 1, n, 12, tzinfo=UTC)


def _row(model: str, **fields: Any) -> dict[str, Any]:
    return {
        "model": model,
        "effective_from": JAN.isoformat(),
        "effective_until": None,
        "min_prompt_tokens": 0,
        "max_prompt_tokens": None,
        "input_usd_per_mtok": "1",
        "output_usd_per_mtok": "2",
    } | fields


# `flat`: $1 in and $2 out per million tokens. `dated`: the same until 2031-01-10, then $3 and $6. `tiered`: the same
# for prompts of up to 1000 tokens, then $5 and $10.
PRICING = Pricing.of(
    [
        PriceList.model_validate(
            {
                "provider": PROVIDER,
                "currency": "USD",
                "checked": JAN.isoformat(),
                "scope": "synthetic",
                "prices": [
                    _row("flat"),
                    _row("dated", effective_until="2031-01-10"),
                    _row("dated", effective_from="2031-01-10", input_usd_per_mtok="3", output_usd_per_mtok="6"),
                    _row("tiered", max_prompt_tokens=1000),
                    _row("tiered", min_prompt_tokens=1001, input_usd_per_mtok="5", output_usd_per_mtok="10"),
                ],
            }
        )
    ]
)


def _usd(tokens_in: int, tokens_out: int, per_mtok_in: str = "1", per_mtok_out: str = "2") -> float:
    return float((tokens_in * Decimal(per_mtok_in) + tokens_out * Decimal(per_mtok_out)) / 1_000_000)


def _id_at(at: datetime) -> uuid.UUID:
    """A UUIDv7 made at `at`: its timestamp, version 7, the RFC 9562 variant and random bits."""
    random_bits = int.from_bytes(os.urandom(10)) & ((1 << 62) - 1)
    return uuid.UUID(
        int=uuid7_floor(at).int | 0x7 << 76 | (int.from_bytes(os.urandom(2)) & 0xFFF) << 64 | 0b10 << 62 | random_bits
    )


@dataclass
class World:
    engine: AsyncEngine

    async def job(self, kind: str = "batch_scrape") -> JobId:
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            values = {"kind": kind, "request": {}, "engine_version": "e", "status": "running"}
            job_id: JobId = (
                await conn.execute(insert(Job).values(project_id=project, **values).returning(Job.id))
            ).scalar_one()
        return job_id

    async def call(
        self,
        job_id: JobId,
        at: datetime,
        *,
        model: str = "flat",
        kind: str = "c_extract_detail",
        tokens_in: int = 1000,
        tokens_out: int = 100,
        tokens_in_recorded: bool = True,
    ) -> None:
        """One answered call as the client records it: `llm_calls`, `llm_tokens_in` and `llm_tokens_out` rows that
        share the call's metadata. `tokens_in_recorded=False` leaves the prompt length out, as rows written before it
        was recorded do."""
        metadata: dict[str, Any] = {"prompt_kind": kind, "model": model, "request_hash": "h", "latency_ms": 1}
        if tokens_in_recorded:
            metadata["tokens_in"] = tokens_in
        rows: list[tuple[UsageResource, int]] = [
            ("llm_calls", 1),
            ("llm_tokens_in", tokens_in),
            ("llm_tokens_out", tokens_out),
        ]
        async with self.engine.begin() as conn:
            for resource, quantity in rows:
                await conn.execute(
                    insert(UsageEvent).values(
                        id=_id_at(at),
                        job_id=job_id,
                        resource=resource,
                        provider=PROVIDER,
                        model_or_pool=model,
                        quantity=quantity,
                        metadata_=metadata,
                    )
                )

    async def report(self, start: date, end: date) -> llm_costs.CostReport:
        async with self.engine.connect() as conn:
            return await llm_costs.cost_report(conn, CostQuery(start=start, end=end), PRICING)


@pytest.fixture
def world(engine: AsyncEngine) -> World:
    return World(engine)


async def test_the_report_sums_calls_tokens_and_cost_by_day_and_by_model_and_role(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, _day(2), kind="c_extract_detail", tokens_in=1000, tokens_out=100)
    await world.call(job_id, _day(3), kind="a_synth", tokens_in=2000, tokens_out=300)

    report = await world.report(date(2031, 1, 2), date(2031, 1, 3))

    total = report.total
    assert (total.calls, total.tokens_in, total.tokens_out, total.unpriced_tokens) == (2, 3000, 400, 0)
    assert total.estimated_usd == pytest.approx(_usd(3000, 400))
    assert [(d.day, d.calls) for d in report.days] == [(date(2031, 1, 2), 1), (date(2031, 1, 3), 1)]
    assert [d.estimated_usd for d in report.days] == [pytest.approx(_usd(1000, 100)), pytest.approx(_usd(2000, 300))]
    assert sorted((b.provider, b.model, b.prompt_kind, b.calls) for b in report.breakdown) == [
        (PROVIDER, "flat", "a_synth", 1),
        (PROVIDER, "flat", "c_extract_detail", 1),
    ]


async def test_every_day_of_the_range_is_reported_and_days_outside_it_are_not(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, datetime(2031, 1, 1, 23, 59, 59, 999_000, tzinfo=UTC))
    await world.call(job_id, datetime(2031, 1, 2, 0, 0, tzinfo=UTC))
    await world.call(job_id, datetime(2031, 1, 4, 23, 59, 59, 999_000, tzinfo=UTC))
    await world.call(job_id, datetime(2031, 1, 5, 0, 0, tzinfo=UTC))

    report = await world.report(date(2031, 1, 2), date(2031, 1, 4))

    assert [(d.day, d.calls) for d in report.days] == [
        (date(2031, 1, 2), 1),
        (date(2031, 1, 3), 0),
        (date(2031, 1, 4), 1),
    ]
    assert report.days[1].estimated_usd == 0
    assert report.total.calls == 2


async def test_a_call_is_priced_at_the_price_of_its_date(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, _day(9), model="dated", tokens_in=1000, tokens_out=100)
    await world.call(job_id, _day(10), model="dated", tokens_in=1000, tokens_out=100)

    report = await world.report(date(2031, 1, 9), date(2031, 1, 10))

    assert [d.estimated_usd for d in report.days] == [
        pytest.approx(_usd(1000, 100)),
        pytest.approx(_usd(1000, 100, "3", "6")),
    ]


async def test_a_call_over_a_prompt_length_tier_pays_its_prices_for_input_and_output(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, _day(2), model="tiered", tokens_in=1000, tokens_out=100)
    await world.call(job_id, _day(3), model="tiered", tokens_in=1001, tokens_out=100)

    report = await world.report(date(2031, 1, 2), date(2031, 1, 3))

    assert [d.estimated_usd for d in report.days] == [
        pytest.approx(_usd(1000, 100)),
        pytest.approx(_usd(1001, 100, "5", "10")),
    ]


async def test_tokens_without_a_price_make_their_cost_unknown_never_guessed(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, _day(2), model="flat", tokens_in=1000, tokens_out=100)
    await world.call(job_id, _day(2), model="unlisted", tokens_in=500, tokens_out=50)
    # A tiered model's output can't be priced without the call's prompt length.
    await world.call(job_id, _day(3), model="tiered", tokens_in=10, tokens_out=7, tokens_in_recorded=False)

    report = await world.report(date(2031, 1, 2), date(2031, 1, 3))

    by_model = {b.model: b for b in report.breakdown}
    assert by_model["flat"].estimated_usd == pytest.approx(_usd(1000, 100))
    assert (by_model["unlisted"].estimated_usd, by_model["unlisted"].unpriced_tokens) == (None, 550)
    assert (by_model["tiered"].estimated_usd, by_model["tiered"].unpriced_tokens) == (None, 7)
    assert (report.total.estimated_usd, report.total.unpriced_tokens) == (None, 557)
    assert [d.estimated_usd for d in report.days] == [None, None]


async def test_before_the_first_checked_price_a_call_has_no_price(world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, datetime(2030, 12, 31, 12, tzinfo=UTC))

    report = await world.report(date(2030, 12, 31), date(2030, 12, 31))

    assert (report.total.calls, report.total.estimated_usd) == (1, None)


async def test_the_top_jobs_are_the_costliest_first(world: World) -> None:
    cheap, dear, middle = await world.job(), await world.job(kind="crawl"), await world.job()
    await world.call(cheap, _day(2), tokens_in=100, tokens_out=10)
    await world.call(dear, _day(2), tokens_in=100_000, tokens_out=1000)
    await world.call(middle, _day(3), tokens_in=10_000, tokens_out=100)

    report = await world.report(date(2031, 1, 2), date(2031, 1, 3))

    assert [(j.job_id, j.calls) for j in report.top_jobs] == [(dear, 1), (middle, 1), (cheap, 1)]
    assert report.top_jobs[0].kind == "crawl"
    assert report.top_jobs[0].estimated_usd == pytest.approx(_usd(100_000, 1000))


async def test_a_jobs_cost_counts_every_call_it_made(world: World) -> None:
    job_id, other = await world.job(), await world.job()
    await world.call(job_id, _day(2), tokens_in=1000, tokens_out=100)
    await world.call(job_id, _day(20), model="dated", tokens_in=1000, tokens_out=100)
    await world.call(other, _day(2), model="unlisted")
    idle = await world.job()

    async with world.engine.connect() as conn:
        costs = await llm_costs.costs_of_jobs(conn, [job_id, other, idle], PRICING)

    assert costs == {
        job_id: pytest.approx(_usd(1000, 100) + _usd(1000, 100, "3", "6")),
        other: None,
        idle: 0,
    }


async def test_a_job_summary_carries_its_estimated_llm_cost(world: World) -> None:
    idle, unpriced = await world.job(), await world.job()
    # The shipped prices list no made-up model, so the cost of its tokens is unknown.
    await world.call(unpriced, _day(2), model="unlisted")

    async with world.engine.connect() as conn:
        summaries = {job_id: await jobs.get_job(conn, job_id) for job_id in (idle, unpriced)}

    assert (summaries[idle].llm_cost_usd, summaries[unpriced].llm_cost_usd) == (0, None)


# Over HTTP.


@pytest.fixture
async def client(
    world: World, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with world.engine.begin() as conn:
        key = await create_key(conn, "llm-costs-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        yield client
    keys = create_async_engine(database_url)
    async with keys.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys.dispose()


async def test_the_report_is_served_for_a_range(client: httpx.AsyncClient, world: World) -> None:
    job_id = await world.job()
    await world.call(job_id, _day(2), model="unlisted", tokens_in=10, tokens_out=5)

    response = await client.get("/v1/usage/llm", params={"start": "2031-01-02", "end": "2031-01-03"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"start", "end", "currency", "total", "days", "breakdown", "top_jobs"}
    assert body["total"] == {
        "calls": 1,
        "tokens_in": 10,
        "tokens_out": 5,
        "unpriced_tokens": 15,
        "estimated_usd": None,
    }
    assert [d["day"] for d in body["days"]] == ["2031-01-02", "2031-01-03"]
    assert [j["job_id"] for j in body["top_jobs"]] == [str(job_id)]


async def test_the_job_costs_page_through_every_job_with_calls_newest_first(
    client: httpx.AsyncClient, world: World
) -> None:
    older, newer = await world.job(), await world.job()
    await world.call(older, _day(2))
    await world.call(newer, _day(2))
    await world.job()  # made no call, so it is not listed
    params = {"start": "2031-01-02", "end": "2031-01-02", "limit": "1"}

    first = (await client.get("/v1/usage/llm/jobs", params=params)).json()
    second = (await client.get("/v1/usage/llm/jobs", params=params | {"cursor": first["next_cursor"]})).json()

    listed = [item["job_id"] for item in first["items"] + second["items"]]
    assert listed == [str(newer), str(older)]
    assert second["next_cursor"] is None


async def test_cost_problems(client: httpx.AsyncClient, world: World) -> None:
    responses = {
        "backwards range": await client.get("/v1/usage/llm", params={"start": "2031-01-03", "end": "2031-01-02"}),
        "over a year": await client.get("/v1/usage/llm", params={"start": "2030-01-01", "end": "2031-01-02"}),
        "bad date": await client.get("/v1/usage/llm", params={"start": "yesterday"}),
        "jobs bad cursor": await client.get("/v1/usage/llm/jobs", params={"cursor": "not-an-id"}),
        "jobs over the page limit": await client.get("/v1/usage/llm/jobs", params={"limit": 201}),
    }

    statuses = {name: (r.status_code, r.json()["type"]) for name, r in responses.items()}
    assert statuses == dict.fromkeys(responses, (422, "validation"))


async def test_costs_need_a_key(client: httpx.AsyncClient, world: World) -> None:
    del client.headers["authorization"]

    response = await client.get("/v1/usage/llm")

    assert (response.status_code, response.json()["type"]) == (401, "unauthorized")
