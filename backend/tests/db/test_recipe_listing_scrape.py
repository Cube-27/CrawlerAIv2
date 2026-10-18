"""A listing scrape of a site whose active config has a listing recipe (Appendix A #59, SPEC-09 §4.8): the recipe
serves the listing's pages over HTTP, one capture each, until the request's `records` target, with no browser; when it
does not serve the first page, the browser actions run as before (§4.10). The worker's batch and crawl tasks serve
every page of the listing the same way, up to the job's page bound.

The web is a stub answering synthetic JSON on RFC 2606 hosts, the listing rung a stub that records being asked: no
network.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.browser_tab import Drive
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SSRF_REJECTED, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, PagedFetch
from crawlerai.core.settings import Settings
from crawlerai.db.models import (
    Capture,
    Extraction,
    ExtractionConfig,
    Job,
    JobId,
    JobKind,
    Record,
    Site,
    SiteId,
    UrlTask,
    UsageEvent,
)
from crawlerai.llm.client import NO_LLM
from crawlerai.recurring.listing_diff import close_run
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.crawl import CrawlRequest, submit_crawl
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.capture_bundle import CaptureBundle
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler, run_worker
from tests.db.conftest import listing_page, listing_schema, resolve

pytestmark = pytest.mark.anyio

NAMES = [f"Kettle {letter}" for letter in "ABCDEFGH"]
PAGE_SIZE = 3


@dataclass
class Web:
    """robots.txt and the listing page over HTTP, the listing endpoint as JSON (`up`: whether it answers; `down`: the
    status it fails with), and the listing rung."""

    fetch_result: Callable[..., FetchResult]
    origin: str
    up: bool = True
    down: int = 500
    empty: bool = False
    names: list[str] = field(default_factory=lambda: list(NAMES))
    refused: str | None = None  # the cursor of the page whose request the SSRF guard refuses
    requested: list[JsonRequest] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url.endswith(".xml"):  # a crawl's start task looks for sitemaps: there are none
            return self.fetch_result(url, 404, b"", block_class="not_found")
        if not url.endswith("/robots.txt"):
            self.pages.append(url)
            return self.fetch_result(url, 200, listing_page(self.origin, NAMES[:2]), policy=policy)
        return self.fetch_result(url, 200, b"User-agent: *\nAllow: /\n")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request)
        if not self.up:
            return self.fetch_result(request.page_url, self.down, b"{}", block_class="error", method="api")
        after = parse_qs(urlsplit(request.url).query).get("after", ["0"])[0]
        if after == self.refused:
            error = f"{SSRF_REJECTED} a private address"
            return self.fetch_result(request.page_url, 0, b"", block_class="error", error=error, method="api")
        start = int(after)
        rows = [
            {"label": name, "href": f"{self.origin}/kettles/{start + i}"}
            for i, name in enumerate(self.names[start : start + PAGE_SIZE])
            if not self.empty
        ]
        following = start + PAGE_SIZE if start + PAGE_SIZE < len(self.names) else None
        body = json.dumps({"result": {"rows": rows, "next": None if following is None else str(following)}})
        return self.fetch_result(request.page_url, 200, body.encode(), method="api")

    async def listing(self, url: str, policy: FetchPolicy, drive: Drive) -> PagedFetch:
        self.listed.append(url)
        page = self.fetch_result(url, 200, listing_page(self.origin, NAMES[:2]), method="browser", policy=policy)
        return PagedFetch(pages=(page,), report=None)


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, own_origin)


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.http, browser=web.http, json=web.json, listing=web.listing)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path / "objects"), HostLimiter())


@pytest.fixture
async def schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    return await listing_schema(engine, schema_name)


def _ir(origin: str, schema: SchemaDef) -> dict[str, Any]:
    """A listing config with no page steps and a recipe whose cursor is the answer's `next`."""
    return {
        "ir_version": "1",
        "site": origin.removeprefix("https://"),
        "schema": {"name": schema.name, "digest": document_digest(schema)},
        "page_kind": "listing",
        "fetch": {"method": "browser"},
        "fields": {},
        "api_recipe": {
            "method": "GET",
            "url": f"{origin}/api/kettles?size={PAGE_SIZE}",
            "pagination": {
                "kind": "cursor",
                "where": "query",
                "name": "after",
                "cursor": "$['result']['next']",
                "rows": "$['result']['rows'][*]",
            },
            "map": {"title": "$['label']", "url": "$['href']"},
            "proof": {"validated_on": [str(uuid.UUID(int=1))], "headers_tried": 0, "bound_by": "deterministic"},
        },
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-17T00:00:00Z",
            "engine_version": "t",
        },
    }


@pytest.fixture
async def recipe_config(engine: AsyncEngine, own_origin: str, site: SiteId, schema: SchemaDef) -> AsyncIterator[None]:
    values = {
        "site_id": site,
        "schema_id": schema.id,
        "page_kind": "listing",
        "version": 1,
        "status": "active",
        "ir": _ir(own_origin, schema),
        "origin": "induced",
        "field_status": {},
    }
    async with engine.begin() as conn:
        await conn.execute(insert(ExtractionConfig).values(values))
    yield
    async with engine.begin() as conn:
        await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.site_id == site))


def _request(url: str, schema: SchemaDef, records: int, **fetch: Any) -> ScrapeRequest:
    body = {
        "url": url,
        "formats": ["records"],
        "schema": {"id": str(schema.id)},
        "page_kind": "listing",
        "browser_actions": {"records": records},
        "fetch": fetch,
    }
    return ScrapeRequest.model_validate(body)


async def test_a_listing_recipe_serves_its_pages_over_http_up_to_the_records_target(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles"

    result = await scrape(engine, fetching, _request(url, schema, records=5), data=engine_data)

    assert web.listed == []  # no browser
    assert [parse_qs(urlsplit(r.url).query).get("after") for r in web.requested] == [None, ["3"]]
    assert result.fetch is not None
    assert (result.outcome, result.fetch.method, result.browser_actions) == ("extracted", "api", None)
    assert result.records is not None
    assert [r.fields["title"].value for r in result.records] == NAMES[:6]
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.id).where(UrlTask.job_id == result.job_id))).scalar_one()
        captures = (
            await conn.execute(
                select(Capture.method)
                .join(Extraction, Extraction.capture_id == Capture.id)
                .where(Extraction.url_task_id == task)
            )
        ).scalars()
        assert sorted(captures) == ["api", "api"]


async def test_a_listing_the_recipe_does_not_serve_runs_its_browser_actions(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    web.up = False
    url = f"{own_origin}/kettles"

    result = await scrape(engine, fetching, _request(url, schema, records=5), data=engine_data)

    assert web.listed == [url]
    assert len(web.requested) == 1
    assert result.fetch is not None
    assert result.fetch.method == "browser"
    assert result.records is not None
    assert [r.fields["title"].value for r in result.records] == NAMES[:2]


async def test_a_listing_with_the_callers_page_steps_is_not_served_by_the_recipe(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles"
    steps = {"actions": [{"type": "click", "text": "Accept"}]}

    result = await scrape(engine, fetching, _request(url, schema, records=5, **steps), data=engine_data)

    # The steps change the page and need the browser: the recipe's HTTP pages would skip them.
    assert (web.listed, web.requested) == ([url], [])
    assert result.fetch is not None
    assert result.fetch.method == "browser"


# The worker's tasks.


async def _run(
    engine: AsyncEngine, handlers: dict[JobKind, TaskHandler], job_id: JobId, *, first_attempt: bool = False
) -> None:
    """Run a worker loop until the job has ended, or with `first_attempt` until its task's first attempt has ended (a
    transient failure is retried only after a backoff)."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, handlers, stop, ending=close_run))
    async with asyncio.timeout(60):
        while not await _ended(engine, job_id, first_attempt=first_attempt):
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def _ended(engine: AsyncEngine, job_id: JobId, *, first_attempt: bool) -> bool:
    async with engine.connect() as conn:
        if first_attempt:
            query = select(UrlTask.last_error.is_not(None)).where(UrlTask.job_id == job_id)
            return bool((await conn.execute(query)).scalar_one())
        status = (await conn.execute(select(Job.status).where(Job.id == job_id))).scalar_one()
    return status in ("completed", "failed", "cancelled")


async def _titles(engine: AsyncEngine, job_id: JobId) -> tuple[list[str], list[str]]:
    """The titles of the job's records, and the methods of the captures its extractions read, in order."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                select(Record.data, Capture.method)
                .join(Extraction, Record.extraction_id == Extraction.id)
                .join(Capture, Extraction.capture_id == Capture.id)
                .join(UrlTask, Extraction.url_task_id == UrlTask.id)
                .where(UrlTask.job_id == job_id)
                .order_by(Record.id)
            )
        ).all()
    return [row.data["title"] for row in rows], [row.method for row in rows]


async def test_a_batch_task_of_a_listing_recipe_stores_every_page_of_the_listing(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    body = {
        "urls": [f"{own_origin}/kettles"],
        "formats": ["records"],
        "schema": {"id": str(schema.id)},
        "page_kind": "listing",
    }
    submitted = await submit_batch(
        engine, fetching.connector, BatchScrapeRequest.model_validate(body), data=engine_data
    )

    await _run(engine, {"batch_scrape": scrape_handler(fetching, engine_data, None, llm=NO_LLM)}, submitted.job_id)

    # Three pages of three, three and two rows: every page is requested and stored, with no browser.
    assert [parse_qs(urlsplit(r.url).query).get("after") for r in web.requested] == [None, ["3"], ["6"]]
    titles, methods = await _titles(engine, submitted.job_id)
    assert (sorted(titles), set(methods), web.listed) == (NAMES, {"api"}, [])


async def test_a_crawl_task_of_a_listing_recipe_serves_its_pages_up_to_the_crawl_limit(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles"
    rules = [{"pattern": url, "page_kind": "listing"}]
    body = {
        "url": url,
        "formats": ["records"],
        "schema": {"id": str(schema.id)},
        "page_kind_rules": rules,
        "max_depth": 0,
        "limit": 2,
    }
    submitted = await submit_crawl(engine, fetching.connector, CrawlRequest.model_validate(body), data=engine_data)

    await _run(engine, {"crawl": crawl_handler(fetching, engine_data, None, llm=NO_LLM)}, submitted.job_id)

    assert len(web.requested) == 2
    titles, _ = await _titles(engine, submitted.job_id)
    assert sorted(titles) == NAMES[:6]


async def _batch(
    engine: AsyncEngine, fetching: Fetching, url: str, schema: SchemaDef, data: EngineData, *, first_attempt: bool
) -> JobId:
    body = {"urls": [url], "formats": ["records"], "schema": {"id": str(schema.id)}, "page_kind": "listing"}
    submitted = await submit_batch(engine, fetching.connector, BatchScrapeRequest.model_validate(body), data=data)
    handlers: dict[JobKind, TaskHandler] = {"batch_scrape": scrape_handler(fetching, data, None, llm=NO_LLM)}
    await _run(engine, handlers, submitted.job_id, first_attempt=first_attempt)
    return submitted.job_id


async def test_a_batch_task_whose_recipe_fails_its_first_page_requests_it_once_then_fetches_the_page(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    web.up = False
    url = f"{own_origin}/kettles"

    await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)

    # The page over HTTP, and its one render: its document shows fewer item blocks than a listing does.
    assert (len(web.requested), web.pages) == (1, [url, url])


async def test_a_batch_task_whose_recipe_is_asked_to_slow_down_sends_nothing_more(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    web.up, web.down = False, 503  # RFC 9110 §15.6.4
    url = f"{own_origin}/kettles"

    await _batch(engine, fetching, url, schema, engine_data, first_attempt=True)

    assert (len(web.requested), web.pages) == (1, [])


async def test_a_listing_the_recipe_does_not_serve_is_not_rendered_without_a_turn_at_the_sites_rate(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    site: SiteId,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    # The recipe's request takes the caller's turn; the next is two minutes off, past what a caller waits in place.
    async with engine.begin() as conn:
        await conn.execute(update(Site).where(Site.id == site).values(crawl_delay_ms=120_000))
    web.up = False
    url = f"{own_origin}/kettles"

    result = await scrape(engine, fetching, _request(url, schema, records=5), data=engine_data)

    assert (web.listed, len(web.requested)) == ([], 1)
    assert result.fetch is not None
    assert result.fetch.method == "api"


async def test_a_batch_task_whose_recipe_answers_no_rows_counts_that_request_then_fetches_the_page(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    web.empty = True
    url = f"{own_origin}/kettles"

    job_id = await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)

    async with engine.connect() as conn:
        query = select(UsageEvent.metadata_["method"].astext).where(UsageEvent.job_id == job_id)
        counted: list[str] = sorted((await conn.execute(query)).scalars())
    assert len(web.requested) == 1
    assert counted.count("api") == 1


async def test_a_batch_task_whose_further_recipe_page_the_guard_refuses_fails(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    web.refused = "3"  # INV-16: a refused request fails the task, never truncates its listing silently
    url = f"{own_origin}/kettles"

    job_id = await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)

    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.status, UrlTask.last_error).where(UrlTask.job_id == job_id))).one()
    titles, _ = await _titles(engine, job_id)
    assert task.status == "failed"
    assert (task.last_error or "").startswith(SSRF_REJECTED)
    assert titles == []


async def test_a_batch_task_whose_further_recipe_page_fails_its_extraction_is_partial(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_later_pages(bundle: CaptureBundle, *args: Any, **kwargs: Any) -> ExtractionResult:
        result = await extract_page(bundle, *args, **kwargs)
        later = NAMES[PAGE_SIZE].encode() in bundle.body  # the second page's first row
        return result.model_copy(update={"outcome": "error", "entity": None, "rows": ()}) if later else result

    monkeypatch.setattr("crawlerai.services.scrape_steps.extract_page", failing_later_pages)
    url = f"{own_origin}/kettles"

    job_id = await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)

    async with engine.connect() as conn:
        outcome = (await conn.execute(select(UrlTask.outcome).where(UrlTask.job_id == job_id))).scalar_one()
    assert outcome == "partial"


async def test_a_recurring_listing_whose_later_recipe_page_changed_is_extracted_again(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema: SchemaDef,
    recipe_config: None,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles"
    await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)
    web.names[PAGE_SIZE] = "Kettle Z"  # the first page reads the same; the second does not

    job_id = await _batch(engine, fetching, url, schema, engine_data, first_attempt=False)

    async with engine.connect() as conn:
        outcome = (await conn.execute(select(UrlTask.outcome).where(UrlTask.job_id == job_id))).scalar_one()
    titles, _ = await _titles(engine, job_id)
    assert outcome == "extracted"
    assert "Kettle Z" in titles
