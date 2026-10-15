"""A site whose active config has an API recipe is served through it (SPEC-09 §4.8, SPEC-02 §4.4, ARCHITECTURE §7.1
"Adapter / API" rung): in a scrape, and in the worker's `batch_scrape` and `crawl` tasks. The recipe's request goes
through robots.txt and the site's rate like the page's would (SPEC-02 §4.6); its values are `api` candidates in the
`adapter` bucket (§10); a page the recipe serves joins no drift window, which measures the config's page steps.

The web is a stub that answers synthetic pages and JSON on RFC 2606 hosts, and the resolver a stub: no network.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    Candidate,
    Extraction,
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    JobKind,
    Project,
    Record,
    Site,
    SiteId,
    UrlTask,
)
from crawlerai.recurring.listing_diff import close_run
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services import captures
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.crawl import CrawlRequest, submit_crawl
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler, run_worker
from tests.db.conftest import resolve

pytestmark = pytest.mark.anyio

TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}
# The page's heading is not the product's name, so a value read from the page and one from the API differ.
PAGE = b"""<!doctype html><html lang="en"><head><title>Lamps</title></head>
<body><main><h1>Lamp page</h1><p>A lamp that lights a desk.</p><a href="/p/other-lamp">Another lamp</a></main></body>
</html>"""
PRODUCT = {"data": {"name": "Desk Lamp", "price": 19.5, "currency": "EUR"}}


@dataclass
class Web:
    """Answers each URL from `pages` over HTTP, and each endpoint from `endpoints` as JSON; anything else is a 404.
    The browser is never used."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, bytes] = field(default_factory=dict)
    endpoints: dict[str, object] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)
    requested: list[JsonRequest] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.fetched.append(url)
        if url not in self.pages:
            return self.fetch_result(url, 404, b"gone", block_class="not_found")
        return self.fetch_result(url, 200, self.pages[url])

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("these pages never need a browser")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request)
        if request.url not in self.endpoints:
            return self.fetch_result(request.page_url, 404, b"{}", block_class="not_found", method="api")
        body = json.dumps(self.endpoints[request.url]).encode()
        return self.fetch_result(request.page_url, 200, body, method="api")

    def page_fetches(self) -> list[str]:
        return [url for url in self.fetched if not url.endswith("/robots.txt")]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": b"User-agent: *\nAllow: /\n"})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.http, browser=web.browser, json=web.json)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
async def lamp_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "version": 1, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


@pytest.fixture
async def site(engine: AsyncEngine, own_origin: str) -> SiteId:
    """The origin's site with a short interval, so its page and its endpoint go without waiting a second each."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"project_id": project, "host": own_origin.removeprefix("https://"), "crawl_delay_ms": 1}
        return (await conn.execute(insert(Site).values(values).returning(Site.id))).scalar_one()


def _ir(origin: str, schema: SchemaDef) -> dict[str, Any]:
    """A config that reads the title from the page's heading, with a recipe that reads both fields from the API."""
    return {
        "ir_version": "1",
        "site": origin.removeprefix("https://"),
        "schema": {"name": schema.name, "version": schema.version},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"title": {"steps": [{"xpath": "normalize-space(//h1)"}], "status": "corroborated"}},
        "api_recipe": {
            "method": "GET",
            "url": f"{origin}/api/products/{{p1}}",
            "params_from_url": {"p1": "path:1"},
            "map": {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
            "proof": {"validated_on": [str(uuid.UUID(int=1))], "headers_tried": 1, "bound_by": "deterministic"},
        },
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "t",
        },
    }


@pytest.fixture
async def recipe_config(
    engine: AsyncEngine, own_origin: str, site: SiteId, lamp_schema: SchemaDef
) -> AsyncIterator[ExtractionConfigId]:
    """The site's active config for the schema, with its API recipe."""
    values = {
        "site_id": site,
        "schema_id": lamp_schema.id,
        "schema_version": lamp_schema.version,
        "page_kind": "detail",
        "version": 1,
        "status": "active",
        "ir": _ir(own_origin, lamp_schema),
        "origin": "induced",
        "field_status": {"title": "corroborated"},
    }
    async with engine.begin() as conn:
        config_id = (
            await conn.execute(insert(ExtractionConfig).values(values).returning(ExtractionConfig.id))
        ).scalar_one()
    yield config_id
    async with engine.begin() as conn:
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site))


async def _drift_window(engine: AsyncEngine, config_id: uuid.UUID) -> object:
    async with engine.connect() as conn:
        query = select(ExtractionConfig.drift_window).where(ExtractionConfig.id == config_id)
        return (await conn.execute(query)).scalar_one()


async def _stored(engine: AsyncEngine, job_id: JobId) -> tuple[dict[str, Any], list[tuple[str, str, bool]]]:
    """The job's one record's data, and its candidates as (field, source kind, chosen)."""
    async with engine.connect() as conn:
        record = (await conn.execute(select(Record.data, Record.extraction_id).where(Record.job_id == job_id))).one()
        rows = await conn.execute(
            select(Candidate.field, Candidate.source_kind, Candidate.chosen)
            .where(Candidate.extraction_id == record.extraction_id)
            .order_by(Candidate.field, Candidate.source_kind)
        )
        return record.data, [(row.field, row.source_kind, row.chosen) for row in rows]


# The scrape service.


def _scrape(url: str, schema: SchemaDef, *formats: str) -> ScrapeRequest:
    return ScrapeRequest.model_validate(
        {"url": url, "formats": ["records", *formats], "schema": {"id": str(schema.id)}, "page_kind": "detail"}
    )


async def test_a_scrape_of_a_site_with_a_recipe_is_served_over_its_api(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method) == ("extracted", "api")
    assert web.page_fetches() == []  # no HTML page, no browser
    assert [(r.url, r.page_url) for r in web.requested] == [(f"{own_origin}/api/products/desk-lamp", url)]
    assert result.records is not None
    (record,) = result.records
    title, price = record.fields["title"], record.fields["price"]
    assert (record.mode, title.value, title.source_kind, title.evidence) == ("config", "Desk Lamp", "api", "adapter")
    assert title.locator == f"api:{recipe_config}:$['data']['name']"
    assert price.value == {"amount": "19.5", "currency": "EUR"}
    # The page steps did not run on the JSON, so their window shows nothing of them.
    assert await _drift_window(engine, recipe_config) == {}


async def test_a_scrape_asking_for_page_formats_fetches_the_page(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    # A JSON body has no markdown, links or metadata of the page: formats read the page itself.
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT

    result = await scrape(engine, fetching, _scrape(url, lamp_schema, "markdown"), data=engine_data)

    assert result.fetch is not None
    assert (result.fetch.method, web.page_fetches(), web.requested) == ("http", [url], [])
    assert result.records is not None
    assert result.records[0].fields["title"].value == "Lamp page"
    assert await _drift_window(engine, recipe_config) == {"title": [[True, True]]}


async def test_max_age_reuses_an_api_capture_for_a_record_only(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    first = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)
    recent = {"max_age": 3600}

    again = await scrape(engine, fetching, _scrape(url, lamp_schema).model_copy(update=recent), data=engine_data)
    markdown = await scrape(
        engine, fetching, _scrape(url, lamp_schema, "markdown").model_copy(update=recent), data=engine_data
    )

    assert again.capture_id == first.capture_id
    # The JSON is no page to render: the page is fetched.
    assert markdown.capture_id not in (None, first.capture_id)
    assert markdown.fetch is not None
    assert (markdown.fetch.method, web.page_fetches(), len(web.requested)) == ("http", [url], 1)
    assert markdown.markdown is not None
    assert "lights a desk" in markdown.markdown


async def test_max_age_reuses_no_api_capture_once_the_config_has_no_recipe(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    first = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)
    async with engine.begin() as conn:  # an operator's correction drops the recipe within `max_age`
        stripped = ExtractionConfig.ir.op("-")("api_recipe")
        await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == recipe_config).values(ir=stripped))

    again = await scrape(
        engine, fetching, _scrape(url, lamp_schema).model_copy(update={"max_age": 3600}), data=engine_data
    )

    # The JSON is read only by a recipe: the page is fetched, and its page steps run on the page itself.
    assert again.capture_id not in (None, first.capture_id)
    assert again.fetch is not None
    assert (again.fetch.method, web.page_fetches()) == ("http", [url])
    assert await _drift_window(engine, recipe_config) == {"title": [[True, True]]}


async def test_an_api_capture_replays_without_page_steps_once_the_config_has_no_recipe(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    first = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)
    async with engine.begin() as conn:  # an operator's correction drops the recipe
        stripped = ExtractionConfig.ir.op("-")("api_recipe")
        await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == recipe_config).values(ir=stripped))
    assert first.capture_id is not None

    replayed = await captures.replay(engine, fetching.store, engine_data, first.capture_id)

    # The capture is the JSON the recipe fetched: the config's page steps were never meant for it.
    assert [record.mode for record in replayed] == ["adhoc"]


async def test_an_endpoint_robots_txt_disallows_is_not_requested_and_the_page_is_fetched(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.pages[f"{own_origin}/robots.txt"] = b"User-agent: *\nDisallow: /api/\n"
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)

    assert result.fetch is not None
    assert (result.fetch.method, web.page_fetches(), web.requested) == ("http", [url], [])
    assert [(a.method, a.error) for a in result.fetch.attempts if a.method == "api"] == [("api", "robots")]
    assert result.records is not None
    assert result.records[0].fields["title"].value == "Lamp page"


def _admissions(fetching: Fetching) -> list[str]:
    """The hosts `fetching`'s limiter admits a request to from now on, in order."""
    admitted: list[str] = []
    admit = fetching.limiter.admit

    def recording(host: str, interval: timedelta) -> timedelta:
        wait = admit(host, interval)
        if not wait:
            admitted.append(host)
        return wait

    fetching.limiter.admit = recording  # type: ignore[method-assign]
    return admitted


async def test_an_endpoint_on_the_page_host_takes_the_page_turn_at_the_site_rate(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    # SPEC-02 §4.6: a page served by its endpoint alone is one request to the host, so one turn at its rate.
    url = f"{own_origin}/p/desk-lamp"
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    admitted = _admissions(fetching)

    await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)

    assert (admitted, len(web.requested)) == ([own_origin.removeprefix("https://")], 1)


async def test_an_endpoint_after_the_page_fetched_to_bind_waits_for_a_turn_of_its_own(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    # SPEC-09 §4.4: a binder that reads the page's JSON-LD fetches the page first; the endpoint is a second request.
    url = f"{own_origin}/p/desk-lamp"
    product = '<script type="application/ld+json">{"@type": "Product", "sku": "9001"}</script></head>'
    web.pages[url] = PAGE.replace(b"</head>", product.encode())
    web.endpoints[f"{own_origin}/api/sku/9001"] = PRODUCT
    recipe = {
        **_ir(own_origin, lamp_schema)["api_recipe"],
        "url": f"{own_origin}/api/sku/{{p1}}",
        "params_from_url": {"p1": "jsonld:$[0]['sku']"},
        "requires_page_fetch": True,
    }
    async with engine.begin() as conn:
        ir = {**_ir(own_origin, lamp_schema), "api_recipe": recipe}
        await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == recipe_config).values(ir=ir))
    admitted = _admissions(fetching)

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=engine_data)

    host = own_origin.removeprefix("https://")
    assert result.fetch is not None
    assert (result.fetch.method, web.page_fetches(), admitted) == ("api", [url], [host, host])
    assert result.records is not None
    assert result.records[0].fields["title"].value == "Desk Lamp"


# The worker's tasks.


async def _run(engine: AsyncEngine, handlers: dict[JobKind, TaskHandler], job_id: JobId) -> None:
    """Run a worker loop until the job has ended."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, handlers, stop, ending=close_run))
    async with asyncio.timeout(60):
        while not await _ended(engine, job_id):
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def _ended(engine: AsyncEngine, job_id: JobId) -> bool:
    async with engine.connect() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    return status in ("completed", "failed", "cancelled")


async def test_a_batch_task_of_a_site_with_a_recipe_is_served_over_its_api(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.pages[url] = PAGE
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    request = BatchScrapeRequest.model_validate(
        {"urls": [url], "formats": ["records"], "schema": {"id": str(lamp_schema.id)}, "page_kind": "detail"}
    )
    submitted = await submit_batch(engine, fetching.connector, request, data=engine_data)

    await _run(engine, {"batch_scrape": scrape_handler(fetching, engine_data, None, llm=None)}, submitted.job_id)

    data, candidates = await _stored(engine, submitted.job_id)
    assert (web.page_fetches(), len(web.requested)) == ([], 1)
    assert (data["title"], data["price"]) == ("Desk Lamp", {"amount": "19.5", "currency": "EUR"})
    assert candidates == [("price", "api", True), ("title", "api", True)]
    assert await _drift_window(engine, recipe_config) == {}


def _crawl(url: str, schema: SchemaDef, max_depth: int) -> CrawlRequest:
    rules = [{"pattern": f"{url.rsplit('/', 1)[0]}/*", "page_kind": "detail"}]
    return CrawlRequest.model_validate(
        {
            "url": url,
            "formats": ["records"],
            "schema": {"id": str(schema.id)},
            "page_kind_rules": rules,
            "max_depth": max_depth,
        }
    )


async def test_a_crawl_page_whose_links_are_followed_is_fetched_and_one_at_the_last_depth_is_served_over_the_api(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    # A crawl reads a page's links (SPEC-10 §4.5), which a JSON body does not have; at `max_depth` none are read.
    start, other = f"{own_origin}/p/desk-lamp", f"{own_origin}/p/other-lamp"
    web.pages[start] = PAGE
    web.pages[other] = PAGE
    web.endpoints[f"{own_origin}/api/products/other-lamp"] = PRODUCT
    submitted = await submit_crawl(engine, fetching.connector, _crawl(start, lamp_schema, 1), data=engine_data)

    await _run(engine, {"crawl": crawl_handler(fetching, engine_data, None, llm=None)}, submitted.job_id)

    # The start page over HTTP for its links; the page it leads to, at the last depth, over the API only.
    assert [url for url in web.page_fetches() if not url.endswith(".xml")] == [start]
    assert [r.url for r in web.requested] == [f"{own_origin}/api/products/other-lamp"]
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.url, Record.data)
            .join(Extraction, Extraction.url_task_id == UrlTask.id)
            .join(Record, Record.extraction_id == Extraction.id)
            .where(UrlTask.job_id == submitted.job_id)
        )
        titles = {row.url: row.data["title"] for row in rows}
    # The start page has no price, so a crawl keeps no record of it (`no_match`); the other page's is the API's.
    assert titles == {other: "Desk Lamp"}
