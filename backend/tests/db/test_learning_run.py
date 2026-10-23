"""The learning run end to end: a site that reaches 8 extracted pages is learned by its
`learn` job without human input and enters `active` with a validated config; its next pages are extracted in `config`
mode, and role C is no longer asked for the fields the config covers. Every other end of a run leaves the state as a
failed run does."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchResult
from crawlerai.config_ir.active import active_config, config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.api_recipe.replay import Replays
from crawlerai.config_ir.learn_job import (
    LEARN_RUN_TIMEOUT,
    LEARNING_FINISHED,
    Learned,
    expire_learn_runs,
    next_learn_job,
    run_learn_job,
)
from crawlerai.config_ir.learning import Hooks
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
from crawlerai.llm.client import LLMRequest, LLMResponse, ReplyCheck, request_hash
from crawlerai.resolve.pipeline import (
    EngineData,
    extract_page,
)
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, SchemaDocument, document_digest
from crawlerai.services import configs as configs_service
from crawlerai.services.page_store import Stored, store_extraction
from crawlerai.storage.capture_bundle import CaptureBundle
from crawlerai.storage.fs import FsStore
from tests.support.captures import call
from tests.support.role_c import FakeRoleC

pytestmark = pytest.mark.anyio

# The price is in an element with no stable anchor, so induction verifies no selector for it and role A is asked.
PRICE_STEP = {"xpath": "normalize-space(//body/p)"}
# The API an API-backed site's pages fetch their values from: page `/p/<n>` from `<ENDPOINT>/<n>`.
ENDPOINT = "https://api.example.test/v1/products"


def _document(name: str) -> SchemaDocument:
    title = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
    price = FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency")
    return SchemaDocument(name=name, page_kind="detail", fields={"title": title, "price": price})


def _page(n: int, *, anchored: bool = False) -> bytes:
    """Product page `n`; with `anchored`, its price element carries a stable class."""
    node = f'{{"@context": "https://schema.org", "@type": "Product", "name": "Kettle {n}"}}'
    script = f'<script type="application/ld+json">{node}</script>'
    price = "<p class='price'>" if anchored else "<p>"
    body = f"<h1>Kettle {n}</h1>{price}{n}.50 EUR</p>"
    return f"<html><head>{script}</head><body>{body}</body></html>".encode()


def _answer(n: int) -> bytes:
    """The API's answer for product `n`, stating its page's path, as the identity check requires."""
    answer = {"data": {"url": f"/p/{n}", "name": f"Kettle {n}", "price": f"{n}.50", "currency": "EUR"}}
    return json.dumps(answer).encode()


def _browser_capture(fetched: FetchResult, n: int) -> FetchResult:
    """`fetched` as the browser captured it, with the API's answer for product `n` among its network bodies."""
    entry, data = call(0, f"{ENDPOINT}/{n}", _answer(n), method="GET")
    manifest = fetched.bundle.manifest.model_copy(update={"method": "browser", "network_bodies": (entry,)})
    bundle = CaptureBundle(manifest=manifest, body=fetched.bundle.body, network=(data,))
    return fetched.model_copy(update={"bundle": bundle})


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


# Role A's reply: `PRICE_STEP` in the wire form (`config_ir.step_wire`).
PRICE_WIRE = {"selector": "xpath", "expression": PRICE_STEP["xpath"], "when_type": "", "source": "", "post": []}
PRICE_REPLY = {"fields": [{"field": "price", "steps": [PRICE_WIRE]}]}


@dataclass
class LearnSite:
    engine: AsyncEngine
    store: FsStore
    origin: str
    site_id: SiteId
    schema: SchemaDef
    data: EngineData
    fetch_result: Callable[..., FetchResult]

    @property
    def key(self) -> StateKey:
        return StateKey(self.site_id, self.schema.id, "detail")

    async def extract(self, n: int, role_c: FakeRoleC, *, api: bool = False, anchored: bool = False) -> Stored:
        """Page `n` fetched and extracted by a scrape job's task, with the site's active config if it has one; with
        `api`, fetched by the browser, which captured the API's answer for it."""
        url = f"{self.origin}/p/{n}"
        fetched = self.fetch_result(url, 200, _page(n, anchored=anchored), (("Content-Type", "text/html"),))
        if api:
            fetched = _browser_capture(fetched, n)
        async with self.engine.begin() as conn:
            project = select(Project.id).where(Project.name == "default").scalar_subquery()
            job = insert(Job).values(project_id=project, kind="scrape", request={}, schema_id=self.schema.id)
            job_id: JobId = (await conn.execute(job.values(engine_version="e").returning(Job.id))).scalar_one()
            capture_id = await store_capture(conn, self.store, fetched, self.site_id)
            task = await insert_claimed(conn, job_id, url, url, "detail", "test-worker")
            config = await active_config(conn, self.site_id, self.schema, self.data.vocabulary)
            result = await extract_page(
                fetched.bundle, self.schema, None if config is None else config.executor, role_c, data=self.data
            )
            stored = await store_extraction(
                conn,
                task,
                result,
                capture_id=capture_id,
                site_id=self.site_id,
                schema=self.schema,
                caller_supplied=True,
                config=config,
            )
            assert stored.outcome != "failed"
            await complete_task(conn, task, stored.outcome, capture_id=capture_id)
            # An extracted or partial page counts toward learning.
            await conn.execute(
                update(ProgressiveState)
                .where(*self.key.where())
                .values(pages_extracted=ProgressiveState.pages_extracted + 1)
            )
        return stored

    async def pages(self, count: int, *, api: bool = False, anchored: bool = False) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(ProgressiveState).values(**self.key.columns()))
        role_c = FakeRoleC(from_text=True)
        for n in range(1, count + 1):
            assert (await self.extract(n, role_c, api=api, anchored=anchored)).outcome == "extracted"

    async def learn(self, role_a: RoleA, replay: Replays | None = None) -> tuple[JobId, Learned | None]:
        async with self.engine.begin() as conn:
            job_id = await next_learn_job(conn)
        assert job_id is not None
        learned = await run_learn_job(
            self.engine,
            self.store,
            role_a,
            job_id,
            vocabulary=self.data.vocabulary,
            max_chars=120_000,
            hooks=Hooks(replay),
        )
        return job_id, learned

    async def recipe(self, config_id: ExtractionConfigId) -> ApiRecipe | None:
        async with self.engine.connect() as conn:
            return recipe_of(await config_by_id(conn, config_id, self.data.vocabulary))

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
) -> LearnSite:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        created = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(created.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    return LearnSite(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)


async def test_a_site_with_8_extracted_pages_is_learned_and_then_served_from_its_config(site: LearnSite) -> None:
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

    # A repeat page: config mode, and no role C call for the covered fields.
    role_c = FakeRoleC(from_text=True)
    stored = await site.extract(9, role_c)
    assert (stored.outcome, stored.result.mode, len(role_c.requests), stored.result.llm_calls) == (
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


@pytest.fixture
async def approval(site: LearnSite) -> AsyncIterator[None]:
    """The project requires approval of learned configs for the test."""
    async with site.engine.begin() as conn:
        await conn.execute(update(Project).values(require_config_approval=True))
    yield
    async with site.engine.begin() as conn:
        await conn.execute(update(Project).values(require_config_approval=False))


@pytest.mark.usefixtures("approval")
async def test_with_approval_required_a_learned_config_waits_until_approved(site: LearnSite) -> None:
    await site.pages(8)
    async with site.engine.begin() as conn:
        assert await trigger_learning(conn, batch=10) == 1

    job_id, learned = await site.learn(RoleA(PRICE_REPLY))

    assert learned is not None
    assert learned.config_id is not None
    assert learned.reason == "pending_approval"
    status, payload = await site.finished(job_id)
    assert (status, payload["config_id"], payload["reason"]) == (
        "completed",
        str(learned.config_id),
        "pending_approval",
    )
    state = await site.state()
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("cold", None, None)
    # Pages are still served cold, and no run starts while the config waits, however many pages come.
    role_c = FakeRoleC(from_text=True)
    assert (await site.extract(9, role_c)).result.mode == "adhoc"
    async with site.engine.begin() as conn:
        await conn.execute(update(ProgressiveState).where(*site.key.where()).values(pages_extracted=100))
        assert await trigger_learning(conn, batch=10) == 0

    async with site.engine.begin() as conn:
        approved = await configs_service.approve_config(conn, learned.config_id)

    assert approved.status == "active"
    assert ((await site.state()).mode, (await site.state()).active_config_id) == ("active", learned.config_id)
    assert (await site.extract(10, role_c)).result.mode == "config"


async def _forced(site: LearnSite) -> None:
    async with site.engine.begin() as conn:
        assert await request_learning(conn, site.key, force=True) is not None


async def test_a_run_validation_refuses_fails_and_the_site_stays_cold(site: LearnSite) -> None:
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


async def test_an_operator_config_activated_during_the_run_is_not_replaced(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)
    operator: list[ExtractionConfigId] = []

    async def correct() -> None:
        # An operator's correction activates while role A is being asked.
        async with site.engine.begin() as conn:
            operator.append(await _operator_config(conn, site))

    job_id, learned = await site.learn(RoleA(PRICE_REPLY, before=correct))

    assert learned == Learned(None, "operator_config")
    state = await site.state()
    assert (state.mode, state.active_config_id, state.learning_started_at) == ("active", operator[0], None)
    assert (await site.finished(job_id))[0] == "failed"


async def _operator_config(conn: AsyncConnection, site: LearnSite) -> ExtractionConfigId:
    ir = {
        "ir_version": "1",
        "site": site.origin.removeprefix("https://"),
        "schema": {"name": site.schema.name, "digest": document_digest(site.schema)},
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


async def test_a_run_whose_process_died_is_ended_after_the_timeout(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        job_id = await next_learn_job(conn)
        assert job_id is not None
        started = func.now() - LEARN_RUN_TIMEOUT - timedelta(minutes=1)
        await conn.execute(update(Job).where(Job.id == job_id).values(status="running", started_at=started))
        recent = await request_learning(conn, StateKey(site.site_id, site.schema.id, "listing"), force=True)
        await conn.execute(update(Job).where(Job.id == recent).values(status="running", started_at=func.now()))

    async with site.engine.begin() as conn:
        assert await expire_learn_runs(conn, batch=10) == 1

    state = await site.state()
    assert (state.mode, state.learning_started_at) == ("cold", None)
    assert await site.finished(job_id) == ("failed", {"config_id": None, "reason": "expired", "report": None})
    async with site.engine.connect() as conn:
        assert (await conn.execute(select(Job.status).where(Job.id == recent))).scalar_one() == "running"
