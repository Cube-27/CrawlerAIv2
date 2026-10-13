"""`batch_scrape` jobs (SPEC-10 §4.3): submitted through the batch service, run by worker loops through the real queue,
and read back through the jobs service; with the settings pinned at submit (INV-28) and each task isolated from the
others (INV-31).

The web is a stub that answers synthetic pages on RFC 2606 hosts, the resolver a stub and the browser a stub session
that can crash: no network, no Chromium.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    EvalRunId,
    Extraction,
    ExtractionConfig,
    Job,
    JobId,
    Project,
    Record,
    Site,
    SiteId,
    UrlTask,
)
from crawlerai.db.queue import MAX_ATTEMPTS
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.pipeline import UNRANKED, EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.batch import BatchRejected, BatchScrapeRequest, submit_batch
from crawlerai.services.jobs import PageOutputPage, ResultsQuery
from crawlerai.services.records import RecordPage
from crawlerai.services.scrape import Fetching, RecordsUnavailable
from crawlerai.storage.fs import FsStore
from crawlerai.worker.browser import SharedBrowser
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import run_worker

pytestmark = pytest.mark.anyio

PRIVATE_HOST = "intranet.example.test"
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}


def _page(name: str, *, offers: bool = True) -> bytes:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return (
        f'<!doctype html><html lang="en"><head><title>{name}</title>'
        f'<script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><main><h1>{name}</h1><p>A kettle that boils water quickly and quietly.</p>"
        f'<a href="/kettles/other">Another kettle</a></main></body></html>'
    ).encode()


class Crash(Exception):
    pass


@dataclass
class Session:
    number: int
    connected: bool = True


@dataclass
class Web:
    """Answers each URL from `pages` as (status, body) over HTTP; anything else is a 404. A URL in `raising` makes
    the HTTP rung raise. The browser answers the same pages; a fetch of a URL in `crashing` kills its session."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    raising: set[str] = field(default_factory=set)
    crashing: set[str] = field(default_factory=set)
    browser_fetches: list[tuple[int, str]] = field(default_factory=list)
    sessions: int = 0

    def answer(self, url: str, method: str = "http") -> FetchResult:
        status, body = self.pages.get(url, (404, b"gone"))
        return self.fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found", method=method)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url in self.raising:
            raise Crash("the rung raised")
        return self.answer(url)

    @asynccontextmanager
    async def launch(self) -> AsyncIterator[Session]:
        self.sessions += 1
        yield Session(self.sessions)

    async def in_browser(self, session: Session, url: str, policy: FetchPolicy) -> FetchResult:
        self.browser_fetches.append((session.number, url))
        if url in self.crashing:
            session.connected = False
            return self.fetch_result(url, 0, b"", block_class="error", error="browser crashed", method="browser")
        return self.answer(url, "browser")


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n")})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    async def resolve(host: str) -> list[IPAddress]:
        return [ip_address("10.0.0.7" if host == PRIVATE_HOST else "93.184.215.14")]

    browser = SharedBrowser(web.launch, web.in_browser, lambda session: session.connected)
    rungs = Rungs(http=web.http, browser=browser.fetch)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
async def site(engine: AsyncEngine, own_origin: str) -> None:
    """The origin's site with a short interval, so a batch of its pages runs without waiting a second per page."""
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        await conn.execute(insert(Site).values(project_id=project, host=own_origin[8:], crawl_delay_ms=1))


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "version": 1, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def _batch(urls: list[str], *formats: str, **members: Any) -> BatchScrapeRequest:
    return BatchScrapeRequest.model_validate({"urls": urls, "formats": list(formats), **members})


def _records(urls: list[str], schema: SchemaDef) -> BatchScrapeRequest:
    return _batch(urls, "records", schema={"id": str(schema.id)}, page_kind="detail")


async def _run(engine: AsyncEngine, fetching: Fetching, data: EngineData | None, *job_ids: JobId) -> None:
    """Run a worker loop until every one of the jobs has ended."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, {"batch_scrape": scrape_handler(fetching, data, None)}, stop))
    async with asyncio.timeout(60):
        while not await _ended(engine, job_ids):
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def _ended(engine: AsyncEngine, job_ids: tuple[JobId, ...]) -> bool:
    async with engine.connect() as conn:
        statuses = (await conn.execute(select(Job.status).where(Job.id.in_(job_ids)))).scalars().all()
    return all(status in ("completed", "failed", "cancelled") for status in statuses)


async def _results(engine: AsyncEngine, fetching: Fetching, job_id: JobId, **query: Any) -> Any:
    async with engine.connect() as conn:
        return await jobs.job_results(conn, job_id, ResultsQuery(**query), store=fetching.store)


async def _summary(engine: AsyncEngine, job_id: JobId) -> jobs.JobSummary:
    async with engine.connect() as conn:
        return await jobs.get_job(conn, job_id)


# Submitting.


async def test_a_submitted_batch_is_a_queued_job_with_one_task_per_canonical_url(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    urls = [f"{own_origin}/a", f"{own_origin}/b", f"{own_origin}/a#reviews", f"{own_origin}/c"]

    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)

    summary = await _summary(engine, submitted.job_id)
    async with engine.connect() as conn:
        tasks = (await conn.execute(select(UrlTask.url).where(UrlTask.job_id == submitted.job_id))).scalars().all()
        job = (await conn.execute(select(Job).where(Job.id == submitted.job_id))).one()
    assert (summary.kind, summary.status, summary.counts.queued) == ("batch_scrape", "queued", 3)
    assert sorted(tasks) == [f"{own_origin}/a", f"{own_origin}/b", f"{own_origin}/c"]
    assert (job.schema_id, job.pinned, job.request["formats"]) == (None, None, ["markdown"])


@pytest.mark.parametrize(
    ("member", "url"),
    [("urls", f"https://{PRIVATE_HOST}/x"), ("webhook_url", f"https://{PRIVATE_HOST}/hook")],
)
async def test_a_refused_target_queues_nothing(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, member: str, url: str
) -> None:
    urls = [f"{own_origin}/a", url] if member == "urls" else [f"{own_origin}/a"]
    batch = _batch(urls, "markdown", **({"webhook_url": url} if member == "webhook_url" else {}))

    with pytest.raises(BatchRejected) as rejected:
        await submit_batch(engine, fetching.connector, batch, data=None)

    assert rejected.value.member == ("urls[1]" if member == "urls" else "webhook_url")
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "batch_scrape"))).all() == []


async def test_records_need_the_engine_data(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, kettle_schema: SchemaDef
) -> None:
    batch = _records([f"{own_origin}/a"], kettle_schema)

    with pytest.raises(RecordsUnavailable):
        await submit_batch(engine, fetching.connector, batch, data=None)


# Running.


@pytest.mark.usefixtures("site")
async def test_page_outputs_are_made_from_each_tasks_capture_and_paginate(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red", "gone")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[1]] = (200, _page("Red kettle"))
    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown", "links"), data=None)

    await _run(engine, fetching, None, submitted.job_id)

    summary = await _summary(engine, submitted.job_id)
    first = await _results(engine, fetching, submitted.job_id, limit=2)
    second = await _results(engine, fetching, submitted.job_id, limit=2, cursor=first.next_cursor)
    assert (summary.status, summary.counts.done, summary.outcomes.extracted, summary.outcomes.not_found) == (
        "completed",
        3,
        2,
        1,
    )
    assert isinstance(first, PageOutputPage) and isinstance(second, PageOutputPage)
    assert second.next_cursor is None
    blue, red, gone = first.items + second.items
    assert [item.url for item in (blue, red, gone)] == urls
    assert [item.outcome for item in (blue, red, gone)] == ["extracted", "extracted", "not_found"]
    assert blue.markdown is not None and "boils water quickly" in blue.markdown
    assert blue.links == red.links == [f"{own_origin}/kettles/other"]
    assert (gone.capture_id is not None, gone.markdown, gone.links) == (True, None, None)
    assert (blue.html, blue.raw_html, blue.metadata) == (None, None, None)


@pytest.mark.usefixtures("site")
async def test_records_are_stored_per_page_and_an_incomplete_page_is_partial(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red", "plain")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[1]] = (200, _page("Red kettle"))
    web.pages[urls[2]] = (200, _page("Plain kettle", offers=False))
    submitted = await submit_batch(engine, fetching.connector, _records(urls, kettle_schema), data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id)

    summary = await _summary(engine, submitted.job_id)
    first = await _results(engine, fetching, submitted.job_id, limit=2)
    second = await _results(engine, fetching, submitted.job_id, limit=2, cursor=first.next_cursor)
    assert (summary.outcomes.extracted, summary.outcomes.partial) == (2, 1)
    assert isinstance(first, RecordPage) and isinstance(second, RecordPage)
    records = first.items + second.items
    assert second.next_cursor is None
    titles = sorted((r.fields["title"].value, r.complete) for r in records)
    assert titles == [("Blue kettle", True), ("Plain kettle", False), ("Red kettle", True)]


# INV-28: settings pinned at submit.


def _calibration(precision: float) -> Calibration:
    bucket = Bucket(n=40, precision=precision)
    return Calibration(
        eval_run_id=EvalRunId(uuid7()),
        git_sha="0" * 40,
        buckets={"money|structured": bucket, "text|structured": bucket},
    )


@pytest.mark.usefixtures("site")
async def test_a_job_runs_with_the_schema_version_and_engine_data_pinned_at_submit(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    before = replace(engine_data, calibration=_calibration(0.99))
    after = replace(engine_data, orders=UNRANKED, calibration=_calibration(0.97))
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _page("Blue kettle"))
    pinned = await submit_batch(engine, fetching.connector, _records([url], kettle_schema), data=before)
    # Then a new schema version replaces the one the job named, and the engine's data changes.
    async with engine.begin() as conn:
        changes = SchemaChanges.model_validate(
            {"fields": {"title": {**TITLE, "description": "The box's name"}, "price": PRICE}}
        )
        newer = await registry.new_version(conn, kettle_schema.name, changes, "user")
        await registry.retire(conn, kettle_schema.id)
    later = await submit_batch(engine, fetching.connector, _records([url], newer), data=after)

    # Both run in a worker whose own data is the new one.
    await _run(engine, fetching, after, pinned.job_id, later.job_id)

    async with engine.connect() as conn:
        rows = await conn.execute(
            select(Record.job_id, Record.schema_version, Record.data, Record.field_meta).where(
                Record.job_id.in_((pinned.job_id, later.job_id))
            )
        )
        by_job = {row.job_id: row for row in rows}
    old, new = by_job[pinned.job_id], by_job[later.job_id]
    # The pinned job: version 1, a ranked title, the old calibration.
    assert (old.schema_version, old.data["title"], old.field_meta["price"]["confidence"]) == (1, "Blue kettle", 0.99)
    # The later job: version 2, the title unranked (no fitted order), the new calibration.
    assert (new.schema_version, new.field_meta["title"]["status"], new.field_meta["price"]["confidence"]) == (
        2,
        "missing",
        0.97,
    )


def _config(site_id: SiteId, schema: SchemaDef, version: int) -> dict[str, Any]:
    """An active config row reading the title from the page's heading."""
    ir = {
        "ir_version": "1",
        "site": "unused.example.test",
        "schema": {"name": schema.name, "version": schema.version},
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
        "schema_version": schema.version,
        "page_kind": "detail",
        "version": version,
        "status": "active",
        "ir": ir,
        "origin": "induced",
        "field_status": {"title": "corroborated"},
    }


@pytest.mark.usefixtures("site")
async def test_a_job_runs_with_the_site_config_active_when_it_was_submitted(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _page("Blue kettle"))
    async with engine.begin() as conn:
        site_id = (await conn.execute(select(Site.id).where(Site.host == own_origin[8:]))).scalar_one()
        first = (
            await conn.execute(
                insert(ExtractionConfig).values(_config(site_id, kettle_schema, 1)).returning(ExtractionConfig.id)
            )
        ).scalar_one()
    try:
        pinned = await submit_batch(engine, fetching.connector, _records([url], kettle_schema), data=engine_data)
        # Then the config is suspended and a new version activates.
        async with engine.begin() as conn:
            await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == first).values(status="suspended"))
            await conn.execute(insert(ExtractionConfig).values(_config(site_id, kettle_schema, 2)))
        later = await submit_batch(engine, fetching.connector, _records([url], kettle_schema), data=engine_data)

        await _run(engine, fetching, engine_data, pinned.job_id, later.job_id)

        async with engine.connect() as conn:
            rows = await conn.execute(
                select(UrlTask.job_id, Extraction.mode, Extraction.config_version)
                .join(Extraction, Extraction.url_task_id == UrlTask.id)
                .where(UrlTask.job_id.in_((pinned.job_id, later.job_id)))
            )
            versions = {row.job_id: (row.mode, row.config_version) for row in rows}
            window: dict[str, Any] = (
                await conn.execute(select(ExtractionConfig.drift_window).where(ExtractionConfig.id == first))
            ).scalar_one()
        assert versions == {pinned.job_id: ("config", 1), later.job_id: ("config", 2)}
        # A config no longer active keeps no drift window (`drift.record_run`).
        assert window == {}
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site_id))


# INV-31: one task's failure never fails another.


async def _last_attempt(engine: AsyncEngine, url: str) -> None:
    """Make the next claim of `url`'s task its last attempt, so a transient failure ends it."""
    async with engine.begin() as conn:
        await conn.execute(update(UrlTask).where(UrlTask.url == url).values(attempts=MAX_ATTEMPTS - 1))


@pytest.mark.usefixtures("site")
async def test_a_task_that_raises_fails_alone(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "broken", "red")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[2]] = (200, _page("Red kettle"))
    web.raising.add(urls[1])
    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)
    await _last_attempt(engine, urls[1])

    await _run(engine, fetching, None, submitted.job_id)

    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.url, UrlTask.status, UrlTask.last_error).where(UrlTask.job_id == submitted.job_id)
        )
        tasks = {row.url: (row.status, row.last_error) for row in rows}
    assert tasks == {
        urls[0]: ("done", None),
        urls[1]: ("failed", "Crash: the rung raised"),
        urls[2]: ("done", None),
    }
    assert (await _summary(engine, submitted.job_id)).status == "completed"


@pytest.mark.usefixtures("site")
async def test_a_crashed_browser_fails_only_its_task_and_restarts_once_for_it(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "crashing", "red")]
    web.pages[urls[0]] = (200, _page("Blue kettle"))
    web.pages[urls[2]] = (200, _page("Red kettle"))
    web.crashing.add(urls[1])
    batch = _batch(urls, "markdown", fetch={"method_hint": "browser"})
    submitted = await submit_batch(engine, fetching.connector, batch, data=None)
    await _last_attempt(engine, urls[1])

    await _run(engine, fetching, None, submitted.job_id)

    async with engine.connect() as conn:
        rows = await conn.execute(select(UrlTask.url, UrlTask.status).where(UrlTask.job_id == submitted.job_id))
        statuses = {row.url: row.status for row in rows}
    assert statuses == {urls[0]: "done", urls[1]: "failed", urls[2]: "done"}
    sessions = {url: [number for number, fetched in web.browser_fetches if fetched == url] for url in urls}
    # The crashing page was fetched in the shared browser and in one restart, which died too; the other pages once.
    assert [len(sessions[url]) for url in urls] == [1, 2, 1]
    assert len(set(sessions[urls[1]])) == 2
