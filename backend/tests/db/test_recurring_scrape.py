"""A records job run again over the same pages (SPEC-11 §4.2, §4.3, §7): pages that did not change end `unchanged`
and are not extracted, whether they answer 304 or their visible text is within three SimHash bits of the last run's.
An unchanged page joins no drift window (SPEC-08 §4.9) and does not count toward `pages_extracted` (ARCHITECTURE §8.3).

Jobs run in a worker loop through the real queue. The web is a stub origin on an RFC 2606 host that can answer with
an ETag and honour If-None-Match (RFC 9110 §13.1.2); no network, no browser.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, Validators
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    Capture,
    Extraction,
    ExtractionConfig,
    Job,
    JobId,
    ProgressiveState,
    Project,
    Record,
    Site,
    SiteId,
    TaskOutcome,
    UrlState,
    UrlTask,
)
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetching import Fetching
from crawlerai.storage.capture_bundle import sha256_hex
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import run_worker

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("site")]

TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}
PROSE = "A kettle that boils water quickly and quietly, with a steel body and a handle that stays cool to the touch."
OTHER_PROSE = "A teapot of glazed stoneware that keeps tea warm, with an infuser basket and a lid that does not drip."


def _page(name: str, prose: str = PROSE) -> bytes:
    node = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "offers": {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"},
    }
    return (
        f'<!doctype html><html lang="en"><head><title>{name}</title>'
        f'<script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><main><h1>{name}</h1><p>{prose}</p></main></body></html>"
    ).encode()


@dataclass
class Origin:
    """Answers each URL in `pages` over HTTP; with `etags`, with an ETag of its body, and 304 to a matching
    If-None-Match. `sent` lists the validators each page fetch carried."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, bytes] = field(default_factory=dict)
    etags: bool = False
    sent: list[Validators | None] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url.endswith("/robots.txt"):
            return self.fetch_result(url, 200, b"User-agent: *")
        return await self.conditional(url, policy, validators=None)

    async def conditional(self, url: str, policy: FetchPolicy, *, validators: Validators | None) -> FetchResult:
        self.sent.append(validators)
        body = self.pages[url]
        etag = f'"{sha256_hex(body)[:16]}"'
        if self.etags and validators is not None and validators.etag == etag:
            return self.fetch_result(url, 304, b"")
        return self.fetch_result(url, 200, body, (("ETag", etag),) if self.etags else ())

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        raise AssertionError("the pages are fetched over HTTP")


@pytest.fixture
def origin(fetch_result: Callable[..., FetchResult]) -> Origin:
    return Origin(fetch_result)


@pytest.fixture
def fetching(origin: Origin, tmp_path: Path) -> Fetching:
    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    rungs = Rungs(http=origin.http, browser=origin.browser, conditional=origin.conditional)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
async def site(engine: AsyncEngine, own_origin: str) -> SiteId:
    """The origin's site with a short interval, so a job of its pages runs without waiting a second per page."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        values = {"project_id": project, "host": own_origin[8:], "crawl_delay_ms": 1}
        return (await conn.execute(insert(Site).values(values).returning(Site.id))).scalar_one()


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "version": 1, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


@dataclass(frozen=True)
class Run:
    """What one job did: each task's outcome and whether it kept a capture, by URL, and its extractions."""

    tasks: dict[str, tuple[TaskOutcome | None, bool]]
    extractions: int


async def _run_job(
    engine: AsyncEngine, fetching: Fetching, data: EngineData, urls: list[str], formats: dict[str, Any]
) -> Run:
    request = BatchScrapeRequest.model_validate({"urls": urls, **formats})
    job_id = (await submit_batch(engine, fetching.connector, request, data=data)).job_id
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, {"batch_scrape": scrape_handler(fetching, data, None)}, stop))
    async with asyncio.timeout(60):
        while not await _ended(engine, job_id):
            await asyncio.sleep(0.1)
    stop.set()
    await loop
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.url, UrlTask.outcome, UrlTask.capture_id).where(UrlTask.job_id == job_id)
        )
        tasks = {row.url: (row.outcome, row.capture_id is not None) for row in rows}
        extracted = select(func.count()).select_from(Extraction).join(UrlTask).where(UrlTask.job_id == job_id)
        return Run(tasks, (await conn.execute(extracted)).scalar_one())


def _records(schema: SchemaDef) -> dict[str, Any]:
    return {"formats": ["records"], "schema": {"id": str(schema.id)}, "page_kind": "detail"}


async def _ended(engine: AsyncEngine, job_id: JobId) -> bool:
    async with engine.connect() as conn:
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    return status in ("completed", "failed", "cancelled")


async def _count(engine: AsyncEngine, model: type[Record] | type[Capture]) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(select(func.count()).select_from(model))).scalar_one()


@pytest.mark.parametrize("etags", [False, True], ids=["fingerprint", "304"])
async def test_a_rerun_over_unchanged_pages_is_unchanged_and_extracts_nothing(
    engine: AsyncEngine,
    fetching: Fetching,
    origin: Origin,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    etags: bool,
) -> None:
    origin.etags = etags
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red")]
    origin.pages = {urls[0]: _page("Blue kettle"), urls[1]: _page("Red kettle")}
    first = await _run_job(engine, fetching, engine_data, urls, _records(kettle_schema))
    records, captures = await _count(engine, Record), await _count(engine, Capture)

    again = await _run_job(engine, fetching, engine_data, urls, _records(kettle_schema))

    assert first == Run({url: ("extracted", True) for url in urls}, extractions=2)
    # A 304 downloads no page, so it keeps no capture; a page fetched whole keeps its capture for replay (§4.3).
    assert again == Run({url: ("unchanged", not etags) for url in urls}, extractions=0)
    assert await _count(engine, Record) == records
    assert await _count(engine, Capture) == captures + (0 if etags else 2)


async def test_a_page_whose_text_changed_is_extracted_again(
    engine: AsyncEngine,
    fetching: Fetching,
    origin: Origin,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red")]
    origin.pages = {urls[0]: _page("Blue kettle"), urls[1]: _page("Red kettle")}
    await _run_job(engine, fetching, engine_data, urls, _records(kettle_schema))
    origin.pages[urls[1]] = _page("Red teapot", OTHER_PROSE)

    again = await _run_job(engine, fetching, engine_data, urls, _records(kettle_schema))

    assert again == Run({urls[0]: ("unchanged", True), urls[1]: ("extracted", True)}, extractions=1)
    # And the next run finds the changed page unchanged against its new fingerprint.
    third = await _run_job(engine, fetching, engine_data, urls, _records(kettle_schema))
    assert third.tasks == {url: ("unchanged", True) for url in urls}


async def _counted(engine: AsyncEngine, site_id: SiteId) -> tuple[dict[str, Any], int]:
    """The site's config's drift window and the pages its progressive state counted."""
    query = (
        select(ExtractionConfig.drift_window, ProgressiveState.pages_extracted)
        .join(ProgressiveState, ProgressiveState.site_id == ExtractionConfig.site_id)
        .where(ExtractionConfig.site_id == site_id)
    )
    async with engine.connect() as conn:
        return (await conn.execute(query)).tuples().one()


@pytest.mark.parametrize("etags", [False, True], ids=["fingerprint", "304"])
async def test_unchanged_pages_join_no_drift_window_and_count_no_extracted_page(
    engine: AsyncEngine,
    fetching: Fetching,
    origin: Origin,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    heading_config: Callable[[SiteId, SchemaDef, int], dict[str, Any]],
    site: SiteId,
    etags: bool,
) -> None:
    origin.etags = etags
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red")]
    origin.pages = {urls[0]: _page("Blue kettle"), urls[1]: _page("Red kettle")}
    async with engine.begin() as conn:
        await conn.execute(insert(ExtractionConfig).values(heading_config(site, kettle_schema, 1)))
    records = _records(kettle_schema)
    try:
        await _run_job(engine, fetching, engine_data, urls, records)
        first = await _counted(engine, site)
        again = await _run_job(engine, fetching, engine_data, urls, records)
        unchanged = await _counted(engine, site)
        origin.pages[urls[1]] = _page("Red teapot", OTHER_PROSE)
        await _run_job(engine, fetching, engine_data, urls, records)
        changed = await _counted(engine, site)
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site))

    assert first == ({"title": [[True, True]] * 2}, 2)
    assert unchanged == first
    assert again.tasks == {url: ("unchanged", not etags) for url in urls}
    # The one page that changed is extracted with the config, so it joins the window and counts.
    assert changed == ({"title": [[True, True]] * 3}, 3)


async def test_a_page_that_changed_only_a_nonce_is_unchanged(
    engine: AsyncEngine,
    fetching: Fetching,
    origin: Origin,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    origin.pages[url] = _page("Blue kettle", f"{PROSE} Session 4f9c2a7e1b8d6c3a5e0f ends.")
    await _run_job(engine, fetching, engine_data, [url], _records(kettle_schema))
    origin.pages[url] = _page("Blue kettle", f"{PROSE} Session 9b1e7d3c5a2f8e6b0d4c ends.")

    again = await _run_job(engine, fetching, engine_data, [url], _records(kettle_schema))

    assert again.tasks == {url: ("unchanged", True)}


async def test_validators_are_sent_only_where_a_record_of_the_schema_version_stands(
    engine: AsyncEngine,
    fetching: Fetching,
    origin: Origin,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    origin.etags = True
    url = f"{own_origin}/kettles/blue"
    origin.pages[url] = _page("Blue kettle")
    await _run_job(engine, fetching, engine_data, [url], _records(kettle_schema))
    async with engine.begin() as conn:
        changes = SchemaChanges.model_validate(
            {"fields": {"title": {**TITLE, "description": "The kettle's name"}, "price": PRICE}}
        )
        newer = await registry.new_version(conn, kettle_schema.name, changes, "user")

    # No record of the new version stands for the page, so nothing may answer for it: it is fetched and extracted.
    other = await _run_job(engine, fetching, engine_data, [url], _records(newer))
    same = await _run_job(engine, fetching, engine_data, [url], _records(kettle_schema))

    assert (other.tasks, other.extractions) == ({url: ("extracted", True)}, 1)
    assert same.tasks == {url: ("unchanged", False)}
    first, by_other, by_same = origin.sent
    assert (first, by_other) == (None, None)
    assert by_same is not None and by_same.etag is not None


async def test_a_job_without_records_neither_reads_nor_writes_url_state(
    engine: AsyncEngine, fetching: Fetching, origin: Origin, own_origin: str, engine_data: EngineData
) -> None:
    origin.etags = True
    url = f"{own_origin}/kettles/blue"
    origin.pages[url] = _page("Blue kettle")

    runs = [await _run_job(engine, fetching, engine_data, [url], {"formats": ["markdown"]}) for _ in range(2)]

    assert [run.tasks for run in runs] == [{url: ("extracted", True)}] * 2
    assert origin.sent == [None, None]
    async with engine.connect() as conn:
        assert (await conn.execute(select(UrlState.canonical_url))).all() == []
