"""A site whose active config has an API recipe is served through it ("Adapter / API" rung): in a scrape, and in the
worker's `batch_scrape` and `crawl` tasks. A URL a custom recipe's pattern matches is served by that recipe, any other
by the learned config. The recipe's request goes
through robots.txt and the site's rate like the page's would; its values are `api` candidates in the
`adapter` bucket; a page the recipe serves joins no drift window, which measures the config's page steps."""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.config_ir.activation import store_recipe
from crawlerai.config_ir.custom_recipe import CustomRecipe
from crawlerai.config_ir.progressive import StateKey
from crawlerai.db.models import (
    ExtractionConfig,
    ExtractionConfigId,
    SiteId,
)
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from tests.db.support import Web as SharedWeb

pytestmark = pytest.mark.anyio

# The page's heading is not the product's name, so a value read from the page and one from the API differ.
PAGE = b"""<!doctype html><html lang="en"><head><title>Lamps</title></head>
<body><main><h1>Lamp page</h1><p>A lamp that lights a desk.</p><a href="/p/other-lamp">Another lamp</a></main></body>
</html>"""
# The API's answer states the product it was asked for (its slug), as the identity check requires.
PRODUCT = {"data": {"slug": "desk-lamp", "name": "Desk Lamp", "price": 19.5, "currency": "EUR"}}


@dataclass
class Web(SharedWeb):
    """`SharedWeb` with each endpoint of `endpoints` answering as JSON; any other is a 404."""

    endpoints: dict[str, object] = field(default_factory=dict)
    requested: list[JsonRequest] = field(default_factory=list)

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request)
        if request.url not in self.endpoints:
            return self.fetch_result(request.page_url, 404, b"{}", block_class="not_found", method="api")
        body = json.dumps(self.endpoints[request.url]).encode()
        return self.fetch_result(request.page_url, 200, body, method="api")

    def rungs(self) -> Rungs:
        return replace(super().rungs(), json=self.json)


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web.site(fetch_result, own_origin)


def _ir(origin: str, schema: SchemaDef) -> dict[str, Any]:
    """A config that reads the title from the page's heading, with a recipe that reads both fields from the API."""
    return {
        "ir_version": "1",
        "site": origin.removeprefix("https://"),
        "schema": {"name": schema.name, "digest": document_digest(schema)},
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
    engine: AsyncEngine, own_origin: str, site: SiteId, kettle_schema: SchemaDef
) -> ExtractionConfigId:
    """The site's active config for the schema, with its API recipe."""
    values = {
        "site_id": site,
        "schema_id": kettle_schema.id,
        "page_kind": "detail",
        "version": 1,
        "status": "active",
        "ir": _ir(own_origin, kettle_schema),
        "origin": "induced",
        "field_status": {"title": "corroborated"},
    }
    async with engine.begin() as conn:
        config_id = (
            await conn.execute(insert(ExtractionConfig).values(values).returning(ExtractionConfig.id))
        ).scalar_one()
    return config_id


async def _drift_window(engine: AsyncEngine, config_id: uuid.UUID) -> object:
    async with engine.connect() as conn:
        query = select(ExtractionConfig.drift_window).where(ExtractionConfig.id == config_id)
        return (await conn.execute(query)).scalar_one()


# The scrape service.


def _scrape(url: str, schema: SchemaDef, *formats: str, **fields: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate(
        {
            "url": url,
            "formats": ["records", *formats],
            "schema": {"id": str(schema.id)},
            "page_kind": "detail",
            **fields,
        }
    )


async def test_a_scrape_of_a_site_with_a_recipe_is_served_over_its_api(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.serve(url, PAGE)
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT

    result = await scrape(engine, fetching, _scrape(url, kettle_schema), data=engine_data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method) == ("extracted", "api")
    assert web.page_fetches() == []  # no HTML page, no browser
    assert [(r.url, r.page_url) for r in web.requested] == [(f"{own_origin}/api/products/desk-lamp", url)]
    assert result.records is not None
    (record,) = result.records
    title, price = record.fields["title"], record.fields["price"]
    assert (record.mode, title.value, title.source_kind, title.evidence) == ("config", "Desk Lamp", "api", "adapter")
    assert title.locator == f"api:{recipe_config}:$['data']['name']"
    assert price.value == {"amount": 19.5, "currency": "EUR"}
    # The page steps did not run on the JSON, so their window shows nothing of them.
    assert await _drift_window(engine, recipe_config) == {}


async def test_an_endpoint_robots_txt_disallows_is_not_requested_and_the_page_is_fetched(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    recipe_config: uuid.UUID,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/p/desk-lamp"
    web.serve(url, PAGE)
    web.robots(own_origin, b"User-agent: *\nDisallow: /api/\n")
    web.endpoints[f"{own_origin}/api/products/desk-lamp"] = PRODUCT
    obeying = _scrape(url, kettle_schema, fetch={"respect_robots": True})

    result = await scrape(engine, fetching, obeying, data=engine_data)

    assert result.fetch is not None
    assert (result.fetch.method, web.page_fetches(), web.requested) == ("http", [("http", url)], [])
    assert [(a.method, a.error) for a in result.fetch.attempts if a.method == "api"] == [("api", "robots")]
    assert result.records is not None
    assert result.records[0].fields["title"].value == "Lamp page"


# The worker's tasks.


# Selection by URL.


@pytest.fixture
async def custom_recipe(
    engine: AsyncEngine, own_origin: str, site: SiteId, kettle_schema: SchemaDef, recipe_config: ExtractionConfigId
) -> ExtractionConfigId:
    """Beside the learned `recipe_config`, a custom recipe for the URLs `/item/{slug}`, served by another endpoint."""
    host = own_origin.removeprefix("https://")
    recipe = CustomRecipe.model_validate(
        {
            "schema_id": kettle_schema.id,
            "page_kind": "detail",
            "patterns": [f"{host}/item/{{slug}}"],
            "main": {
                "method": "GET",
                "url": f"{own_origin}/api/items/{{p1}}",
                "params_from_url": {"p1": "path:1"},
                "map": {"title": "$['data']['name']", "price": "$['data']['price']+$['data']['currency']"},
            },
        }
    )
    ir = recipe.to_ir(kettle_schema, at=datetime(2026, 10, 1, tzinfo=UTC), engine_version="t")
    async with engine.begin() as conn:
        return await store_recipe(conn, StateKey(site, kettle_schema.id, "detail"), ir, replaces=None)


async def test_a_url_a_recipes_pattern_matches_is_served_by_it_and_any_other_by_the_learned_config(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    recipe_config: uuid.UUID,
    custom_recipe: uuid.UUID,
    engine_data: EngineData,
) -> None:
    item, about = f"{own_origin}/item/desk-lamp", f"{own_origin}/about"
    web.serve(item, PAGE)
    web.serve(about, PAGE)
    web.endpoints[f"{own_origin}/api/items/desk-lamp"] = PRODUCT

    served = await scrape(engine, fetching, _scrape(item, kettle_schema), data=engine_data)
    learned = await scrape(engine, fetching, _scrape(about, kettle_schema), data=engine_data)

    assert served.fetch is not None
    assert served.records is not None
    assert served.fetch.method == "api"
    assert served.records[0].fields["title"].locator == f"api:{custom_recipe}:$['data']['name']"
    # The learned config's recipe binds nothing on `/about`, so its page steps read the page.
    assert learned.fetch is not None
    assert learned.records is not None
    assert (learned.fetch.method, web.page_fetches()) == ("http", [("http", about)])
    title = learned.records[0].fields["title"]
    # The recipe has no page steps: the learned config's read the heading.
    assert (learned.records[0].mode, title.value, title.locator) == (
        "config",
        "Lamp page",
        "config:title:0:normalize-space(//h1)",
    )
    assert [r.url for r in web.requested] == [f"{own_origin}/api/items/desk-lamp"]
