"""The learning run end to end (SPEC-08 §4.4 to §4.8, §7): a site that reaches 8 extracted pages is learned by its
`learn` job without human input and enters `active` with a validated config; its next pages are extracted in `config`
mode, and role C is no longer asked for the fields the config covers. Every other end of a run leaves the state as a
failed run does.

Pages are made the way a page task makes them (`extract_task`) from synthetic pages on an RFC 2606 host: the title
comes from JSON-LD, the price only from the page text, which a scripted role C reads in cold mode. Role A is a
scripted client; no provider is called. On an API-backed site the pages are browser captures whose network bodies hold
the values, and a stand-in API (`tests.stand_in`) answers the run's replays (SPEC-09 §2, §7).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.persist import store_capture
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.collect.base import Candidate
from crawlerai.config_ir import learning
from crawlerai.config_ir.active import active_config, config_by_id, recipe_of
from crawlerai.config_ir.api_recipe.model import ApiRecipe, Proof
from crawlerai.config_ir.api_recipe.replay import Replays
from crawlerai.config_ir.held_out import load_pages
from crawlerai.config_ir.learning import (
    LEARN_RUN_TIMEOUT,
    LEARNING_FINISHED,
    Learned,
    expire_learn_runs,
    next_learn_job,
    run_learn_job,
)
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
from crawlerai.resolve.types import LLMCallRecord
from crawlerai.schemas import registry
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaContent, SchemaDef, SchemaDocument, document_digest
from crawlerai.services import configs as configs_service
from crawlerai.services import schemas as schemas_service
from crawlerai.services.jobs import cancel_job
from crawlerai.storage.capture_bundle import CaptureBundle, NetworkBody, sha256_hex
from crawlerai.storage.fs import FsStore
from crawlerai.worker.learn import run_learner

pytestmark = pytest.mark.anyio

PRICE_STEP = {"xpath": "normalize-space(//p[@class='price'])"}
# The API an API-backed site's pages fetch their values from: page `/p/<n>` from `<ENDPOINT>/<n>`.
ENDPOINT = "https://api.example.test/v1/products"
StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)


def _document(name: str) -> SchemaDocument:
    title = FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name")
    price = FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency")
    return SchemaDocument(name=name, page_kind="detail", fields={"title": title, "price": price})


def _page(n: int) -> bytes:
    node = f'{{"@context": "https://schema.org", "@type": "Product", "name": "Kettle {n}"}}'
    script = f'<script type="application/ld+json">{node}</script>'
    body = f"<h1>Kettle {n}</h1><p class='price'>{n}.50 EUR</p>"
    return f"<html><head>{script}</head><body>{body}</body></html>".encode()


def _answer(n: int) -> bytes:
    """The API's answer for product `n`."""
    return json.dumps({"data": {"name": f"Kettle {n}", "price": f"{n}.50", "currency": "EUR"}}).encode()


def _browser_capture(fetched: FetchResult, n: int) -> FetchResult:
    """`fetched` as the browser captured it, with the API's answer for product `n` among its network bodies."""
    data = _answer(n)
    entry = NetworkBody(
        url=f"{ENDPOINT}/{n}",
        status=200,
        content_type="application/json",
        sha256=sha256_hex(data),
        file="network/0001.json",
        method="GET",
    )
    manifest = fetched.bundle.manifest.model_copy(update={"method": "browser", "network_bodies": (entry,)})
    bundle = CaptureBundle(manifest=manifest, body=fetched.bundle.body, network=(data,))
    return fetched.model_copy(update={"bundle": bundle})


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


# Role A's reply: `PRICE_STEP` in the wire form (`config_ir.step_wire`).
PRICE_WIRE = {"selector": "xpath", "expression": PRICE_STEP["xpath"], "when_type": "", "source": "", "post": []}
PRICE_REPLY = {"fields": [{"field": "price", "steps": [PRICE_WIRE]}]}
# A reply whose price step matches no element of the sample pages.
MISSING_PRICE_REPLY = {
    "fields": [{"field": "price", "steps": [{**PRICE_WIRE, "expression": "normalize-space(//p[@class='absent'])"}]}]
}


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

    async def extract(self, n: int, role_c: TextRoleC, *, api: bool = False) -> Stored:
        """Page `n` fetched and extracted by a scrape job's task, with the site's active config if it has one; with
        `api`, fetched by the browser, which captured the API's answer for it."""
        url = f"{self.origin}/p/{n}"
        fetched = self.fetch_result(url, 200, _page(n), (("Content-Type", "text/html"),))
        if api:
            fetched = _browser_capture(fetched, n)
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

    async def pages(self, count: int, *, api: bool = False) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(insert(ProgressiveState).values(**self.key.columns()))
        role_c = TextRoleC()
        for n in range(1, count + 1):
            assert (await self.extract(n, role_c, api=api)).outcome == "extracted"

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
            replay=replay,
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
) -> AsyncIterator[LearnSite]:
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        created = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://"))
        site_id = (await conn.execute(created.returning(Site.id))).scalar_one()
        schema = await registry.create(conn, _document(schema_name), "user")
    yield LearnSite(engine, FsStore(tmp_path / "objects"), own_origin, site_id, schema, engine_data, fetch_result)
    # The site's configs, which `own_origin` does not know of, go before it deletes the site.
    async with engine.begin() as conn:
        await conn.execute(delete(ProgressiveState).where(ProgressiveState.site_id == site_id))
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


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


class AskedRoleC(TextRoleC):
    """`TextRoleC` whose every call is an answered, charged LLM call, as a provider's is."""

    async def detail(self, request: GapRequest) -> GapReply:
        reply = await super().detail(request)
        call = LLMCallRecord(
            prompt_kind="c_extract_detail", provider="p", model="m", request_hash="0" * 64, tokens_in=1, tokens_out=1
        )
        return GapReply(reply.candidates, (call,))


async def test_a_required_field_no_page_states_is_learned_as_absent_and_not_asked_again(site: LearnSite) -> None:
    # D-1341: the sku is required, no source on any of the 8 pages states it, and role C was asked on each.
    document = _document(f"{site.schema.name}_sku")
    sku = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", required=True, schema_org="Product.sku")
    document = document.model_copy(update={"fields": {**document.fields, "sku": sku}})
    async with site.engine.begin() as conn:
        schema = await registry.create(conn, document, "user")
        site = replace(site, schema=schema)
        await conn.execute(insert(ProgressiveState).values(**site.key.columns()))
    role_c = AskedRoleC()
    for n in range(1, 9):
        assert (await site.extract(n, role_c)).outcome == "partial"
    await _forced(site)

    _, learned = await site.learn(RoleA(PRICE_REPLY))

    assert learned is not None
    assert learned.config_id is not None
    async with site.engine.connect() as conn:
        config = (await conn.execute(select(ExtractionConfig).where(ExtractionConfig.id == learned.config_id))).one()
    assert (config.ir["absent"], config.field_status["sku"]) == (["sku"], "absent")
    assert config.validation_report["fields"]["sku"]["dropped"] == "not_learned: absent"
    role_c = AskedRoleC()
    stored = await site.extract(9, role_c)
    assert stored.result.entity is not None
    sku_outcome = stored.result.entity["sku"]
    assert (role_c.calls, sku_outcome.status, sku_outcome.reason) == (0, "missing", "absent")


async def test_only_an_extraction_that_could_ask_role_c_for_every_gap_counts_as_asked(site: LearnSite) -> None:
    # A config-mode extraction asks role C only for the fields its config does not cover, so its LLM call says
    # nothing about a covered field: it never makes that field absent (D-1341).
    async with site.engine.begin() as conn:
        await conn.execute(insert(ProgressiveState).values(**site.key.columns()))
    role_c = AskedRoleC()
    await site.extract(1, role_c)
    configured = await site.extract(2, role_c)
    async with site.engine.begin() as conn:
        await conn.execute(
            update(Extraction).where(Extraction.id == configured.extraction_id).values(mode="config", config_version=1)
        )
        pages = await load_pages(conn, site.store, site.site_id, site.schema, limit=10)

    assert [page.asked_llm for page in pages] == [False, True]  # most recent first: the config-mode one


@pytest.fixture
async def approval(site: LearnSite) -> AsyncIterator[None]:
    """The project requires approval of learned configs (D-1342) for the test."""
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
    role_c = TextRoleC()
    assert (await site.extract(9, role_c)).result.mode == "adhoc"
    async with site.engine.begin() as conn:
        await conn.execute(update(ProgressiveState).where(*site.key.where()).values(pages_extracted=100))
        assert await trigger_learning(conn, batch=10) == 0

    async with site.engine.begin() as conn:
        approved = await configs_service.approve_config(conn, learned.config_id)

    assert approved.status == "active"
    assert ((await site.state()).mode, (await site.state()).active_config_id) == ("active", learned.config_id)
    assert (await site.extract(10, role_c)).result.mode == "config"


async def test_a_field_role_a_gives_no_working_steps_is_reported_as_not_learned_with_why(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)

    # Each reply's price step matches nothing on the sample: the first call and every repair fail.
    role_a = RoleA(*[MISSING_PRICE_REPLY] * 4)
    _, learned = await site.learn(role_a)

    assert learned is not None
    assert learned.config_id is not None
    async with site.engine.connect() as conn:
        config = (await conn.execute(select(ExtractionConfig).where(ExtractionConfig.id == learned.config_id))).one()
    # The config and its statuses hold only what validated; the report says why the price has no steps.
    assert (sorted(config.ir["fields"]), config.field_status) == (["title"], {"title": "corroborated"})
    assert config.validation_report["fields"]["price"] == {
        "pages": 3,
        "matched": 0,
        "valid": 0,
        "published": 0,
        "reproduced": 0,
        "comparable": 0,
        "corroborated_on": 0,
        "status": None,
        "yield": 0.0,
        "validity": None,
        "dropped": "not_learned: not_induced:text; synthesis: page 1: no_match; page 2: no_match",
    }
    assert [r.prompt_kind for r in role_a.requests] == ["a_synth", "a_repair", "a_repair", "a_repair"]


def _replay(stand_in_api: StandInApi, products: range, sent: list[str]) -> Replays:
    """The run's replays, answered by the stand-in API for `products`; each request's URL is added to `sent`."""
    fetcher = stand_in_api({f"{ENDPOINT}/{n}": _answer(n) for n in products})

    async def replay(request: JsonRequest) -> FetchResult:
        sent.append(request.url)
        return await fetcher(request, FetchPolicy(timeout_s=5))

    return lambda _job_id, _proxy_pool: replay


async def test_a_site_whose_values_come_from_an_api_is_learned_with_a_validated_recipe(
    site: LearnSite, stand_in_api: StandInApi
) -> None:
    await site.pages(8, api=True)
    await _forced(site)
    sent: list[str] = []

    job_id, learned = await site.learn(RoleA(PRICE_REPLY), _replay(stand_in_api, range(1, 9), sent))

    assert learned is not None
    assert learned.config_id is not None
    recipe = await site.recipe(learned.config_id)
    status, payload = await site.finished(job_id)
    held_out = payload["report"]["api_recipe"]["held_out"]
    assert recipe == ApiRecipe(
        method="GET",
        url=f"{ENDPOINT}/{{p1}}",
        params_from_url={"p1": "path:1"},
        headers={"Accept": "application/json"},
        map={"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
        proof=Proof(validated_on=held_out, headers_tried=0, bound_by="deterministic"),
    )
    assert (status, len(held_out), payload["report"]["api_recipe"]["refused"]) == ("completed", 3, None)
    # Five sample replays prove the headers, three held-out ones validate the recipe.
    assert len(sent) == 8


async def test_a_recipe_that_does_not_validate_leaves_the_config_without_one(
    site: LearnSite, stand_in_api: StandInApi
) -> None:
    await site.pages(8, api=True)
    await _forced(site)

    # The API answers only the five most recent products, the sample (§4.4): the held-out pages do not reproduce.
    job_id, learned = await site.learn(RoleA(PRICE_REPLY), _replay(stand_in_api, range(4, 9), []))

    assert learned is not None
    assert learned.config_id is not None
    assert await site.recipe(learned.config_id) is None
    status, payload = await site.finished(job_id)
    assert (status, payload["report"]["api_recipe"]["refused"]) == ("completed", "not_reproduced: price, title")


async def test_a_recipe_learning_error_refuses_the_recipe_and_the_config_still_activates(site: LearnSite) -> None:
    # D-1389: an error of the recipe learner itself, not of the LLM, is reported as a refused recipe.
    await site.pages(8, api=True)
    await _forced(site)

    async def broken(_request: JsonRequest) -> FetchResult:
        raise RuntimeError("synthetic replay failure")

    job_id, learned = await site.learn(RoleA(PRICE_REPLY), lambda _job_id, _pool: broken)

    assert learned is not None
    assert learned.config_id is not None
    assert await site.recipe(learned.config_id) is None
    status, payload = await site.finished(job_id)
    assert (status, payload["report"]["api_recipe"]["refused"]) == ("completed", "recipe_error: RuntimeError")


async def test_a_replays_usage_that_cannot_be_stored_fails_the_run_and_nothing_activates(site: LearnSite) -> None:
    # A database error is the run's, not the recipe learner's: the replay's request would go unaccounted (D-1381).
    await site.pages(8, api=True)
    await _forced(site)

    async def unaccounted(_request: JsonRequest) -> FetchResult:
        raise OperationalError("INSERT INTO usage_event", {}, ConnectionError("synthetic"))

    job_id, learned = await site.learn(RoleA(PRICE_REPLY), lambda _job_id, _pool: unaccounted)

    assert learned == Learned(None, "error")
    assert ((await site.state()).mode, (await site.finished(job_id))[0]) == ("cold", "failed")


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


async def test_an_llm_failure_fails_the_run_and_nothing_activates(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)

    job_id, learned = await site.learn(RoleA(BudgetExhausted("no budget")))

    assert learned == Learned(None, BudgetExhausted.code)
    assert ((await site.state()).mode, await site.finished(job_id)) == (
        "cold",
        ("failed", {"config_id": None, "reason": BudgetExhausted.code, "report": None}),
    )


async def test_an_operator_config_activated_during_the_run_is_not_replaced(site: LearnSite) -> None:
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


async def _edit_schema(site: LearnSite) -> None:
    """The site's schema edited through the service a caller's edit goes through (SPEC-04 §4.1)."""
    content = SchemaContent(page_kind="detail", fields=site.schema.fields, required_groups=[["title"]])
    async with site.engine.begin() as conn:
        await schemas_service.update(conn, site.schema.id, content)


async def test_a_run_its_schema_edit_overtook_leaves_the_next_run_and_activates_nothing(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)
    later: list[JobId | None] = []

    async def edit_and_learn_again() -> None:
        # The schema is edited while role A is being asked, and the next run starts on the edited document.
        await _edit_schema(site)
        async with site.engine.begin() as conn:
            later.append(await request_learning(conn, site.key, force=True))

    job_id, learned = await site.learn(RoleA(PRICE_REPLY, before=edit_and_learn_again))

    assert learned == Learned(None, learning.SCHEMA_EDITED)
    state = await site.state()
    assert later[0] is not None
    assert (state.mode, state.active_config_id, state.learning_started_at is not None) == ("learning", None, True)
    async with site.engine.connect() as conn:
        configs = select(ExtractionConfig.id).where(*site.key.config_scope())
        assert (await conn.execute(configs)).all() == []
    status, payload = await site.finished(job_id)
    assert (status, payload["reason"], payload["config_id"]) == ("failed", learning.SCHEMA_EDITED, None)


async def test_a_run_that_fails_after_its_schema_was_edited_ends_without_touching_the_state(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)

    async def edit() -> None:
        await _edit_schema(site)

    job_id, learned = await site.learn(RoleA(BudgetExhausted("no budget"), before=edit))

    assert learned == Learned(None, learning.SCHEMA_EDITED)
    state = await site.state()
    assert (state.mode, state.learning_started_at, state.retry_at_pages) == ("cold", None, None)
    assert (await site.finished(job_id))[0:1] == ("failed",)


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


async def test_a_learn_job_cancelled_before_it_starts_ends_the_run(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        await conn.execute(update(Job).where(Job.kind == "learn").values(cancel_requested=True))

    job_id, learned = await site.learn(RoleA())

    assert learned == Learned(None, "cancelled")
    async with site.engine.connect() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    assert (status, (await site.state()).learning_started_at) == ("cancelled", None)


async def test_a_job_another_process_started_is_not_run_again(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        job_id = await next_learn_job(conn)
        await conn.execute(update(Job).where(Job.id == job_id).values(status="running"))
    assert job_id is not None

    learned = await run_learn_job(
        site.engine, site.store, RoleA(), job_id, vocabulary=site.data.vocabulary, max_chars=120_000, replay=None
    )

    assert learned is None


async def test_the_worker_runs_a_queued_learn_job_to_its_end(site: LearnSite, stand_in_api: StandInApi) -> None:
    await site.pages(8, api=True)
    async with site.engine.begin() as conn:
        assert await trigger_learning(conn, batch=10) == 1
    stop = asyncio.Event()
    sent: list[str] = []
    learner = asyncio.create_task(
        run_learner(
            site.engine,
            site.store,
            RoleA(PRICE_REPLY),
            stop,
            vocabulary=site.data.vocabulary,
            max_chars=1000,
            replay=_replay(stand_in_api, range(1, 9), sent),
        )
    )

    async with asyncio.timeout(30):
        while (await site.state()).mode == "learning":
            await asyncio.sleep(0.05)
    stop.set()
    await learner

    state = await site.state()
    assert state.mode == "active"
    # The learner's runs replay recipes: the config it activated has one.
    assert await site.recipe(state.active_config_id) is not None
    assert len(sent) == 8


async def test_cancelling_a_queued_learn_job_ends_its_run(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        job_id = await next_learn_job(conn)
        assert job_id is not None
        await cancel_job(conn, job_id)

    state = await site.state()
    assert (state.mode, state.learning_started_at, state.retry_at_pages) == ("cold", None, 11)
    async with site.engine.begin() as conn:
        assert await request_learning(conn, site.key, force=True) is not None


async def test_a_learn_job_that_cannot_start_fails_and_is_not_picked_again(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        # A request naming a page kind the state does not have: `_start` cannot read its state.
        request = Job.request.op("||")(func.jsonb_build_object("page_kind", "listing"))
        await conn.execute(update(Job).where(Job.kind == "learn").values(request=request))

    job_id, learned = await site.learn(RoleA())

    assert learned == Learned(None, "error")
    async with site.engine.begin() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
        assert (status, await next_learn_job(conn)) == ("failed", None)


async def test_a_learn_job_whose_request_names_no_state_fails_and_is_not_picked_again(site: LearnSite) -> None:
    await site.pages(3)
    await _forced(site)
    async with site.engine.begin() as conn:
        await conn.execute(update(Job).where(Job.kind == "learn").values(request={"site_id": "not a uuid"}))

    job_id, learned = await site.learn(RoleA())

    assert learned == Learned(None, "error")
    async with site.engine.begin() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
        assert (status, await next_learn_job(conn)) == ("failed", None)


async def test_a_stopping_worker_ends_the_run_in_progress_without_waiting_for_it(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)
    asked, never = asyncio.Event(), asyncio.Event()

    async def hang() -> None:  # role A takes as long as it may (minutes, `llm.client.TIMEOUT_S`)
        asked.set()
        await never.wait()

    stop = asyncio.Event()
    learner = asyncio.create_task(
        run_learner(
            site.engine,
            site.store,
            RoleA(PRICE_REPLY, before=hang),
            stop,
            vocabulary=site.data.vocabulary,
            max_chars=1000,
            replay=None,
        )
    )
    async with asyncio.timeout(30):
        await asked.wait()

    stop.set()
    async with asyncio.timeout(5):
        await learner

    async with site.engine.connect() as conn:
        job_id = (await conn.execute(select(Job.id).where(Job.kind == "learn"))).scalar_one()
    assert await site.finished(job_id) == ("failed", {"config_id": None, "reason": "shutdown", "report": None})
    state = await site.state()
    assert (state.mode, state.learning_started_at) == ("cold", None)


async def test_a_worker_that_stops_while_the_run_ends_still_ends_it(
    site: LearnSite, monkeypatch: pytest.MonkeyPatch
) -> None:
    await site.pages(8)
    await _forced(site)
    ending, never = asyncio.Event(), asyncio.Event()

    async def activating(*args: object, **kwargs: object) -> None:  # the run's final transaction, still open
        ending.set()
        await never.wait()

    monkeypatch.setattr(learning, "activate", activating)
    stop = asyncio.Event()
    learner = asyncio.create_task(
        run_learner(
            site.engine,
            site.store,
            RoleA(PRICE_REPLY),
            stop,
            vocabulary=site.data.vocabulary,
            max_chars=1000,
            replay=None,
        )
    )
    async with asyncio.timeout(30):
        await ending.wait()

    stop.set()
    async with asyncio.timeout(5):
        await learner

    async with site.engine.connect() as conn:
        job_id = (await conn.execute(select(Job.id).where(Job.kind == "learn"))).scalar_one()
    # Not left `running` until `expire_learn_runs`: the run ends as one its stopping worker cancelled.
    assert await site.finished(job_id) == ("failed", {"config_id": None, "reason": "shutdown", "report": None})
    state = await site.state()
    assert (state.mode, state.learning_started_at) == ("cold", None)


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


async def test_a_run_that_ends_after_it_expired_writes_nothing(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)

    async def expire() -> None:
        # The scheduler gives the run up while role A is being asked, as if its process had died.
        async with site.engine.begin() as conn:
            await conn.execute(update(Job).where(Job.kind == "learn").values(started_at=func.now() - timedelta(days=1)))
            assert await expire_learn_runs(conn, batch=10) == 1

    job_id, learned = await site.learn(RoleA(PRICE_REPLY, before=expire))

    assert learned == Learned(None, "expired")
    state = await site.state()
    assert (state.mode, state.active_config_id) == ("cold", None)
    assert (await site.finished(job_id))[0] == "failed"


async def test_cancelling_a_running_learn_job_ends_it_through_its_run(site: LearnSite) -> None:
    await site.pages(8)
    await _forced(site)

    async def cancel() -> None:
        async with site.engine.begin() as conn:
            job_id = (await conn.execute(select(Job.id).where(Job.kind == "learn"))).scalar_one()
            assert (await cancel_job(conn, job_id)).status == "running"

    job_id, learned = await site.learn(RoleA(PRICE_REPLY, before=cancel))

    assert learned == Learned(None, "cancelled")
    state = await site.state()
    assert (state.mode, state.learning_started_at, state.active_config_id) == ("cold", None, None)
    assert (await site.finished(job_id))[0] == "cancelled"
