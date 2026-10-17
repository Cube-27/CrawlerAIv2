"""`POST /v1/scrape` over HTTP (SPEC-07 §4.4, §4.8): what a client sends and gets back. What a scrape does is the
service's (`test_scrape_service.py`).

The app runs with its real settings against the test database; its fetching is replaced by a stub web of synthetic
pages on RFC 2606 hosts and a stub resolver, so nothing leaves the process.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.db.keys import create_key
from crawlerai.db.models import ApiKey, Job
from crawlerai.llm.client import MeteredClient, ProviderError, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services.fetching import Fetching
from crawlerai.storage.fs import FsStore
from tests.db.conftest import LISTING_FIELDS, listing_page

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
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
async def database(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[AsyncEngine]:
    """The app's settings pointed at the test database, with no LLM provider key. `engine` deletes the jobs
    afterwards; the keys a test added are deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    monkeypatch.setenv("CRAWLERAI_LLM_PROVIDERS", "anthropic")
    keys_engine = create_async_engine(database_url)
    async with keys_engine.connect() as conn:
        keys = set((await conn.execute(select(ApiKey.id))).scalars())
    yield engine
    async with keys_engine.begin() as conn:
        await conn.execute(delete(ApiKey).where(ApiKey.id.not_in(keys)))
    await keys_engine.dispose()


@pytest.fixture
def pages(own_origin: str) -> dict[str, tuple[int, bytes]]:
    return {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")}


@pytest.fixture
def fetching(fetch_result: Callable[..., FetchResult], pages: dict[str, tuple[int, bytes]], tmp_path: Path) -> Fetching:
    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        if url.endswith("/slow"):
            await asyncio.sleep(5)
        status, body = pages.get(url, (404, b""))
        return fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found", policy=policy)

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    store = FsStore(tmp_path / "objects")
    return Fetching(Rungs(http=http, browser=http), SafeConnector(resolve), store, HostLimiter())


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
    database: AsyncEngine, fetching: Fetching, provider: FakeProvider | None, data: EngineData | None
) -> AsyncIterator[httpx.AsyncClient]:
    async with database.begin() as conn:
        key = await create_key(conn, "scrape-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        app.state.fetching = fetching
        app.state.engine_data = data
        if provider is not None:
            app.state.llm = MeteredClient([provider], database)
        yield client


async def _post(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/v1/scrape", json=body)


async def test_answers_the_requested_formats_and_only_those(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    response = await _post(client, {"url": url, "formats": ["links", "metadata"]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        *("job_id", "capture_id", "url", "final_url", "fetched_at", "outcome", "fetch", "usage"),
        *("links", "metadata"),
    }
    assert (body["url"], body["final_url"], body["outcome"]) == (url, url, "extracted")
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
        "attempts": [
            {"method": "http", "status": 200, "block_class": "ok", "duration_ms": 1, "error": None, "challenge": None}
        ],
    }
    assert body["usage"] == {
        "llm_calls": 0,
        "llm_tokens_in": 0,
        "llm_tokens_out": 0,
        "browser_seconds": 0,
        "http_requests": 2,
    }


async def test_a_page_not_found_is_an_outcome_in_a_200(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/gone", "formats": ["markdown"]})

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "not_found"
    assert "markdown" not in body


async def test_a_private_target_is_an_ssrf_problem(client: httpx.AsyncClient) -> None:
    response = await _post(client, {"url": f"https://{PRIVATE_HOST}/", "formats": ["markdown"]})

    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "ssrf_rejected",
        "detail": "ssrf_rejected: private_address",
    }


async def test_a_scrape_past_its_timeout_is_a_timeout_problem(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/slow", "formats": ["markdown"], "timeout_s": 0.2})

    assert response.status_code == 504
    assert response.json()["type"] == "timeout"


async def test_a_prompt_returns_its_draft_and_reuses_it(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
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


async def test_a_prompt_without_llm_budget_is_a_budget_problem(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    response = await _post(
        client, {"url": url, "formats": ["links"], "schema": {"prompt": prompt}, "budget": {"llm_calls": 0}}
    )

    assert response.status_code == 422
    assert response.json()["type"] == "budget_exhausted"


@pytest.mark.parametrize("provider", [FakeProvider([ProviderError("overloaded")])])
async def test_a_prompt_no_provider_answers_is_an_llm_problem(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    response = await _post(client, {"url": url, "formats": ["links"], "schema": {"prompt": prompt}})

    assert response.status_code == 503
    assert {k: response.json()[k] for k in ("type", "detail")} == {
        "type": "llm_unavailable",
        "detail": "fake: overloaded",
    }


@pytest.mark.parametrize("provider", [None])
async def test_an_app_without_a_provider_key_serves_and_refuses_a_new_prompt(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)

    plain = await _post(client, {"url": url, "formats": ["links"]})
    drafted = await _post(client, {"url": url, "formats": ["links"], "schema": {"prompt": prompt}})

    assert plain.status_code == 200
    assert drafted.status_code == 503
    assert {k: drafted.json()[k] for k in ("type", "detail")} == {
        "type": "llm_unavailable",
        "detail": "CRAWLERAI_LLM_API_KEY_ANTHROPIC is not set",
    }


async def test_a_blank_prompt_is_a_validation_problem_and_starts_no_job(
    client: httpx.AsyncClient, database: AsyncEngine, own_origin: str
) -> None:
    async with database.connect() as conn:
        jobs_before = (await conn.execute(select(func.count()).select_from(Job))).scalar_one()

    response = await _post(client, {"url": f"{own_origin}/", "formats": ["links"], "schema": {"prompt": " \n\t "}})

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "validation"
    # The union reports each schema form's error; the prompt form's is that the prompt is empty.
    assert {"field": "schema.SchemaPrompt.prompt", "reason": "the prompt is empty"} in problem["errors"]
    async with database.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(Job))).scalar_one() == jobs_before


# --- records (§4.4) ---

TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}
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


@pytest.fixture
async def kettle_schema(database: AsyncEngine, schema_name: str) -> SchemaDef:
    document = SchemaDocument.model_validate(
        {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    )
    async with database.begin() as conn:
        return await registry.create(conn, document, "user")


def _records(url: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"url": url, "formats": ["markdown", "records"], "schema": schema, "page_kind": "detail"}


async def test_records_answer_every_field_with_its_attributes(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, kettle_schema: SchemaDef
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, _product_page(url))

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


async def test_an_inline_schema_that_breaks_a_schema_rule_is_a_validation_problem(
    client: httpx.AsyncClient, own_origin: str, schema_name: str
) -> None:
    undescribed = {"name": schema_name, "page_kind": "detail", "fields": {"title": {"type": "text"}}}

    response = await _post(client, _records(f"{own_origin}/kettles/blue", {"inline": undescribed}))

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "validation"
    assert [error["field"] for error in problem["errors"]] == ["schema.inline"]


async def test_an_unknown_schema_id_is_a_validation_problem(client: httpx.AsyncClient, own_origin: str) -> None:
    schema_id = "0192f5a4-0000-7000-8000-000000000001"

    response = await _post(client, _records(f"{own_origin}/kettles/blue", {"id": schema_id}))

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "validation"
    assert problem["errors"] == [{"field": "schema", "reason": f"no schema with id {schema_id}"}]


@pytest.mark.parametrize("data", [None])
async def test_records_without_the_engine_data_are_unavailable(
    client: httpx.AsyncClient, own_origin: str, kettle_schema: SchemaDef
) -> None:
    response = await _post(client, _records(f"{own_origin}/kettles/blue", {"id": str(kettle_schema.id)}))

    assert response.status_code == 503
    assert response.json()["type"] == "records_unavailable"
    # The detail names the fix.
    assert response.json()["detail"] == (
        "this process has not loaded the engine's data files: fetch them with `crawlerai data fetch` (in backend/),"
        " then restart the API and the worker"
    )


def _listing_records(url: str, schema_name: str, **fields: Any) -> dict[str, Any]:
    inline = {"name": schema_name, "page_kind": "listing", "fields": {**LISTING_FIELDS, **fields}}
    return {"url": url, "formats": ["records"], "schema": {"inline": inline}, "page_kind": "listing"}


async def test_a_listing_answers_one_record_per_row(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, schema_name: str
) -> None:
    url = f"{own_origin}/kettles"
    pages[url] = (200, listing_page(own_origin, ["Blue kettle", "Red kettle", "Green kettle"]))

    response = await _post(client, _listing_records(url, schema_name))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "extracted"
    rows = [(r["complete"], r["fields"]["title"]["value"], r["fields"]["url"]["value"]) for r in body["records"]]
    assert rows == [
        (True, "Blue kettle", f"{own_origin}/kettles/1"),
        (True, "Red kettle", f"{own_origin}/kettles/2"),
        (True, "Green kettle", f"{own_origin}/kettles/3"),
    ]


async def test_a_listing_with_an_incomplete_row_is_partial_and_keeps_every_row(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, schema_name: str
) -> None:
    url = f"{own_origin}/kettles"
    pages[url] = (200, listing_page(own_origin, ["Blue kettle", "Red kettle", "Green kettle"], priced=False))

    response = await _post(client, _listing_records(url, schema_name, price=PRICE))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "partial"
    assert [(r["complete"], r["fields"]["price"]["status"]) for r in body["records"]] == [(False, "missing")] * 3


async def test_a_listing_without_rows_is_partial_with_no_record(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, schema_name: str
) -> None:
    url = f"{own_origin}/kettles"
    pages[url] = (200, PAGE)

    response = await _post(client, _listing_records(url, schema_name))

    assert response.status_code == 200, response.text
    assert (response.json()["outcome"], response.json()["records"]) == ("partial", [])


async def test_the_markdown_of_a_page_scraped_as_a_listing_keeps_its_items(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles"
    tiles = "".join(
        f'<li class="tile"><h3><a href="/kettles/{i}">Kettle {i}</a></h3><p>{i}9.90 EUR</p></li>' for i in range(5)
    )
    pages[url] = (200, f"<html><body><main><h1>Kettles</h1><ul>{tiles}</ul></main></body></html>".encode())

    listing = (await _post(client, {"url": url, "formats": ["markdown"], "page_kind": "listing"})).json()["markdown"]
    detail = (await _post(client, {"url": url, "formats": ["markdown"], "page_kind": "detail"})).json()["markdown"]

    assert [line for line in listing.splitlines() if line.startswith("- ")] == [
        f"- [Kettle {i}]({own_origin}/kettles/{i}) {i}9.90 EUR" for i in range(5)
    ]
    assert f"[Kettle 3]({own_origin}/kettles/3)" not in detail
