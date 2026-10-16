"""The MCP server (SPEC-10 §4.7): the SDK's client calls each of the ten tools over streamable HTTP at `/mcp` in the
API app, and over stdio from `python -m crawlerai.mcp_server`. What each tool does is its service's, tested with the
service; here, that a tool reaches it with the caller's key, and answers by the output rules (§13.3).

The app runs as the REST tests run it: real settings against the test database, its fetching a stub web of synthetic
pages on RFC 2606 hosts with a stub resolver, so nothing leaves the process.
"""

import json
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.db.keys import CreatedKey, create_key, revoke_key
from crawlerai.db.models import ApiKey, ExtractionConfig, ExtractionConfigId, Job, Project, Site, SiteId
from crawlerai.llm.client import Unconfigured
from crawlerai.llm.setup import LLMSetup
from crawlerai.mcp_server.output import MARKDOWN_PAGE_CHARS
from crawlerai.mcp_server.server import UNTRUSTED, build_server
from crawlerai.mcp_server.stdio import key_bind
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services import schemas
from crawlerai.services.fetching import Fetching
from crawlerai.services.runtime import Runtime
from crawlerai.storage.fs import FsStore
from tests.db.conftest import PRIVATE_HOST, resolve

pytestmark = pytest.mark.anyio

TOOLS = {
    "scrape",
    "map",
    "crawl_start",
    "crawl_status",
    "extract",
    "extract_status",
    "list_schemas",
    "create_schema",
    "get_site_config",
    "export_config",
}
# The tools that answer with page content say that it is untrusted (§4.7).
CONTENT_TOOLS = {"scrape", "map", "crawl_status", "extract_status"}
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}


def _page(title: str, body: str = "") -> bytes:
    node = {"@context": "https://schema.org", "@type": "Product", "name": title}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    return (
        f'<!doctype html><html lang="en"><head><title>{title}</title>{script}</head>'
        f'<body><h1>{title}</h1><p>{body}</p><a href="/kettles/red">Red kettle</a></body></html>'
    ).encode()


@pytest.fixture
def pages(own_origin: str) -> dict[str, tuple[int, bytes]]:
    return {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")}


@pytest.fixture
def fetching(fetch_result: Callable[..., FetchResult], pages: dict[str, tuple[int, bytes]], tmp_path: Path) -> Fetching:
    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        status, body = pages.get(url, (404, b""))
        return fetch_result(
            url, status, body, (("Content-Type", "text/html"),), block_class="ok" if status == 200 else "not_found"
        )

    return Fetching(
        Rungs(http=http, browser=http), SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter()
    )


@pytest.fixture
async def key(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[CreatedKey]:
    """A key, and the app's settings pointed at the test database. `engine` deletes the jobs afterwards; they let go of
    the key, deleted here, first."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")
    async with engine.begin() as conn:
        created = await create_key(conn, "mcp-test")
    yield created
    async with engine.begin() as conn:
        await conn.execute(update(Job).where(Job.api_key_id == created.id).values(api_key_id=None))
        await conn.execute(delete(ApiKey).where(ApiKey.id == created.id))


@pytest.fixture
async def app_client(key: CreatedKey, fetching: Fetching, engine_data: EngineData) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client of the app, with the key as its bearer."""
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
        app.state.engine_data = engine_data
        yield client


@pytest.fixture
async def session(app_client: httpx.AsyncClient) -> AsyncIterator[ClientSession]:
    """The SDK's client, connected to `/mcp` through `app_client`."""
    async with (
        streamable_http_client("http://api.test/mcp", http_client=app_client) as (read, write, _),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        yield client


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = SchemaDocument.model_validate(
        {"name": schema_name, "version": 1, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    )
    async with engine.begin() as conn:
        return await registry.create(conn, document, "user")


async def _call(session: ClientSession, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await session.call_tool(tool, arguments)
    assert not result.isError, _texts(result)
    assert result.structuredContent is not None
    return result.structuredContent


def _texts(result: CallToolResult) -> list[str]:
    return [block.text for block in result.content if isinstance(block, TextContent)]


async def test_the_ten_tools_are_listed_and_those_with_page_content_say_it_is_untrusted(
    session: ClientSession,
) -> None:
    tools = (await session.list_tools()).tools

    assert {tool.name for tool in tools} == TOOLS
    assert {tool.name for tool in tools if UNTRUSTED in (tool.description or "")} == CONTENT_TOOLS


async def test_the_endpoint_refuses_a_request_without_a_key(app_client: httpx.AsyncClient) -> None:
    response = await app_client.post("/mcp", json={}, headers={"authorization": ""})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["type"] == "unauthorized"


async def test_scrape_pages_the_markdown_the_rest_endpoint_answers_with(
    session: ClientSession, app_client: httpx.AsyncClient, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, _page("Blue kettle", "steel " * MARKDOWN_PAGE_CHARS))
    rest = (await app_client.post("/v1/scrape", json={"url": url, "formats": ["markdown"]})).json()

    first = await _call(session, "scrape", request={"url": url, "formats": ["markdown"]})
    texts, cursor = [first["markdown"]], first["next_cursor"]
    while cursor is not None:
        page = await _call(session, "scrape", cursor=cursor)
        texts.append(page["markdown"])
        cursor = page["next_cursor"]

    assert len(rest["markdown"]) > 2 * MARKDOWN_PAGE_CHARS
    assert "".join(texts) == rest["markdown"]
    assert [len(text) for text in texts[:-1]] == [MARKDOWN_PAGE_CHARS] * (len(texts) - 1)
    assert first["outcome"] == "extracted"


async def test_scrape_records_read_unknown_for_a_field_without_a_published_value(
    session: ClientSession, pages: dict[str, tuple[int, bytes]], own_origin: str, kettle_schema: SchemaDef
) -> None:
    url = f"{own_origin}/kettles/blue"
    pages[url] = (200, _page("Blue kettle"))
    request = {"url": url, "formats": ["records"], "schema": {"id": str(kettle_schema.id)}, "page_kind": "detail"}

    result = await session.call_tool("scrape", {"request": request})

    assert not result.isError, _texts(result)
    (record,) = (result.structuredContent or {})["records"]
    assert {name: field["status"] for name, field in record["fields"].items()} == {
        "title": "published",
        "price": "missing",
    }
    summary = _texts(result)[1].splitlines()
    assert sorted(summary[1:]) == [
        "- price: unknown [missing, confidence none]",
        '- title: "Blue kettle" [published, confidence none]',
    ]


async def test_scrape_of_a_private_target_is_an_error_result(session: ClientSession) -> None:
    result = await session.call_tool(
        "scrape", {"request": {"url": f"https://{PRIVATE_HOST}/", "formats": ["markdown"]}}
    )

    assert (result.isError, _texts(result)) == (True, ["Error executing tool scrape: ssrf_rejected: private_address"])


async def test_map_answers_the_start_pages_links(
    session: ClientSession, pages: dict[str, tuple[int, bytes]], own_origin: str
) -> None:
    pages[f"{own_origin}/"] = (200, _page("Kettles"))

    result = await _call(session, "map", request={"url": f"{own_origin}/", "use_sitemaps": False})

    assert result == {"urls": [f"{own_origin}/kettles/red"], "sources": {"sitemap": 0, "links": 1}, "truncated": False}


async def test_a_created_schema_is_listed(session: ClientSession, schema_name: str) -> None:
    document = {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE}}

    created = await _call(session, "create_schema", schema=document)
    listed = await _call(session, "list_schemas", name=schema_name)

    assert (created["name"], created["version"], created["origin"]) == (schema_name, 1, "user")
    assert listed["items"] == [created]


async def test_a_started_crawl_is_the_callers_and_its_status_has_the_summary_and_results(
    session: ClientSession, engine: AsyncEngine, key: CreatedKey, own_origin: str
) -> None:
    started = await _call(session, "crawl_start", request={"url": f"{own_origin}/", "formats": ["markdown"]})
    status = await _call(session, "crawl_status", job_id=started["job_id"])

    assert set(started) == {"job_id"}
    async with engine.connect() as conn:
        owner = (await conn.execute(select(Job.api_key_id).where(Job.id == started["job_id"]))).scalar_one()
    assert owner == key.id
    assert (status["job"]["id"], status["job"]["kind"], status["job"]["counts"]["queued"]) == (
        started["job_id"],
        "crawl",
        1,
    )
    assert [item["url"] for item in status["results"]["items"]] == [f"{own_origin}/"]


async def test_an_extract_job_is_the_callers_and_its_status_has_no_records_yet(
    session: ClientSession, engine: AsyncEngine, key: CreatedKey, own_origin: str, kettle_schema: SchemaDef
) -> None:
    request = {"urls": [f"{own_origin}/kettles/blue"], "schema": {"id": str(kettle_schema.id)}, "page_kind": "detail"}

    submitted = await session.call_tool("extract", {"request": request})
    assert not submitted.isError, _texts(submitted)
    job_id = (submitted.structuredContent or {})["job_id"]
    status = await session.call_tool("extract_status", {"job_id": job_id})

    assert (submitted.structuredContent or {})["schema"]["id"] == str(kettle_schema.id)
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.api_key_id).where(Job.id == job_id))).scalar_one() == key.id
    assert (status.structuredContent or {})["job"]["kind"] == "extract"
    assert (status.structuredContent or {})["results"] == {"items": [], "next_cursor": None}
    assert _texts(status)[1] == "No records."


@pytest.fixture
async def site_config(
    engine: AsyncEngine,
    own_origin: str,
    kettle_schema: SchemaDef,
    heading_config: Callable[[SiteId, SchemaDef, int], dict[str, Any]],
) -> AsyncIterator[ExtractionConfigId]:
    """An active config of the kettle schema for `own_origin`'s site; deleted before `own_origin` deletes the site."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site = insert(Site).values(project_id=project, host=own_origin.removeprefix("https://")).returning(Site.id)
        site_id = (await conn.execute(site)).scalar_one()
        row = heading_config(site_id, kettle_schema, 1)
        config_id = (
            await conn.execute(insert(ExtractionConfig).values(**row).returning(ExtractionConfig.id))
        ).scalar_one()
    yield config_id
    async with engine.begin() as conn:
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


async def test_a_sites_config_is_read_and_exported(
    session: ClientSession, own_origin: str, site_config: ExtractionConfigId
) -> None:
    configs = await _call(session, "get_site_config", host=own_origin.removeprefix("https://"))
    exported = await _call(session, "export_config", config_id=str(site_config), format="json")

    assert [(config["id"], config["status"]) for config in configs["items"]] == [(str(site_config), "active")]
    assert exported["format"] == "json"
    assert exported["export"]["fields"]["title"]["steps"] == [{"xpath": "normalize-space(//h1)", "post": []}]


# --- stdio ---


async def test_the_stdio_server_acts_with_the_key_in_its_environment(
    key: CreatedKey, database_url: str, kettle_schema: SchemaDef, tmp_path: Path
) -> None:
    environment = {
        **os.environ,
        "CRAWLERAI_DATABASE_URL": database_url,
        "CRAWLERAI_OBJECT_STORE": "fs:///" + tmp_path.as_posix().lstrip("/"),
        "CRAWLERAI_API_KEY": key.key,
    }
    server = StdioServerParameters(command=sys.executable, args=["-m", "crawlerai.mcp_server"], env=environment)

    async with stdio_client(server) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        listed = await client.call_tool("list_schemas", {"name": kettle_schema.name})

    assert not listed.isError, _texts(listed)
    assert [item["id"] for item in (listed.structuredContent or {})["items"]] == [str(kettle_schema.id)]


async def test_a_revoked_key_stops_the_stdio_server_at_its_next_call(
    key: CreatedKey, engine: AsyncEngine, fetching: Fetching, engine_data: EngineData
) -> None:
    runtime = Runtime(engine, fetching, Unconfigured("no LLM"), engine_data, None, LLMSetup.unavailable("no LLM"))
    server = build_server(key_bind(runtime, key.key))

    async with create_connected_server_and_client_session(server) as client:
        before = await client.call_tool("list_schemas", {})
        async with engine.begin() as conn:
            await revoke_key(conn, key.id)
        after = await client.call_tool("list_schemas", {})

    assert not before.isError
    assert after.isError
    assert _texts(after) == ["Error executing tool list_schemas: CRAWLERAI_API_KEY is unknown or revoked"]


async def test_a_status_cursor_that_is_not_one_is_refused_with_why(session: ClientSession, own_origin: str) -> None:
    started = await _call(session, "crawl_start", request={"url": f"{own_origin}/", "formats": ["markdown"]})

    result = await session.call_tool("crawl_status", {"job_id": started["job_id"], "cursor": "not-an-id"})

    assert (result.isError, _texts(result)) == (
        True,
        ["Error executing tool crawl_status: not a results cursor: 'not-an-id'"],
    )


async def test_a_services_invalid_data_reaches_the_client_as_an_unexpected_error(
    key: CreatedKey, engine: AsyncEngine, fetching: Fetching, engine_data: EngineData, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def parsing_a_stored_row(*args: object, **kwargs: object) -> None:
        TypeAdapter(int).validate_python("stored row 'secret'")

    monkeypatch.setattr(schemas, "list_all", parsing_a_stored_row)
    runtime = Runtime(engine, fetching, Unconfigured("no LLM"), engine_data, None, LLMSetup.unavailable("no LLM"))
    server = build_server(key_bind(runtime, key.key))

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("list_schemas", {})

    # The client's own input is refused before the tool runs; this one is the server's, as REST answers it.
    assert (result.isError, _texts(result)) == (
        True,
        ["Error executing tool list_schemas: the server failed to answer the request"],
    )


async def test_an_unexpected_error_reaches_the_client_without_its_text(
    key: CreatedKey,
    engine: AsyncEngine,
    fetching: Fetching,
    engine_data: EngineData,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("SELECT secret FROM internals")

    monkeypatch.setattr(schemas, "list_all", failing)
    runtime = Runtime(engine, fetching, Unconfigured("no LLM"), engine_data, None, LLMSetup.unavailable("no LLM"))
    server = build_server(key_bind(runtime, key.key))

    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("list_schemas", {})

    # As REST answers an unexpected exception (`problems._on_unexpected`); the server logs it.
    assert (result.isError, _texts(result)) == (
        True,
        ["Error executing tool list_schemas: the server failed to answer the request"],
    )
    assert "SELECT secret FROM internals" in caplog.text
