"""The learning run end to end (SPEC-08 §4.4 to §4.8, §7): a site that reaches 8 extracted pages is learned by its
`learn` job without human input and enters `active` with a validated config; its next pages are extracted in `config`
mode, and role C is no longer asked for the fields the config covers. Every other end of a run leaves the state as a
failed run does.

Pages are made the way a page task makes them (`extract_task`) from synthetic pages on an RFC 2606 host: the title
comes from JSON-LD, the price only from the page text, which a scripted role C reads in cold mode. Role A is a
scripted client; no provider is called.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.collect.base import Candidate
from crawlerai.config_ir.active import active_config
from crawlerai.config_ir.learning import LEARNING_FINISHED, Learned, next_learn_job, run_learn_job
from crawlerai.config_ir.progressive import StateKey, operator_activated, request_learning, trigger_learning
from crawlerai.db.models import (
    Extraction,
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobEvent,
    JobId,
    ProgressiveState,
    Project,
    Record,
    Site,
    SiteId,
)
from crawlerai.db.queue import complete_task, insert_claimed
from crawlerai.llm.client import BudgetExhausted, LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.normalize.base import Ok
from crawlerai.recurring.versions import store_records
from crawlerai.resolve.pipeline import EngineData, GapReply, GapRequest, ListingGapReply, ListingGapRequest
from crawlerai.resolve.task import Stored, extract_task
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PRICE_STEP = {"xpath": "normalize-space(//p[@class='price'])"}


def _document(name: str) -> SchemaDocument:
    title = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
    price = FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency")
    return SchemaDocument(name=name, version=1, page_kind="detail", fields={"title": title, "price": price})


def _page(n: int) -> bytes:
    node = f'{{"@context": "https://schema.org", "@type": "Product", "name": "Kettle {n}"}}'
    script = f'<script type="application/ld+json">{node}</script>'
    body = f"<h1>Kettle {n}</h1><p class='price'>{n}.50 EUR</p>"
    return f"<html><head>{script}</head><body>{body}</body></html>".encode()


class TextRoleC:
    """Role C reading the price from the page text, grounded on its offsets; counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def detail(self, request: GapRequest) -> GapReply:
        self.calls += 1
        text = request.page.cleaned_text.text
        start = text.index(" EUR") - 4
        raw = text[start : start + 8]
        candidates = tuple(
            Candidate(
                field=name,
                entity_id=request.target.id,
                source_kind="llm",
                raw=raw,
                normalized=Ok({"amount": raw.removesuffix(" EUR"), "currency": "EUR"}),
                locator=f"text:{start}-{start + len(raw)}",
                independent=True,
            )
            for name in request.missing
            if name == "price"
        )
        return GapReply(candidates, ())

    async def listing(self, request: ListingGapRequest) -> ListingGapReply:
        raise AssertionError("no listing here")


class RoleA:
    """A scripted role A: each call gets the next reply; `before` runs first, as if the run went on meanwhile."""

    def __init__(self, *replies: Mapping[str, Any] | Exception, before: Callable[[], Awaitable[None]] | None = None):
        self._replies = list(replies)
        self._before = before
        self.requests: list[LLMRequest] = []

    async def complete_json(self, req: LLMRequest, check: ReplyCheck | None = None) -> LLMResponse:
        self.requests.append(req)
        if self._before is not None:
            await self._before()
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        Draft202012Validator(req.output_schema).validate(reply)
        return LLMResponse(
            data=dict(reply),
            provider="fake",
            model="fake-strong",
            tokens_in=1,
            tokens_out=1,
            latency_ms=1,
            request_hash=request_hash(req),
        )


PRICE_REPLY = {"fields": {"price": {"steps": [PRICE_STEP]}}}


@dataclass
class Site_:
    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId
    schema: SchemaDef
    data: EngineData
    fetch_result: Callable[..., FetchResult]

    @property
    def key(self) -> StateKey:
        return StateKey(self.site_id, self.schema.id, self.schema.version, "detail")

    async def extract(self, n: int, role_c: TextRoleC) -> Stored:
        """Page `n` fetched and extracted by a scrape job's task, with the site's active config if it has one."""
        url = f"{self.origin}/p/{n}"
        fetched = self.fetch_result(url, 200, _page(n), (("Content-Type", "text/html"),))
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job = insert(Job).values(project_id=project, kind="scrape", request={}, schema_id=self.schema.id)
            job_id: JobId = (await conn.execute(job.values(engine_version="e").returning(Job.id))).scalar_one()
            capture_id = await store_capture(conn, self.store, fetched, self.site_id)
            task = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
            config = await active_config(conn, self.site_id, self.schema, self.data.vocabulary)
            stored = await extract_task(
                conn,
                task,
                capture_id=capture_id,
                site_id=self.site_id,
                bundle=fetched.bundle,
                schema=self.schema,
                data=self.data,
                role_c=role_c,
                config=config,
                caller_supplied=True,
                write_records=store_records,
            )
            assert stored.outcome != "failed"
            await complete_task(conn, task, stored.outcome, capture_id=capture_id)
            # ARCHITECTURE §8.3: an extracted or partial page counts toward learning.
            await conn.execute(
                update(ProgressiveState)
                .where(*self.key.where())
                .values(pages_extracted=ProgressiveState.pages_extracted + 1)
            )
        return stored

    async def pages(self, count: int) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(ProgressiveState).values(**self.key.columns()))
        role_c = TextRoleC()
        for n in range(1, count + 1):
            assert (await self.extract(n, role_c)).outcome == "extracted"

    async def learn(self, role_a: RoleA) -> tuple[JobId, Learned | None]:
        async with self.engine.begin() as conn:
            job_id = await next_learn_job(conn)
        assert job_id is not None
        learned = await run_learn_job(
            self.engine, self.store, role_a, job_id, vocabulary=self.data.vocabulary, max_chars=120_000
        )
        return job_id, learned

    async def state(self) -> Any:
        async with self.engine.connect() as conn:
            return (await conn.execute(select(ProgressiveState).where(*self.key.where()))).one()

    async def finished(self, job_id: JobId) -> tuple[str, dict[str, Any]]:
        async with self.engine.connect() as conn:
            status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
            events = select(JobEvent.payload).where(JobEvent.job_id == job_id, JobEvent.kind == LEARNING_FINISHED)
            return status, (await conn.execute(events)).scalar_one()


@pytest.fixture
async def site(
    engine: AsyncEngine,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    tmp_path: Path,
) -> AsyncIterator[Site_]:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        created = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(created.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    yield Site_(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)
    # The site's configs, which `own_origin` does not know of, go before it deletes the site.
    async with engine.begin() as conn:
        await conn.execute(delete(ProgressiveState).where(ProgressiveState.site_id == site_id))
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


async def test_a_site_with_8_extracted_pages_is_learned_and_then_served_from_its_config(site: Site_) -> None:
    await site.pages(8)
    async with site.engine.begin() as conn:
        assert await trigger_learning(conn, batch=10) == 1

    role_a = RoleA(PRICE_REPLY)
    job_id, learned = await site.learn(role_a)

    assert learned is not None
    assert learned.config_id is not None
    # Induction learned the title from the JSON-LD locators; role A was asked only for the price.
    assert [r.prompt_kind for r in role_a.requests] == ["a_synth"]
    state = await site.state()
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("active", learned.config_id, None)
    async with site.engine.connect() as conn:
        config = (await conn.execute(select(ExtractionConfig).where(ExtractionConfig.id == learned.config_id))).one()
    assert (config.status, config.version, config.origin) == ("active", 1, "llm_synth")
    # The title equals its JSON-LD value on the 3 held-out pages; the price has no structured value to compare with.
    assert config.field_status == {"title": "corroborated", "price": "uncorroborated"}
    assert len(config.validation_report["held_out"]) == 3
    status, payload = await site.finished(job_id)
    assert (status, payload["config_id"], payload["reason"]) == ("completed", str(learned.config_id), None)

    # A repeat page: config mode, and no role C call for the covered fields (§7).
    role_c = TextRoleC()
    stored = await site.extract(9, role_c)
    assert (stored.outcome, stored.result.mode, role_c.calls, stored.result.llm_calls) == (
        "extracted",
        "config",
        0,
        (),
    )
    entity = stored.result.entity
    assert entity is not None
    assert (entity["price"].value, entity["price"].evidence) == (
        {"amount": "9.50", "currency": "EUR"},
        "config_uncorroborated",
    )
    async with site.engine.connect() as conn:
        extraction = (await conn.execute(select(Extraction).where(Extraction.id == stored.extraction_id))).one()
        record_mode = (
            await conn.execute(select(Record.mode).where(Record.extraction_id == stored.extraction_id))
        ).scalar_one()
    assert (extraction.mode, extraction.config_version, extraction.llm_calls, record_mode) == ("config", 1, 0, "config")


async def _forced(site: Site_) -> None:
    async with site.engine.begin() as conn:
        assert await request_learning(conn, site.key, force=True) is not None


async def test_a_run_validation_refuses_fails_and_the_site_stays_cold(site: Site_) -> None:
    await site.pages(6)  # five sample pages leave one held out, fewer than 3
    await _forced(site)

    job_id, learned = await site.learn(RoleA(PRICE_REPLY))

    assert learned == Learned(None, "too_few_held_out")
    state = await site.state()
    assert (state.mode, state.active_config_id, state.learning_started_at, state.retry_at_pages) == (
        "cold",
        None,
        None,
        14,
    )
    status, payload = await site.finished(job_id)
    assert (status, payload["reason"], payload["report"]["refused"]) == (
        "failed",
        "too_few_held_out",
        "too_few_held_out",
    )


async def test_an_llm_failure_fails_the_run_and_nothing_activates(site: Site_) -> None:
    await site.pages(8)
    await _forced(site)

    job_id, learned = await site.learn(RoleA(BudgetExhausted("no budget")))

    assert learned == Learned(None, BudgetExhausted.code)
    assert ((await site.state()).mode, await site.finished(job_id)) == (
        "cold",
        ("failed", {"config_id": None, "reason": BudgetExhausted.code, "report": None}),
    )


async def test_an_operator_config_activated_during_the_run_is_not_replaced(site: Site_) -> None:
    await site.pages(8)
    await _forced(site)
    operator: list[ExtractionConfigId] = []

    async def correct() -> None:
        # An operator's correction activates while role A is being asked (§4.10, D-0598).
        async with site.engine.begin() as conn:
            operator.append(await _operator_config(conn, site))

    job_id, learned = await site.learn(RoleA(PRICE_REPLY, before=correct))

    assert learned == Learned(None, "operator_config")
    state = await site.state()
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("active", operator[0], None)
    assert (await site.finished(job_id))[0] == "failed"


async def _operator_config(conn: AsyncConnection, site: Site_) -> ExtractionConfigId:
    ir = {
        "ir_version": "1",
        "site": site.origin.removeprefix("https://"),
        "schema": {"name": site.schema.name, "version": 1},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"price": {"steps": [PRICE_STEP], "status": "operator"}},
        "provenance": {
            "origin": "operator",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
    }
    config = insert(ExtractionConfig).values(
        **site.key.columns(), version=1, status="active", ir=ir, origin="operator", field_status={"price": "operator"}
    )
    config_id: ExtractionConfigId = (await conn.execute(config.returning(ExtractionConfig.id))).scalar_one()
    await operator_activated(conn, site.key, config_id)
    return config_id


async def test_a_learn_job_cancelled_before_it_starts_ends_the_run(site: Site_) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        await conn.execute(update(Job).where(Job.kind == "learn").values(cancel_requested=True))

    job_id, learned = await site.learn(RoleA())

    assert learned == Learned(None, "cancelled")
    async with site.engine.connect() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    assert (status, (await site.state()).learning_started_at) == ("cancelled", None)


async def test_a_job_another_process_started_is_not_run_again(site: Site_) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        job_id = await next_learn_job(conn)
        await conn.execute(update(Job).where(Job.id == job_id).values(status="running"))
    assert job_id is not None

    learned = await run_learn_job(
        site.engine, site.store, RoleA(), job_id, vocabulary=site.data.vocabulary, max_chars=120_000
    )

    assert learned is None
