"""Tests against a real Postgres, in a database of their own: `CRAWLERAI_TEST_DATABASE_URL`. CI provides one, and
`make check` recreates one each run. Without it these tests are skipped.

The tests own that database: they delete every job and task in it, and the queue tests claim and run every due task
in it, not only their own, which is why they never use `CRAWLERAI_DATABASE_URL`. Never point it at data you want.

`CRAWLERAI_TEST_PRIVATE_DATABASE_URL` names a second throwaway database, migrated with the private eval revisions
(`alembic -n private`), for the private eval store's tests. It is never the private eval database itself (C1), and
without it those tests are skipped.

Under pytest-xdist (CI: `pytest -n`) each worker gets databases of its own, the names suffixed with the worker id
(`crawlerai_gw0`, ...): the tests above delete and claim every row, so two workers never share one. CI creates them;
a serial run (`uv run pytest`) uses the databases as named.

The database is migrated to head once per session. Each test runs in a transaction that is rolled back (`conn`),
or, when several connections must see each other's work, commits through `engine`, which deletes every job afterwards.
"""

import json
import os
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.acquire.politeness import HostLimiter, retry_after
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.api.app import create_app
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.progressive import StateKey
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.keys import create_key
from crawlerai.db.models import (
    ApiKey,
    Candidate,
    Capture,
    ConfigStatus,
    Extraction,
    ExtractionConfig,
    Job,
    JobEvent,
    ProgressiveState,
    Project,
    Record,
    SchemaDef,
    Site,
    SiteId,
    SourceKind,
    UrlState,
    UrlTask,
    UsageEvent,
    WebhookDelivery,
)
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas import registry
from crawlerai.schemas import types as schema_types
from crawlerai.services.fetching import Fetching
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, HeaderList, Headers, sha256_hex
from crawlerai.storage.fs import FsStore

TEST_DATABASE_URL = "CRAWLERAI_TEST_DATABASE_URL"
VOCABULARY = Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld"
# Every source kind ranked, so precedence types resolve (an unfitted order declines them, D-0486).
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
TEST_PRIVATE_DATABASE_URL = "CRAWLERAI_TEST_PRIVATE_DATABASE_URL"
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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _test_database_url(TEST_DATABASE_URL)
    config = Config(ALEMBIC_INI)
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
def private_database_url() -> str:
    url = _test_database_url(TEST_PRIVATE_DATABASE_URL)
    config = Config(ALEMBIC_INI, ini_section="private")
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    return url


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(database_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield connection
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    async with engine.begin() as connection:
        for model in (
            Candidate,
            Record,
            Extraction,
            ProgressiveState,
            UsageEvent,
            JobEvent,
            WebhookDelivery,
            UrlTask,
            Job,
        ):
            await connection.execute(delete(model))
    await engine.dispose()


@pytest.fixture
async def own_origin(database_url: str) -> AsyncIterator[str]:
    """An https origin on a host no other test uses, for tests that commit a site for it. The site, its captures, and
    its records, progressive state and url_state are deleted afterwards (a task or extraction that named a capture
    keeps a NULL, SPEC-01 §4.2)."""
    async for origin in _origin(database_url):
        yield origin


@pytest.fixture
async def other_origin(database_url: str) -> AsyncIterator[str]:
    """A second origin as `own_origin`, for a test of two sites (a redirect from one host to another)."""
    async for origin in _origin(database_url):
        yield origin


async def _origin(database_url: str) -> AsyncIterator[str]:
    host = f"shop-{uuid7().hex[-12:]}.example.test"
    yield f"https://{host}"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        site_ids = select(Site.id).where(Site.host == host).scalar_subquery()
        for model in (Record, ProgressiveState, Capture, UrlState):
            await connection.execute(delete(model).where(model.site_id.in_(site_ids)))
        await connection.execute(delete(Site).where(Site.host == host))
    await engine.dispose()


async def _delete_schemas(engine: AsyncEngine, name: str) -> None:
    """Schema `name` and those whose names start with it, with their records and progressive state; jobs that named
    them keep a NULL."""
    async with engine.begin() as conn:
        ids = select(SchemaDef.id).where(SchemaDef.name.startswith(name)).scalar_subquery()
        await conn.execute(update(Job).where(Job.schema_id.in_(ids)).values(schema_id=None))
        for model in (Record, ProgressiveState):
            await conn.execute(delete(model).where(model.schema_id.in_(ids)))
        await conn.execute(delete(SchemaDef).where(SchemaDef.name.startswith(name)))


@pytest.fixture
async def prompt(engine: AsyncEngine) -> AsyncIterator[str]:
    """A prompt no other test drafts; its draft schema is deleted afterwards."""
    text = f"Product names {uuid.uuid4()}"
    yield text
    await _delete_schemas(engine, draft_name(text))


@pytest.fixture
async def schema_name(engine: AsyncEngine) -> AsyncIterator[str]:
    """A schema name no other test uses, and a prefix for more; those schemas are deleted afterwards."""
    name = f"synthetic_{uuid.uuid4().hex[:12]}"
    yield name
    await _delete_schemas(engine, name)


@pytest.fixture
def fetch_result() -> Callable[..., FetchResult]:
    """A factory for the result of one fetch of `url` by one rung, as `fetch_http` reports it; `final_url` is where its
    redirects ended (default: `url`)."""

    def make(
        url: str,
        status: int = 200,
        body: bytes = b"",
        headers: HeaderList = (),
        *,
        block_class: BlockClass = "ok",
        error: str | None = None,
        method: CaptureMethod = "http",
        policy: FetchPolicy | None = None,
        final_url: str | None = None,
    ) -> FetchResult:
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=final_url or url,
            fetched_at=datetime.now(UTC),
            method=method,
            status_code=status,
            block_class=block_class,
            headers=Headers(request=(), response=headers),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(body),
            network_bodies=(),
            fetch_policy=(policy or FetchPolicy()).model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(
            method=method,
            status=status or None,
            block_class=block_class,
            duration_ms=1,
            error=error,
            retry_after=retry_after(headers, manifest.fetched_at),
        )
        return FetchResult(
            bundle=CaptureBundle(manifest=manifest, body=body, network=()), duration_ms=1, attempts=(attempt,)
        )

    return make


@pytest.fixture
async def site(engine: AsyncEngine, own_origin: str) -> SiteId:
    """The site of `own_origin` with a short interval, so a job of its pages, or a page and its API endpoint, run
    without waiting a second per request."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"project_id": project, "host": own_origin.removeprefix("https://"), "crawl_delay_ms": 1}
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
            "schema": {"name": schema.name},
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


PRIVATE_HOST = "intranet.example.test"


async def resolve(host: str) -> list[IPAddress]:
    """A stub resolver: `PRIVATE_HOST` has a private address, every other host a public one."""
    return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]


@pytest.fixture
async def submit_client(
    database_url: str, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """The app against the test database, for the endpoints that submit jobs: without the engine's data files, its
    fetching a stub that resolves `PRIVATE_HOST` to a private address and fetches nothing (submitting fetches
    nothing). `engine` deletes the jobs afterwards; the key is deleted here."""
    monkeypatch.setenv("CRAWLERAI_DATABASE_URL", database_url)
    monkeypatch.setenv("CRAWLERAI_OBJECT_STORE", "fs:///" + tmp_path.as_posix().lstrip("/"))
    monkeypatch.setenv("CRAWLERAI_TRUSTED_PROXIES", "[]")

    async def never(url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("submitting a job fetches nothing")

    async with engine.begin() as conn:
        key = await create_key(conn, "submit-api-test")
    app = create_app(eval_ui=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api.test",
            headers={"authorization": f"Bearer {key.key}"},
        ) as client,
    ):
        store = FsStore(tmp_path / "objects")
        app.state.fetching = Fetching(Rungs(http=never, browser=never), SafeConnector(resolve), store, HostLimiter())
        app.state.engine_data = None
        yield client
    keys_engine = create_async_engine(database_url)
    async with keys_engine.begin() as conn:
        # The key's jobs keep their rows until `engine` deletes them; they let go of the key first.
        await conn.execute(update(Job).where(Job.api_key_id == key.id).values(api_key_id=None))
        await conn.execute(delete(ApiKey).where(ApiKey.id == key.id))
    await keys_engine.dispose()
