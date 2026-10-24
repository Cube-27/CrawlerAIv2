"""A page an active adapter detects is served through the platform's API: in a scrape, and in the
worker's `batch_scrape` task. The API request goes through robots.txt and the site's rate like the page's would; a
page the adapter does not serve (an answer without the platform's signal, an endpoint robots.txt disallows) is
fetched as a page. A storefront collection is page-scoped: its page is fetched first and stays the capture, joined
with the API's answer for the products it links to; a card's visible amount is weighed against the answer's. The
adapter's values are `adapter` candidates in the `adapter` bucket."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.acquire.api import JsonRequest
from snowcrawl.acquire.rungs import Rungs, adapter_registry
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.resolve.pipeline import EngineData
from snowcrawl.schemas import registry
from snowcrawl.schemas.types import SchemaDef, SchemaDocument
from snowcrawl.services.fetching import Fetching
from snowcrawl.services.scrape import ScrapeRequest, scrape
from tests.db.support import PRICE, TITLE
from tests.db.support import Web as SharedWeb

pytestmark = pytest.mark.anyio

API_VERSION = "2026-10"
URL = {"type": "url", "required": True, "description": "The product page the row links to", "schema_org": "Product.url"}
# Three products, each a card that shows its tax-inclusive amount; the API states the catalogue (tax-exclusive) one.
LAMPS = (
    ("desk-lamp", "Desk Lamp", "19.50", "23.40"),
    ("wall-lamp", "Wall Lamp", "30.00", "36.00"),
    ("floor-lamp", "Floor Lamp", "50.00", "60.00"),
)
CARDS = "".join(
    f'<li class="card"><a href="/products/{handle}"><h3>{title}</h3></a><span class="price">€{shown}</span></li>'
    for handle, title, _, shown in LAMPS
)
PAGE = f"""<!doctype html><html lang="en"><head><title>Lamps</title></head>
<body><main><h1>Lamps</h1><ul>{CARDS}</ul><a rel="next" href="?page=2">Next</a></main></body></html>""".encode()


def _node(handle: str, title: str, amount: str, own_origin: str) -> dict[str, Any]:
    money = {"amount": amount, "currencyCode": "EUR"}
    return {
        "handle": handle,
        "title": title,
        "onlineStoreUrl": f"{own_origin}/products/{handle}",
        "priceRange": {"minVariantPrice": money, "maxVariantPrice": money},
    }


def _answer(own_origin: str) -> dict[str, Any]:
    nodes = [_node(handle, title, amount, own_origin) for handle, title, amount, _ in LAMPS]
    shop = {"paymentSettings": {"enabledPresentmentCurrencies": ["EUR"]}}
    return {"data": {"shop": shop, "collection": {"products": {"nodes": nodes}}}}


@dataclass
class Web(SharedWeb):
    """`SharedWeb` with the storefront endpoint, which answers with `endpoint` and, when `platform`, the platform's
    version header, or fails with `status`."""

    endpoint: dict[str, Any] = field(default_factory=dict)
    platform: bool = True
    status: int = 200
    requested: list[str] = field(default_factory=list)

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request.url)
        headers = (("X-Shopify-API-Version", API_VERSION),) if self.platform else ()
        if self.status != 200:
            # `Retry-After: 0` asks for no pause, so the page's fallback goes without the first backoff's wait.
            headers = (("Retry-After", "0"),)
            return self.fetch_result(
                request.page_url, self.status, b"", headers, block_class="blocked", method="api", final_url=request.url
            )
        body = json.dumps(self.endpoint).encode()
        return self.fetch_result(request.page_url, 200, body, headers, method="api", final_url=request.url)

    def rungs(self) -> Rungs:
        return replace(super().rungs(), adapters=adapter_registry(()), json=self.json)


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web.site(fetch_result, own_origin, endpoint=_answer(own_origin))


@pytest.fixture
def data(engine_data: EngineData, fetching: Fetching) -> EngineData:
    return replace(engine_data, adapters=fetching.rungs.adapters)


@pytest.fixture
async def lamp_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    fields = {"title": TITLE, "url": URL, "price": PRICE}
    document = {"name": schema_name, "page_kind": "listing", "fields": fields}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def _scrape(url: str, schema: SchemaDef, **fields: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate(
        {
            "url": url,
            "formats": ["records", "links"],
            "schema": {"id": str(schema.id)},
            "page_kind": "listing",
            **fields,
        }
    )


async def test_a_storefront_collection_page_is_joined_with_its_answer_and_shows_its_cards_prices(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    url = f"{own_origin}/collections/lamps"
    web.serve(url, PAGE)

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method, web.page_fetches()) == ("extracted", "http", [("http", url)])
    assert web.requested == [f"{own_origin}/api/{API_VERSION}/graphql.json"]
    # The page stays the capture, with its next-page link for the crawl to follow.
    assert f"{url}?page=2" in (result.links or [])
    assert result.records is not None
    by_title = {str(record.fields["title"].value): record.fields for record in result.records}
    assert sorted(by_title) == sorted(title for _, title, _, _ in LAMPS)
    for _, title, _, shown in LAMPS:
        fields = by_title[title]
        # The page keeps its markup: the card's visible amount publishes over the answer's, flagged (#334).
        price = {"amount": float(shown), "currency": "EUR"}  # served as a JSON number
        assert (fields["price"].value, fields["price"].reason) == (price, "disagree")
        assert fields["title"].source_kind == "adapter"


async def test_a_collection_redirected_to_its_www_host_is_joined_with_that_host_answer(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    # A redirect within the site (apex to `www`): the page's links are on the `www` host, which the API is asked on.
    www = own_origin.replace("://", "://www.", 1)
    url = f"{own_origin}/collections/lamps"
    web.redirects[url] = f"{www}/collections/lamps"
    web.serve(f"{www}/collections/lamps", PAGE)
    web.endpoint = _answer(www)

    result = await scrape(engine, fetching, _scrape(url, lamp_schema), data=data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method) == ("extracted", "http")
    assert web.requested == [f"{www}/api/{API_VERSION}/graphql.json"]
    assert result.records is not None
    assert {record.fields["title"].source_kind for record in result.records} == {"adapter"}


async def test_a_collection_page_robots_txt_disallows_is_neither_fetched_nor_asked_of_its_api(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, lamp_schema: SchemaDef, data: EngineData
) -> None:
    # A page-scoped adapter serves a fetched page only, so a page robots.txt disallows is not served.
    url = f"{own_origin}/collections/lamps"
    web.serve(url, PAGE)
    web.robots(own_origin, b"User-agent: *\nDisallow: /collections/\n")

    obeying = _scrape(url, lamp_schema, fetch={"respect_robots": True})
    result = await scrape(engine, fetching, obeying, data=data)

    assert (result.outcome, result.fetch, web.requested, web.page_fetches()) == ("blocked", None, [], [])
