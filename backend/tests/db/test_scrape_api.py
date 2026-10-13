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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.api.keys import create_key
from crawlerai.db.models import ApiKey
from crawlerai.llm.client import MeteredClient, ProviderError, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.services.scrape import Fetching
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
PAGE = b"""<!doctype html><html lang="en"><head><title>Blue kettle</title></head>
<body><h1>Blue kettle</h1><a href="/kettles/red">Red kettle</a></body></html>"""
DRAFT_REPLY = ProviderReply(
    model="fake-strong",
    text=json.dumps(
        {"page_kind": "detail", "fields": {"title": {"type": "text", "required": True, "description": "Product name"}}}
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
    monkeypatch.delenv("CRAWLERAI_LLM_API_KEY_ANTHROPIC", raising=False)
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
        return fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found")

    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    store = FsStore(tmp_path / "objects")
    return Fetching(Rungs(http=http, browser=http), SafeConnector(resolve), store, HostLimiter())


@pytest.fixture
def provider() -> FakeProvider | None:
    """The LLM provider the app's client asks: one role S draft, scripted. None keeps the app's own client."""
    return FakeProvider([DRAFT_REPLY])


@pytest.fixture
async def client(
    database: AsyncEngine, fetching: Fetching, provider: FakeProvider | None
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
        "attempts": [{"method": "http", "status": 200, "block_class": "ok", "duration_ms": 1, "error": None}],
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


async def test_an_invalid_request_is_a_validation_problem(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await _post(client, {"url": f"{own_origin}/", "formats": ["markdown"], "timeout_s": 121})

    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "validation"
    assert [error["field"] for error in problem["errors"]] == ["timeout_s"]


async def test_a_request_without_a_key_is_unauthorized(client: httpx.AsyncClient, own_origin: str) -> None:
    response = await client.post(
        "/v1/scrape", json={"url": f"{own_origin}/", "formats": ["markdown"]}, headers={"authorization": ""}
    )

    assert response.status_code == 401
    assert response.json()["type"] == "unauthorized"


async def test_a_prompt_returns_its_draft_and_reuses_it(
    client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str, prompt: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, PAGE)
    body = {"url": url, "formats": ["links"], "schema": {"prompt": prompt}}

    first, second = await _post(client, body), await _post(client, body)

    assert (first.status_code, second.status_code) == (200, 200), first.text
    schema = first.json()["schema"]
    assert {k: schema[k] for k in ("name", "version", "origin", "status", "page_kind")} == {
        "name": draft_name(prompt),
        "version": 1,
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
