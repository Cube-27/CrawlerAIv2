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
from crawlerai.acquire.session import CookieExport
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    EvalRunId,
    Extraction,
    ExtractionConfig,
    Job,
    JobId,
    Record,
    SiteId,
    UrlTask,
)
from crawlerai.db.queue import MAX_ATTEMPTS
from crawlerai.llm.client import NO_LLM, LLMClient, MeteredClient, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.pipeline import UNRANKED, EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.jobs import PageOutputPage, ResultsQuery
from crawlerai.services.records import RecordPage
from crawlerai.storage.fs import FsStore
from crawlerai.worker.browser import SharedBrowser
from crawlerai.worker.handlers.table import task_handlers
from crawlerai.worker.loop import run_worker
from tests.db.conftest import listing_page, listing_schema

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
    the HTTP rung raise. The browser answers the same pages, or a URL's page in `renders`; a fetch of a URL in
    `crashing` kills its session."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    raising: set[str] = field(default_factory=set)
    crashing: set[str] = field(default_factory=set)
    renders: dict[str, bytes] = field(default_factory=dict)
    browser_fetches: list[tuple[int, str]] = field(default_factory=list)
    http_fetches: list[tuple[str, FetchPolicy]] = field(default_factory=list)
    policies: list[FetchPolicy] = field(default_factory=list)  # of the browser's fetches
    sessions: int = 0

    def answer(self, url: str, method: str = "http") -> FetchResult:
        status, body = self.pages.get(url, (404, b"gone"))
        return self.fetch_result(url, status, body, block_class="ok" if status == 200 else "not_found", method=method)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url in self.raising:
            raise Crash("the rung raised")
        self.http_fetches.append((url, policy))
        return self.answer(url)

    @asynccontextmanager
    async def launch(self) -> AsyncIterator[Session]:
        self.sessions += 1
        yield Session(self.sessions)

    async def in_browser(
        self, session: Session, url: str, policy: FetchPolicy, export: CookieExport | None = None
    ) -> FetchResult:
        self.browser_fetches.append((session.number, url))
        self.policies.append(policy)
        if url in self.crashing:
            session.connected = False
            return self.fetch_result(url, 0, b"", block_class="error", error="browser crashed", method="browser")
        if url in self.renders:
            return self.fetch_result(url, 200, self.renders[url], method="browser")
        result = self.answer(url, "browser")
        files = {**({"screenshot.png": b"png " + url.encode()} if policy.screenshot else {})}
        return result.model_copy(update={"artifacts": files})


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
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def _batch(urls: list[str], *formats: str, **members: Any) -> BatchScrapeRequest:
    return BatchScrapeRequest.model_validate({"urls": urls, "formats": list(formats), **members})


def _records(urls: list[str], schema: SchemaDef) -> BatchScrapeRequest:
    return _batch(urls, "records", schema={"id": str(schema.id)}, page_kind="detail")


async def _run(
    engine: AsyncEngine, fetching: Fetching, data: EngineData | None, *job_ids: JobId, llm: LLMClient = NO_LLM
) -> None:
    """Run a worker loop with the worker's handlers until every one of the jobs has ended; role C runs on `llm`."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, task_handlers(fetching, data, None, llm=llm), stop))
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


async def test_a_batch_keys_its_tasks_by_the_url_with_its_query_pairs_sorted(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    # SPEC-10 §4.1: every job kind keys a page by one canonical form, so its records form one entity whatever job
    # fetched it. Two orders of the same pairs are one page.
    urls = [f"{own_origin}/p?id=5&color=red", f"{own_origin}/p?color=red&id=5"]

    submitted = await submit_batch(engine, fetching.connector, _batch(urls, "markdown"), data=None)

    async with engine.connect() as conn:
        query = select(UrlTask.canonical_url).where(UrlTask.job_id == submitted.job_id)
        canonical = (await conn.execute(query)).scalars().all()
    assert canonical == [f"{own_origin}/p?color=red&id=5"]


@pytest.mark.parametrize(
    ("member", "url"),
    [("urls", f"https://{PRIVATE_HOST}/x"), ("webhook_url", f"https://{PRIVATE_HOST}/hook")],
)
async def test_a_refused_target_queues_nothing(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, member: str, url: str
) -> None:
    urls = [f"{own_origin}/a", url] if member == "urls" else [f"{own_origin}/a"]
    batch = _batch(urls, "markdown", **({"webhook_url": url} if member == "webhook_url" else {}))

    with pytest.raises(TargetsRejected) as rejected:
        await submit_batch(engine, fetching.connector, batch, data=None)

    assert rejected.value.member == ("urls[1]" if member == "urls" else "webhook_url")
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "batch_scrape"))).all() == []


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
    assert isinstance(first, PageOutputPage)
    assert isinstance(second, PageOutputPage)
    assert second.next_cursor is None
    blue, red, gone = first.items + second.items
    assert [item.url for item in (blue, red, gone)] == urls
    assert [item.outcome for item in (blue, red, gone)] == ["extracted", "extracted", "not_found"]
    assert blue.markdown is not None
    assert "boils water quickly" in blue.markdown
    assert blue.links == red.links == [f"{own_origin}/kettles/other"]
    assert (gone.capture_id is not None, gone.markdown, gone.links) == (True, None, None)
    assert (blue.html, blue.raw_html, blue.metadata) == (None, None, None)


@pytest.mark.usefixtures("site")
@pytest.mark.usefixtures("site")
async def test_a_screenshot_forces_the_browser_and_each_pages_file_is_stored_beside_its_capture(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/kettles/{name}" for name in ("blue", "red")]
    for url, name in zip(urls, ("Blue kettle", "Red kettle"), strict=True):
        web.pages[url] = (200, _page(name))
    request = _batch(urls, "screenshot", "markdown_fit", fetch={"screenshot": "full_page"})
    submitted = await submit_batch(engine, fetching.connector, request, data=None)

    await _run(engine, fetching, None, submitted.job_id)

    page = await _results(engine, fetching, submitted.job_id)
    assert sorted(url for _, url in web.browser_fetches) == urls
    assert {(p.method_hint, p.screenshot, p.pdf) for p in web.policies} == {("browser", "full_page", False)}
    assert [item.screenshot.url for item in page.items if item.screenshot] == [
        f"/v1/captures/{item.capture_id}/artifacts/screenshot.png" for item in page.items
    ]
    assert len(page.items) == 2
    assert all("kettle" in (item.markdown_fit or "") for item in page.items)
    files = [key for key in fetching.store.list("captures/") if key.endswith(".screenshot.png")]
    assert sorted(fetching.store.get(key) for key in files) == [b"png " + url.encode() for url in urls]


async def test_a_schema_without_the_records_format_is_ignored(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _page("Blue kettle"))
    # The schema's page kind is not the request's: unread without `records`, so not refused either.
    batch = _batch([url], "markdown", schema={"id": str(kettle_schema.id)}, page_kind="listing")
    submitted = await submit_batch(engine, fetching.connector, batch, data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id)

    async with engine.connect() as conn:
        job = (await conn.execute(select(Job.schema_id, Job.pinned).where(Job.id == submitted.job_id))).one()
    results = await _results(engine, fetching, submitted.job_id)
    assert tuple(job) == (None, None)
    assert isinstance(results, PageOutputPage)
    [item] = results.items
    assert item.markdown is not None
    assert "boils water quickly" in item.markdown


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
    assert isinstance(first, RecordPage)
    assert isinstance(second, RecordPage)
    records = first.items + second.items
    assert second.next_cursor is None
    titles = sorted((r.fields["title"].value, r.complete) for r in records)
    assert titles == [("Blue kettle", True), ("Plain kettle", False), ("Red kettle", True)]


def _price_reply(fetch_result: Callable[..., FetchResult], url: str, body: bytes) -> ProviderReply:
    """Role C's claim of the price the page shows only in its text (SPEC-06 §4.4)."""
    text = ParsedPage.of(fetch_result(url, 200, body).bundle).cleaned_text.text
    start = text.index("19.90 EUR")
    price = {"shown": True, "ref": "", "value": "19.90 EUR", "start": start, "end": start + len("19.90 EUR")}
    return ProviderReply(model="fake-fast", text=json.dumps({"fields": {"price": price}}), tokens_in=7, tokens_out=3)


async def test_role_c_fills_a_required_field_the_page_has_only_in_its_text_as_a_scrape_does(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # SPEC-10 §4.3: a batch's handler is the scrape's steps, role C included (D-1006), charged to the batch's job.
    url = f"{own_origin}/kettles/blue"
    body = _page("Blue kettle", offers=False).replace(b"</main>", b"<p>19.90 EUR</p></main>")
    web.pages[url] = (200, body)
    llm = MeteredClient([FakeProvider([_price_reply(fetch_result, url, body)])], engine)
    submitted = await submit_batch(engine, fetching.connector, _records([url], kettle_schema), data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id, llm=llm)

    summary = await _summary(engine, submitted.job_id)
    async with engine.connect() as conn:
        record = (await conn.execute(select(Record.complete, Record.data))).one()
    assert (summary.outcomes.extracted, summary.usage["llm_calls"]) == (1, 1)
    assert (record.complete, record.data["price"]) == (True, {"amount": "19.90", "currency": "EUR"})


async def test_a_batch_budget_of_no_llm_calls_leaves_the_field_missing(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # SPEC-10 §4.3 `budget`: the job's `llm_calls` bound role C as a scrape's do (SPEC-06 §4.2).
    url = f"{own_origin}/kettles/blue"
    body = _page("Blue kettle", offers=False).replace(b"</main>", b"<p>19.90 EUR</p></main>")
    web.pages[url] = (200, body)
    provider = FakeProvider([_price_reply(fetch_result, url, body)])
    request = _batch(
        [url], "records", schema={"id": str(kettle_schema.id)}, page_kind="detail", budget={"llm_calls": 0}
    )
    submitted = await submit_batch(engine, fetching.connector, request, data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id, llm=MeteredClient([provider], engine))

    page = await _results(engine, fetching, submitted.job_id)
    assert isinstance(page, RecordPage)
    price = page.items[0].fields["price"]
    assert (price.status, price.reason, len(provider.calls)) == ("missing", "llm_budget", 0)


async def test_a_listing_page_keeps_a_record_per_row_and_one_without_rows_is_partial(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, schema_name: str, engine_data: EngineData
) -> None:
    listed, empty = f"{own_origin}/kettles", f"{own_origin}/kettles/none"
    web.pages[listed] = (200, listing_page(own_origin, ["Blue kettle", "Red kettle", "Green kettle"]))
    web.pages[empty] = (200, _page("Blue kettle"))
    schema = await listing_schema(engine, schema_name)
    request = _batch([listed, empty], "records", schema={"id": str(schema.id)}, page_kind="listing")
    submitted = await submit_batch(engine, fetching.connector, request, data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id)

    summary = await _summary(engine, submitted.job_id)
    results = await _results(engine, fetching, submitted.job_id)
    assert (summary.outcomes.extracted, summary.outcomes.partial) == (1, 1)
    assert isinstance(results, RecordPage)
    assert sorted(str(r.fields["title"].value) for r in results.items) == ["Blue kettle", "Green kettle", "Red kettle"]
    # Master plan 2026-10-18 §3.1: both documents show fewer item blocks than a listing does, so each is rendered once;
    # neither render lists more, so both HTTP captures are kept.
    assert sorted(url for _, url in web.browser_fetches) == [listed, empty]


async def test_a_listing_whose_rows_only_a_render_holds_keeps_the_renders_rows(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, schema_name: str, engine_data: EngineData
) -> None:
    # Owner #54: the HTTP page lists links that are not its items; the render's ItemList gives the rows.
    url = f"{own_origin}/kettles"
    related = "".join(f'<li><a href="{own_origin}/blog/{n}">Post {n}</a></li>' for n in range(1, 4))
    web.pages[url] = (200, f"<!doctype html><html><body><ul>{related}</ul></body></html>".encode())
    web.renders[url] = listing_page(own_origin, ["Blue kettle", "Red kettle"])
    schema = await listing_schema(engine, schema_name)
    request = _batch([url], "records", schema={"id": str(schema.id)}, page_kind="listing")
    submitted = await submit_batch(engine, fetching.connector, request, data=engine_data)

    await _run(engine, fetching, engine_data, submitted.job_id)

    results = await _results(engine, fetching, submitted.job_id)
    assert isinstance(results, RecordPage)
    assert sorted(str(r.fields["title"].value) for r in results.items) == ["Blue kettle", "Red kettle"]
    assert [fetched for _, fetched in web.browser_fetches] == [url]


# INV-28: settings pinned at submit.


def _calibration(precision: float) -> Calibration:
    bucket = Bucket(n=40, precision=precision)
    return Calibration(
        eval_run_id=EvalRunId(uuid7()),
        git_sha="0" * 40,
        buckets={"money|structured": bucket, "text|structured": bucket},
    )


@pytest.mark.usefixtures("site")
async def test_a_job_runs_with_the_schema_and_engine_data_pinned_at_submit(
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
    # Then the schema the job named is edited in place, dropping `title`, and the engine's data changes.
    async with engine.begin() as conn:
        edited = await registry.update_schema(
            conn, kettle_schema, SchemaChanges.model_validate({"fields": {"price": PRICE}})
        )
    later = await submit_batch(engine, fetching.connector, _records([url], edited), data=after)

    # Both run in a worker whose own data is the new one.
    await _run(engine, fetching, after, pinned.job_id, later.job_id)

    async with engine.connect() as conn:
        rows = await conn.execute(
            select(Record.job_id, Record.schema_id, Record.data, Record.field_meta).where(
                Record.job_id.in_((pinned.job_id, later.job_id))
            )
        )
        by_job = {row.job_id: row for row in rows}
    old, new = by_job[pinned.job_id], by_job[later.job_id]
    # The pinned job: the schema as submitted, with a ranked title, and the old calibration.
    assert (old.schema_id, old.data["title"], old.field_meta["price"]["confidence"]) == (
        kettle_schema.id,
        "Blue kettle",
        0.99,
    )
    # The later job: the edited schema, without a title, and the new calibration.
    assert (new.schema_id, sorted(new.field_meta), new.field_meta["price"]["confidence"]) == (
        kettle_schema.id,
        ["price"],
        0.97,
    )


async def test_a_job_runs_with_the_site_config_active_when_it_was_submitted(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    heading_config: Callable[[SiteId, SchemaDef, int], dict[str, Any]],
    site: SiteId,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _page("Blue kettle"))
    async with engine.begin() as conn:
        row = heading_config(site, kettle_schema, 1)
        first = (await conn.execute(insert(ExtractionConfig).values(row).returning(ExtractionConfig.id))).scalar_one()
    try:
        pinned = await submit_batch(engine, fetching.connector, _records([url], kettle_schema), data=engine_data)
        # Then the config is suspended and a new version activates.
        async with engine.begin() as conn:
            await conn.execute(update(ExtractionConfig).where(ExtractionConfig.id == first).values(status="suspended"))
            await conn.execute(insert(ExtractionConfig).values(heading_config(site, kettle_schema, 2)))
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
            await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site))


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


# The request context and cache modes per page (D-1432, D-1435, D-1439).


async def test_a_batchs_workers_send_the_callers_cookie_with_every_page(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    urls = [f"{own_origin}/a", f"{own_origin}/b"]
    for url in urls:
        web.pages[url] = (200, _page("Kettle"))
    batch = _batch(urls, "markdown", fetch={"cookies": {"sid": "s3cret"}})

    submitted = await submit_batch(engine, fetching.connector, batch, data=None)
    await _run(engine, fetching, None, submitted.job_id)

    sent = {
        url: [value.get_secret_value() for _, value in policy.context.cookies]
        for url, policy in web.http_fetches
        if policy.context is not None
    }
    assert sent == {url: ["s3cret"] for url in urls}  # robots.txt goes without it


async def test_cache_only_serves_each_page_from_its_stored_capture_or_fails_it(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    stored, missing = f"{own_origin}/a", f"{own_origin}/never"
    web.pages[stored] = (200, _page("Kettle"))
    first = await submit_batch(engine, fetching.connector, _batch([stored], "markdown"), data=None)
    await _run(engine, fetching, None, first.job_id)
    fetched = len(web.http_fetches)

    again = _batch([stored, missing], "markdown", fetch={"cache": "only"})
    second = await submit_batch(engine, fetching.connector, again, data=None)
    await _run(engine, fetching, None, second.job_id)

    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(UrlTask.url, UrlTask.status, UrlTask.last_error).where(UrlTask.job_id == second.job_id)
            )
        ).all()
    assert len(web.http_fetches) == fetched  # nothing fetched
    assert {(url, status, error) for url, status, error in rows} == {
        (stored, "done", None),
        (missing, "failed", "not_cached"),
    }
