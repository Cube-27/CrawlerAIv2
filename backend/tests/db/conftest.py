"""Tests against a real Postgres, in a database of their own: `SNOWCRAWL_TEST_DATABASE_URL`. CI provides one, and
`make check` recreates one each run. Without it these tests are skipped."""

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from snowcrawl.acquire import politeness
from snowcrawl.acquire.rungs import Rungs
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.config_ir.progressive import StateKey
from snowcrawl.core.ids import uuid7
from snowcrawl.db.models import (
    Base,
    ConfigStatus,
    ExtractionConfig,
    ProgressiveState,
    Project,
    Site,
    SiteId,
    SourceKind,
)
from snowcrawl.normalize.dispatch import warm
from snowcrawl.resolve.pipeline import EngineData
from snowcrawl.resolve.preference import PRECEDENCE_TYPES
from snowcrawl.schemas import registry
from snowcrawl.schemas import types as schema_types
from snowcrawl.schemas.types import document_digest
from snowcrawl.services.fetching import Fetching
from tests.db.support import PRICE, TITLE, Web, api, fetching_from, unpaced
from tests.support.captures import fetched

TEST_DATABASE_URL = "SNOWCRAWL_TEST_DATABASE_URL"
VOCABULARY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld"
# Every source kind ranked, so precedence types resolve (an unfitted order declines them).
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def worker_database_url(url: str, worker: str | None) -> str:
    """`url` with the database name suffixed with the xdist `worker` id (`gw0`, ...), or `url` itself without one."""
    if worker is None:
        return url
    parsed = make_url(url)
    return parsed.set(database=f"{parsed.database}_{worker}").render_as_string(hide_password=False)


def _test_database_url(variable: str) -> str:
    url = os.environ.get(variable)
    if not url:
        pytest.skip(f"{variable} is not set")
    return worker_database_url(url, os.environ.get("PYTEST_XDIST_WORKER"))


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """One event loop for the session, so the worker's one engine (`shared_engine`) serves every test."""
    return "asyncio"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url(TEST_DATABASE_URL)
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
async def shared_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The one engine of this xdist worker, against its own database; its pool serves every test."""
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def uncancelled(anyio_backend: str) -> AsyncIterator[None]:
    """Every test starts and ends with no cancellation counted on the session's one task. Python 3.12's
    `asyncio.TaskGroup` leaves one counted on its parent for each child that fails (3.13 no longer does), and in a
    task that outlives the test, that count makes a later test's task group raise `CancelledError`."""
    _uncancel()
    yield
    _uncancel()


def _uncancel() -> None:
    task = asyncio.current_task()
    while task is not None and task.cancelling():
        task.uncancel()


@pytest.fixture
async def conn(shared_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection in a transaction rolled back after the test."""
    async with shared_engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()


# Every table, referencing ones first. On tables of a few rows a DELETE each is about ten times faster than one TRUNCATE
# (which recreates every table's files) and locks rows, not tables.
_TABLES = tuple(reversed(Base.metadata.sorted_tables))


@pytest.fixture
async def engine(shared_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """The database for a test that commits (through it, the app, the CLI or a worker): every table is emptied
    afterwards but for the default project, which the baseline migration seeds. A test that commits requests it,
    directly or through a fixture."""
    yield shared_engine
    async with shared_engine.begin() as connection:
        for table in _TABLES:
            rows = table.delete()
            if table is Project.__table__:
                rows = rows.where(table.c.name != "default")
            await connection.execute(rows)


@pytest.fixture
def own_origin() -> str:
    """An https origin on a host no other test uses."""
    return f"https://shop-{uuid7().hex[-12:]}.example.test"


@pytest.fixture
def www_origin(own_origin: str) -> str:
    """`own_origin` on its `www.` subdomain: a site that redirects one to the other."""
    return f"https://www.{own_origin.removeprefix('https://')}"


@pytest.fixture
def prompt() -> str:
    """A prompt no other test drafts."""
    return f"Product names {uuid.uuid4()}"


@pytest.fixture
def schema_name() -> str:
    """A schema name no other test uses, and a prefix for more."""
    return f"synthetic_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def fetch_result() -> Callable[..., FetchResult]:
    """The result of one fetch of `url` by one rung, as the rung reports it (`tests.support.captures.fetched`)."""
    return fetched


@pytest.fixture
async def site(engine: AsyncEngine, own_origin: str, monkeypatch: pytest.MonkeyPatch) -> SiteId:
    """The site of `own_origin`, with a short request interval for the test, so a job of its pages, or a page and its
    API endpoint, run without waiting a second per request."""
    monkeypatch.setattr(politeness, "DEFAULT_INTERVAL", timedelta(milliseconds=1))
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"project_id": project, "host": own_origin.removeprefix("https://")}
        site_id: SiteId = (await conn.execute(insert(Site).values(values).returning(Site.id))).scalar_one()
    return site_id


async def learned_site(
    conn: AsyncConnection, schema: schema_types.SchemaDef, statuses: Sequence[ConfigStatus]
) -> StateKey:
    """A new site with configs of `statuses` (versions 1, 2, ...) for `schema`, and its progressive state: `active` on
    the last active config, else `cold`; 12 pages extracted, a run in flight and a retry pending."""
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    host = f"shop-{uuid.uuid4().hex[:12]}.example.test"
    site_id = (await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))).scalar_one()
    key = StateKey(site_id, schema.id, schema.page_kind)
    rows = [
        {**key.columns(), "version": n, "status": s, "ir": {}, "origin": "induced"} for n, s in enumerate(statuses, 1)
    ]
    ids = (await conn.execute(insert(ExtractionConfig).returning(ExtractionConfig.id), rows)).scalars().all()
    active = [config_id for config_id, status in zip(ids, statuses, strict=True) if status == "active"]
    state: dict[str, Any] = {"mode": "active", "active_config_id": active[-1]} if active else {"mode": "cold"}
    values = {
        **key.columns(),
        **state,
        "pages_extracted": 12,
        "learning_started_at": datetime.now(UTC),
        "retry_at_pages": 20,
    }
    await conn.execute(insert(ProgressiveState).values(values))
    return key


@pytest.fixture
def heading_config() -> Callable[[SiteId, schema_types.SchemaDef, int], dict[str, Any]]:
    """A factory for an active `extraction_config` row of a detail schema, version `version`, whose one field, the
    title, is read from the page's heading."""

    def make(site_id: SiteId, schema: schema_types.SchemaDef, version: int) -> dict[str, Any]:
        ir = {
            "ir_version": "1",
            "site": "unused.example.test",
            "schema": {"name": schema.name, "digest": document_digest(schema)},
            "page_kind": "detail",
            "fetch": {"method": "http"},
            "fields": {"title": {"steps": [{"xpath": "normalize-space(//h1)"}], "status": "corroborated"}},
            "provenance": {
                "origin": "induced",
                "validated_on": [],
                "learned_at": "2026-10-01T00:00:00Z",
                "engine_version": "t",
            },
        }
        return {
            "site_id": site_id,
            "schema_id": schema.id,
            "page_kind": "detail",
            "version": version,
            "status": "active",
            "ir": ir,
            "origin": "induced",
            "field_status": {"title": "corroborated"},
        }

    return make


@pytest.fixture(scope="session")
def engine_data() -> EngineData:
    """What resolution reads besides the page: the synthetic schema.org vocabulary, every precedence type ranked, and
    no calibration."""
    return EngineData(
        vocabulary=Vocabulary.read(VOCABULARY), orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None
    )


# A listing schema's row fields: the item's name and URL (the schema.org Thing properties `name` and `url`).
LISTING_FIELDS: dict[str, Any] = {
    "title": {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"},
    "url": {"type": "url", "required": True, "description": "The product page", "schema_org": "Product.url"},
}


async def listing_schema(engine: AsyncEngine, name: str) -> schema_types.SchemaDef:
    """A stored listing schema of `LISTING_FIELDS`, named `name`."""
    document = {"name": name, "page_kind": "listing", "fields": LISTING_FIELDS}
    async with engine.begin() as conn:
        return await registry.create(conn, schema_types.SchemaDocument.model_validate(document), "user")


def listing_page(
    origin: str, names: list[str], *, priced: bool = True, first: int = 1, next_page: str | None = None
) -> bytes:
    """A synthetic listing whose rows are the items of a schema.org ItemList, one Product at `origin`/kettles/<n>
    each from n = `first`, priced in EUR when `priced`; `next_page` is its `<link rel="next">` (HTML standard)."""
    items = []
    for position, name in enumerate(names, start=first):
        product: dict[str, Any] = {"@type": "Product", "name": name, "url": f"{origin}/kettles/{position}"}
        if priced:
            product["offers"] = {"@type": "Offer", "price": f"{position}9.90", "priceCurrency": "EUR"}
        items.append({"@type": "ListItem", "position": position, "item": product})
    node = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": items}
    head = f'<title>Kettles</title><script type="application/ld+json">{json.dumps(node)}</script>'
    if next_page is not None:
        head += f'<link rel="next" href="{next_page}">'
    return f"<!doctype html><html><head>{head}</head><body></body></html>".encode()


@pytest.fixture
async def submit_client(submit_app: tuple[FastAPI, httpx.AsyncClient]) -> httpx.AsyncClient:
    """The client of `submit_app`."""
    return submit_app[1]


@pytest.fixture
async def submit_app(
    app_env: pytest.MonkeyPatch, engine: AsyncEngine, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """The app, and its client, for the endpoints that submit jobs: without the engine's data files, its fetching a
    stub that resolves `PRIVATE_HOST` to a private address and fetches nothing (submitting fetches nothing)."""

    async def never(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("submitting a job fetches nothing")

    async with api(engine) as (app, client):
        fetching = fetching_from(Rungs(http=never, browser=never), tmp_path / "objects")
        app.state.runtime = replace(app.state.runtime, fetching=fetching, engine_data=None)
        yield app, client


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    """`own_origin` as a site whose robots.txt allows everything."""
    return Web.site(fetch_result, own_origin)


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> schema_types.SchemaDef:
    """A stored detail schema of `TITLE` and `PRICE`."""
    document = {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, schema_types.SchemaDocument.model_validate(document), "user")


@pytest.fixture(scope="session")
def warmed() -> None:
    """The normalizers' CLDR tables, built once for the session: every app's startup builds them on a thread
    (`services.runtime`), and apps of tests sharing one event loop would otherwise build them side by side."""
    warm()


@pytest.fixture
def app_env(warmed: None, database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """The app's settings: the test database, an object store under `tmp_path/objects`, no trusted proxies."""
    monkeypatch.setenv("SNOWCRAWL_DATABASE_URL", database_url)
    monkeypatch.setenv("SNOWCRAWL_OBJECT_STORE", "fs:///" + (tmp_path / "objects").as_posix().lstrip("/"))
    monkeypatch.setenv("SNOWCRAWL_TRUSTED_PROXIES", "[]")
    return monkeypatch


@pytest.fixture
async def client(app_env: pytest.MonkeyPatch, engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """The app's client, on the app as configured; a file needing the app's state changed defines its own."""
    async with api(engine) as (_, client):
        yield client


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    """What a service fetches with: `web`'s rungs, unpaced, storing captures under `tmp_path/objects`."""
    return fetching_from(web, tmp_path / "objects", limiter=unpaced())
