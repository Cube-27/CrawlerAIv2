"""Engineer captures over HTTP: `POST /v1/captures` renders a sample page keeping every call, stores it and its record;
its calls are listed by endpoint (`GET /v1/captures/{id}/calls`, merged across samples by `POST /v1/recipes/calls`),
read one by one, and exported as HAR. The browser is a stand-in whose page made one call to the site's API."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetching import Fetching
from crawlerai.storage.capture_bundle import NetworkBody
from tests.db.support import Web, api
from tests.support.captures import call, fetched

pytestmark = pytest.mark.anyio


def _page(name: str) -> bytes:
    offers = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    node = {"@context": "https://schema.org", "@type": "Product", "name": name, "offers": offers}
    return (
        f'<!doctype html><html lang="en"><head><title>{name}</title>'
        f'<script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><main><h1>{name}</h1><p>{name} boils water quickly and quietly.</p></main></body></html>"
    ).encode()


@pytest.fixture
def fetch_result() -> Callable[..., FetchResult]:
    """A rung's result; a browser fetch keeping every call (`calls` `all`) also holds the call the page made to the
    site's API for its product, whose name is the page's."""

    def result(url: str, status: int, body: bytes, *args: Any, **kwargs: Any) -> FetchResult:
        policy: FetchPolicy = kwargs["policy"]
        network: tuple[tuple[NetworkBody, bytes], ...] = ()
        if kwargs["method"] == "browser" and policy.calls == "all":
            name = body.split(b"<h1>")[1].split(b"</h1>")[0].decode() if b"<h1>" in body else "Unnamed kettle"
            answer = json.dumps({"product": {"title": name, "id": url.rsplit("/", 1)[1]}}).encode()
            network = (call(0, f"{url.rsplit('/', 2)[0]}/api/product?slug=x", answer, method="GET", same_site=True),)
        return fetched(url, status, body, *args, network=network, **kwargs)

    return result


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch, engine: AsyncEngine, fetching: Fetching, engine_data: EngineData
) -> AsyncIterator[httpx.AsyncClient]:
    async with api(engine) as (app, client):
        app.state.runtime = replace(app.state.runtime, fetching=fetching, engine_data=engine_data)
        yield client


async def _capture(client: httpx.AsyncClient, web: Web, url: str, name: str, schema: SchemaDef) -> dict[str, Any]:
    web.serve(url, _page(name))
    response = await client.post(
        "/v1/captures",
        json={
            "url": url,
            "schema_id": str(schema.id),
            "page_kind": "detail",
            "actions": [{"type": "click", "selector": "#more"}],
        },
    )
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


async def test_a_capture_renders_its_page_and_lists_reads_and_exports_its_calls(
    client: httpx.AsyncClient, web: Web, own_origin: str, kettle_schema: SchemaDef
) -> None:
    url = f"{own_origin}/p/blue"

    captured = await _capture(client, web, url, "Blue kettle", kettle_schema)

    assert web.page_fetches() == [("browser", url)]
    assert (captured["url"], captured["outcome"]) == (url, "extracted")
    assert [attempt["method"] for attempt in captured["attempts"]] == ["browser"]
    assert captured["records"][0]["fields"]["title"]["value"] == "Blue kettle"
    capture_id = captured["capture_id"]

    listed = (await client.get(f"/v1/captures/{capture_id}/calls")).json()
    assert (listed["schema_id"], listed["samples"]) == (str(kettle_schema.id), [capture_id])
    [endpoint] = listed["endpoints"]
    assert (endpoint["method"], endpoint["origin"], endpoint["query"]) == ("GET", own_origin, ["slug"])
    assert [(c["index"], c["same_site"], c["status"]) for c in endpoint["calls"]] == [(0, True, 200)]
    title = next(match for match in endpoint["fields"] if match["field"] == "title")
    assert title == {
        "field": "title",
        "published": True,
        "paths": [{"path": "$['product']['title']", "samples": 1}],
        "in_text": 0,
    }

    one = (await client.get(f"/v1/captures/{capture_id}/calls/0")).json()
    assert (one["method"], one["url"], json.loads(one["answer"])["product"]["title"]) == (
        "GET",
        f"{own_origin}/api/product?slug=x",
        "Blue kettle",
    )
    assert (await client.get(f"/v1/captures/{capture_id}/calls/1")).status_code == 404

    exported = await client.get(f"/v1/captures/{capture_id}/calls.har")
    assert exported.headers["content-type"] == "application/json"
    log = exported.json()["log"]
    assert [entry["request"]["url"] for entry in log["entries"]] == [url, f"{own_origin}/api/product?slug=x"]


async def test_samples_calls_are_merged_by_endpoint_counting_the_samples_that_read_each_field(
    client: httpx.AsyncClient, web: Web, own_origin: str, kettle_schema: SchemaDef
) -> None:
    first = await _capture(client, web, f"{own_origin}/p/blue", "Blue kettle", kettle_schema)
    second = await _capture(client, web, f"{own_origin}/p/red", "Red kettle", kettle_schema)
    ids = [first["capture_id"], second["capture_id"]]

    merged = await client.post("/v1/recipes/calls", json={"capture_ids": ids})

    assert merged.status_code == 200, merged.text
    [endpoint] = merged.json()["endpoints"]
    assert endpoint["samples"] == ids
    title = next(match for match in endpoint["fields"] if match["field"] == "title")
    assert title["paths"] == [{"path": "$['product']['title']", "samples": 2}]
    twice = await client.post("/v1/recipes/calls", json={"capture_ids": [ids[0], ids[0]]})
    assert twice.status_code == 422


async def test_a_capture_the_engine_read_no_record_from_lists_the_paths_of_each_field_s_type(
    client: httpx.AsyncClient, web: Web, own_origin: str, kettle_schema: SchemaDef
) -> None:
    url = f"{own_origin}/p/shell"
    web.serve(url, b"<!doctype html><html><body><div id='app'></div></body></html>")
    body = {"url": url, "schema_id": str(kettle_schema.id), "page_kind": "detail"}
    captured = (await client.post("/v1/captures", json=body)).json()
    assert captured["records"] == []

    listed = (await client.get(f"/v1/captures/{captured['capture_id']}/calls")).json()

    [endpoint] = listed["endpoints"]
    title = next(match for match in endpoint["fields"] if match["field"] == "title")
    assert (title["published"], title["paths"][0]) == (False, {"path": "$['product']['title']", "samples": 1})
