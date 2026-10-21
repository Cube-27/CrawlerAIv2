"""`POST /v1/scrape` over HTTP (rest-api spec): what a client sends and gets back. What a scrape does is the
service's (`test_scrape_service.py`)."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.llm.client import MeteredClient, ProviderReply
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services.fetching import Fetching
from tests.db.support import PRIVATE_HOST, TITLE, Web, api
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

PAGE = b"""<!doctype html><html lang="en"><head><title>Blue kettle</title></head>
<body><h1>Blue kettle</h1><a href="/kettles/red">Red kettle</a></body></html>"""
DRAFT_REPLY = ProviderReply(
    model="fake-strong",
    text=json.dumps(
        to_wire(
            {
                "page_kind": "detail",
                "fields": {"title": {"type": "text", "required": True, "description": "Product name"}},
            }
        )
    ),
    tokens_in=900,
    tokens_out=80,
)


@pytest.fixture
def provider() -> FakeProvider | None:
    """The LLM provider the app's client asks: one role S draft, scripted. None keeps the app's own client."""
    return FakeProvider([DRAFT_REPLY])


@pytest.fixture
def data(engine_data: EngineData) -> EngineData | None:
    """The engine data `records` reads; None stands for a process without the data files."""
    return engine_data


@pytest.fixture
async def client(
    app_env: pytest.MonkeyPatch,
    engine: AsyncEngine,
    fetching: Fetching,
    provider: FakeProvider | None,
    data: EngineData | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """The app with no LLM provider key, fetching `web`, its client asking `provider`."""
    app_env.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    async with api(engine) as (app, client):
        app.state.fetching = fetching
        app.state.engine_data = data
        if provider is not None:
            app.state.llm = MeteredClient([provider], engine)
        yield client


async def _post(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/v1/scrape", json=body)


async def test_answers_the_requested_formats_and_only_those(
    client: httpx.AsyncClient, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.serve(url, PAGE)

    response = await _post(client, {"url": url, "formats": ["links", "metadata"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        *("job_id", "capture_id", "url", "final_url", "fetched_at", "outcome", "reason", "fetch", "usage"),
        *("links", "metadata"),
    }
    assert (body["url"], body["final_url"], body["outcome"], body["reason"]) == (url, url, "extracted", None)
    assert body["links"] == [f"{own_origin}/kettles/red"]
    assert body["metadata"] == {
        "title": "Blue kettle",
        "description": None,
        "language": "en",
        "canonical": None,
        "og": {},
        "structured_data_types": [],
    }
    assert body["fetch"] == {
        "method": "http",
        "status_code": 200,
        "block_class": "ok",
        "adapter": None,
        "attempts": [
            {
                "method": "http",
                "status": 200,
                "block_class": "ok",
                "duration_ms": 1,
                "error": None,
                "challenge": None,
                "steps": [],
            }
        ],
    }
    assert body["usage"] == {
        "llm_calls": 0,
        "llm_tokens_in": 0,
        "llm_tokens_out": 0,
        "browser_seconds": 0,
        "http_requests": 1,
    }


async def test_a_private_target_is_an_ssrf_problem(client: httpx.AsyncClient) -> None:
    response = await _post(client, {"url": f"https://{PRIVATE_HOST}/", "formats": ["markdown"]})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "ssrf_rejected",
        "detail": "ssrf_rejected: private_address",
    }


async def test_a_prompt_returns_its_draft_and_reuses_it(
    client: httpx.AsyncClient, web: Web, own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.serve(url, PAGE)
    body = {"url": url, "formats": ["links"], "schema": {"prompt": prompt}}

    first, second = await _post(client, body), await _post(client, body)

    assert (first.status_code, second.status_code) == (200, 200), first.text
    schema = first.json()["schema"]
    assert {k: schema[k] for k in ("name", "origin", "status", "page_kind")} == {
        "name": draft_name(prompt),
        "origin": "prompt_draft",
        "status": "active",
        "page_kind": "detail",
    }
    assert list(schema["fields"]) == ["title"]
    assert second.json()["schema"] == schema
    assert (first.json()["usage"]["llm_calls"], second.json()["usage"]["llm_calls"]) == (1, 0)


# --- records (§4.4) ---

# §13.1's six attributes, plus `reason`, `source_kind` and `derived_by` from `field_meta` (§4.4).
FIELD_MEMBERS = {
    "value",
    "status",
    "evidence",
    "confidence",
    "calibrated",
    "locator",
    "reason",
    "source_kind",
    "derived_by",
}


def _product_page(url: str) -> bytes:
    node = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Blue kettle",
        "url": url,
        "offers": {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"},
    }
    return PAGE.replace(b"</head>", f'<script type="application/ld+json">{json.dumps(node)}</script></head>'.encode())


def _records(url: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"url": url, "formats": ["markdown", "records"], "schema": schema, "page_kind": "detail"}


async def test_records_answer_every_field_with_its_attributes(
    client: httpx.AsyncClient, web: Web, own_origin: str, kettle_schema: SchemaDef
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.serve(url, _product_page(url))

    response = await _post(client, _records(url, {"id": str(kettle_schema.id)}))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "extracted"
    assert "Blue kettle" in body["markdown"]
    (record,) = body["records"]
    assert {k: record[k] for k in ("mode", "complete", "confidence")} == {
        "mode": "adhoc",
        "complete": True,
        "confidence": None,
    }
    assert record["fields"]["price"] == {
        "value": {"amount": "19.90", "currency": "EUR"},
        "status": "published",
        "reason": None,
        "evidence": "structured",
        "confidence": None,
        "calibrated": False,
        "source_kind": "jsonld",
        "locator": record["fields"]["price"]["locator"],
        "derived_by": None,
    }
    assert [set(field) for field in record["fields"].values()] == [FIELD_MEMBERS, FIELD_MEMBERS]


async def test_an_inline_schema_that_differs_from_its_stored_name_is_a_conflict(
    client: httpx.AsyncClient, own_origin: str, kettle_schema: SchemaDef
) -> None:
    inline = {"name": kettle_schema.name, "page_kind": "detail", "fields": {"title": TITLE}}

    response = await _post(client, _records(f"{own_origin}/kettles/blue", {"inline": inline}))

    assert response.status_code == 409
    assert response.json()["type"] == "conflict"
