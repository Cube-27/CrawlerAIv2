"""A page an active adapter detects is served through the platform's API (SPEC-15 §4.6 to §4.8): in a scrape, and in the
worker's `batch_scrape` task. The API request goes through robots.txt and the site's rate like the page's would; a
page the adapter does not serve (an answer without the platform's signal, an endpoint robots.txt disallows) is
fetched as a page. The adapter's values are `adapter` candidates in the `adapter` bucket.

The web is a stub that answers synthetic pages and storefront answers on RFC 2606 hosts: no network.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs, adapter_registry
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.settings import Settings
from crawlerai.db.models import Job, JobId, JobKind, Record, SiteId
from crawlerai.recurring.listing_diff import close_run
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler, run_worker
from tests.db.conftest import resolve

pytestmark = pytest.mark.anyio

API_VERSION = "2026-10"
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}
PAGE = b"""<!doctype html><html lang="en"><head><title>Lamps</title></head>
<body><main><h1>Lamp page</h1><p>A lamp that lights a desk.</p></main></body></html>"""
ANSWER = {
    "data": {
        "shop": {"paymentSettings": {"enabledPresentmentCurrencies": ["EUR"]}},
        "collection": {
            "products": {
                "nodes": [
                    {
                        "id": "gid://shopify/Product/1",
                        "title": "Desk Lamp",
                        "priceRange": {
                            "minVariantPrice": {"amount": "19.50", "currencyCode": "EUR"},
                            "maxVariantPrice": {"amount": "19.50", "currencyCode": "EUR"},
                        },
                    }
                ]
            }
        },
    }
}


@dataclass
class Web:
    """Answers each URL from `pages` over HTTP, and the storefront endpoint with `answer` and, when `platform`, the
    platform's version header. The browser renders a page as it is served (`rendered` lists the URLs): a listing page
    the page rungs fetch gives no rows, so it is rendered once (owner #54)."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, bytes] = field(default_factory=dict)
    answer: dict[str, Any] = field(default_factory=lambda: ANSWER)
    platform: bool = True
    status: int = 200
    fetched: list[str] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.fetched.append(url)
        if url not in self.pages:
            return self.fetch_result(url, 404, b"gone", block_class="not_found")
        return self.fetch_result(url, 200, self.pages[url])

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.rendered.append(url)
        if url not in self.pages:
            return self.fetch_result(url, 404, b"gone", block_class="not_found", method="browser")
        return self.fetch_result(url, 200, self.pages[url], method="browser")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request.url)
        headers = (("X-Shopify-API-Version", API_VERSION),) if self.platform else ()
        if self.status != 200:
            # `Retry-After: 0` asks for no pause, so the page's fallback goes without the first backoff's wait.
            headers = (("Retry-After", "0"),)
            return self.fetch_result(
                request.page_url, self.status, b"", headers, block_class="blocked", method="api", final_url=request.url
            )
        body = json.dumps(self.answer).encode()
        return self.fetch_result(request.page_url, 200, body, headers, method="api", final_url=request.url)

    def page_fetches(self) -> list[str]:
        return [url for url in self.fetched if not url.endswith("/robots.txt")]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": b"User-agent: *\nAllow: /\n"})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.http, browser=web.browser, adapters=adapter_registry(()), json=web.json)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
def data(engine_data: EngineData, fetching: Fetching) -> EngineData:
    return replace(engine_data, adapters=fetching.rungs.adapters)


@pytest.fixture
async def lamp_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "page_kind": "listing", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def _scrape(url: str, schema: SchemaDef) -> ScrapeRequest:
    return ScrapeRequest.model_validate(
        {"url": url, "formats": ["records"], "schema": {"id": str(schema.id)}, "page_kind": "listing"}
    )


async def test_a_scrape_of_a_storefront_collection_is_served_over_the_platform_api(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method, web.page_fetches()) == ("extracted", "api", [])
    assert web.requested == [f"{own_origin}/api/{API_VERSION}/graphql.json"]
    assert result.records is not None
    (record,) = result.records
    title, price = record.fields["title"], record.fields["price"]
    assert (title.value, title.source_kind, title.evidence) == ("Desk Lamp", "adapter", "adapter")
    assert title.locator == "adapter:shopify:$['data']['collection']['products']['nodes'][0]['title']"
    assert price.value == {"amount": "19.50", "currency": "EUR"}


async def test_a_collection_url_with_a_query_its_canonical_drops_is_served_over_the_platform_api(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    # SPEC-15 §4.2: the page names the collection without the query as its canonical (RFC 6596).
    canonical = f"{own_origin}/collections/lamps"
    url = f"{canonical}?ref=footer"
    web.pages[url] = PAGE.replace(b"</title>", f'</title><link rel="canonical" href="{canonical}">'.encode())

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method, web.page_fetches()) == ("extracted", "api", [url])
    # The page gives no rows, so it is rendered once (owner #54) before the adapter serves its canonical URL.
    assert [(a.method, a.status) for a in result.fetch.attempts] == [("http", 200), ("browser", 200), ("api", 200)]
    assert result.records is not None
    assert [record.fields["title"].value for record in result.records] == ["Desk Lamp"]


async def test_a_page_of_a_host_that_is_not_the_platform_is_fetched_as_a_page_and_the_host_declined(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    # INV-40.
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE
    web.platform = False

    first = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)
    second = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert first.fetch is not None
    assert second.fetch is not None
    assert (first.fetch.method, second.fetch.method) == ("http", "http")
    assert (len(web.requested), web.page_fetches()) == (1, [url, url])
    assert [(a.method, a.error) for a in first.fetch.attempts] == [
        ("api", "not_platform"),
        ("http", None),
        ("browser", None),  # a listing without rows, rendered once to no better effect (owner #54)
    ]


@pytest.mark.parametrize("status", [429, 502])
async def test_an_endpoint_that_cannot_answer_now_leaves_the_page_to_the_page_rungs_and_declines_no_host(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    lamp_schema: SchemaDef,
    data: EngineData,
    status: int,
) -> None:
    # SPEC-15 §4.9: a slow-down or a server error says nothing of the platform; the page falls back on its turn.
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE
    web.status = status

    first = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)
    second = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert first.fetch is not None
    assert (first.outcome, first.fetch.method, first.fetch.block_class) == (
        "partial",
        "http",
        "ok",
    )  # no price on the page
    assert [(a.method, a.status, a.error) for a in first.fetch.attempts] == [
        ("api", status, None),
        ("http", 200, None),
        ("browser", 200, None),  # a listing without rows, rendered once to no better effect (owner #54)
    ]
    assert (len(web.requested), web.page_fetches()) == (2, [url, url])
    assert second.fetch is not None


async def test_an_endpoint_robots_txt_disallows_is_not_requested_and_the_page_is_fetched(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE
    web.pages[f"{own_origin}/robots.txt"] = b"User-agent: *\nDisallow: /api/\n"

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert result.fetch is not None
    assert (result.fetch.method, web.requested, web.page_fetches()) == ("http", [], [url])


async def test_a_page_robots_txt_disallows_is_served_by_its_adapter_and_never_fetched(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    # SPEC-15 §4.6: the adapter requests its endpoint, which robots.txt allows; the page itself is not requested, and
    # when the endpoint does not serve it, the page rungs are not admitted either.
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE
    web.pages[f"{own_origin}/robots.txt"] = b"User-agent: *\nDisallow: /collections/\n"

    served = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)
    web.platform = False
    unserved = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert served.fetch is not None
    assert (served.outcome, served.fetch.method) == ("extracted", "api")
    assert (unserved.outcome, unserved.fetch) == ("blocked", None)
    assert (len(web.requested), web.page_fetches()) == (2, [])


async def _run_job(engine: AsyncEngine, fetching: Fetching, data: EngineData, job_id: JobId) -> None:
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    handlers: dict[JobKind, TaskHandler] = {"batch_scrape": scrape_handler(fetching, data, None, llm=None)}
    loop = asyncio.create_task(run_worker(settings, handlers, stop, ending=close_run))
    async with asyncio.timeout(60):
        while True:
            async with engine.connect() as conn:
                status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
            if status in ("completed", "failed", "cancelled"):
                break
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def test_a_batch_task_of_a_storefront_collection_is_served_over_the_platform_api(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    site: SiteId,
    lamp_schema: SchemaDef,
    data: EngineData,
) -> None:
    url = f"{own_origin}/collections/lamps"
    web.pages[url] = PAGE
    request = BatchScrapeRequest.model_validate(
        {"urls": [url], "formats": ["records"], "schema": {"id": str(lamp_schema.id)}, "page_kind": "listing"}
    )
    submitted = await submit_batch(engine, fetching.connector, request, data=data)

    await _run_job(engine, fetching, data, submitted.job_id)

    async with engine.connect() as conn:
        query = select(Record.data).where(Record.job_id == submitted.job_id)
        record: dict[str, Any] = (await conn.execute(query)).scalar_one()
    assert (web.page_fetches(), len(web.requested)) == ([], 1)
    assert (record["title"], record["price"]) == ("Desk Lamp", {"amount": "19.50", "currency": "EUR"})
