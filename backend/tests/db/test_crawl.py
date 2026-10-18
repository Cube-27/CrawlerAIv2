"""`crawl` jobs (SPEC-10 §4.5, ARCHITECTURE §13.2): submitted through the crawl service, run by a worker loop through
the real queue, and read back through the jobs service. The frontier's enqueueing is also tested on its own, against the
`url_task` table.

The web is a stub that answers synthetic pages, sitemaps and robots.txt on RFC 2606 hosts, and the resolver a stub: no
network, no Chromium. The limiter's clock jumps ahead on every reading, so the site's rate never makes a test wait.
"""

import asyncio
import itertools
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire import politeness
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.core.settings import Settings
from crawlerai.crawl.frontier import Frontier
from crawlerai.crawl.rules import PageKindRule, Scope
from crawlerai.db import queue
from crawlerai.db.models import Extraction, Job, JobEvent, JobId, JobKind, Project, Site, UrlState, UrlTask
from crawlerai.db.queue import MAX_ATTEMPTS
from crawlerai.db.usage import budget_remaining
from crawlerai.llm.client import NO_LLM, LLMClient, MeteredClient, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.recurring.listing_diff import SITEMAPS_TIMED_OUT, close_run
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.crawl import CrawlRequest, submit_crawl
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.jobs import PageOutputPage, ResultsQuery
from crawlerai.services.records import RecordPage
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers import crawl as crawl_handler_module
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.loop import TaskHandler, run_worker
from tests.conftest import ParserCounter
from tests.db.conftest import PRIVATE_HOST, listing_page, listing_schema, resolve

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}

Page = tuple[int, bytes, BlockClass]


def page(*hrefs: str, product: str | None = None, offers: bool = True) -> Page:
    head = ""
    if product is not None:
        node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": product}
        if offers:
            node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
        head = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    anchors = "".join(f'<a href="{href}">link</a>' for href in hrefs)
    body = f"<main><h1>{product or 'Shop'}</h1><p>A shop that sells kettles.</p>{anchors}</main>"
    return 200, f"<!doctype html><html lang='en'><head>{head}</head><body>{body}</body></html>".encode(), "ok"


def urlset(*locs: str) -> Page:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return 200, f'<?xml version="1.0"?><urlset xmlns="{NS}">{entries}</urlset>'.encode(), "ok"


def robots(*lines: str) -> Page:
    return 200, "\n".join(["User-agent: *", "Allow: /", *lines]).encode(), "ok"


@dataclass
class Web:
    """Answers each URL from `pages` over HTTP; anything else is a 404. A URL of `redirects` answers as its target,
    reached through the site's redirect. A URL in `refused` redirects to a private address: the rung reports the
    guard's refusal as the attempt's error. A URL in `held` answers once its event is set. The browser renders a page
    as it is served (`rendered` lists the URLs): a page without offer data is rendered once (owner #49)."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, Page] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)
    refused: set[str] = field(default_factory=set)
    held: dict[str, asyncio.Event] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        if url in self.refused:
            return self.fetch_result(url, 0, b"", block_class="error", error="ssrf_rejected: private_address")
        self.fetched.append(url)
        if url in self.held:
            await self.held[url].wait()
        final_url = self.redirects.get(url, url)
        status, body, block_class = self.pages.get(final_url, (404, b"gone", "not_found"))
        return self.fetch_result(url, status, body, block_class=block_class, final_url=final_url)

    async def browser(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.rendered.append(url)
        status, body, block_class = self.pages.get(url, (404, b"gone", "not_found"))
        return self.fetch_result(url, status, body, block_class=block_class, method="browser")


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": robots()})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    clock = itertools.count(step=3600)
    return Fetching(
        Rungs(http=web.http, browser=web.browser),
        SafeConnector(resolve),
        FsStore(tmp_path / "objects"),
        HostLimiter(clock=lambda: float(next(clock))),
    )


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = {"name": schema_name, "page_kind": "detail", "fields": {"title": TITLE, "price": PRICE}}
    async with engine.begin() as conn:
        return await registry.create(conn, SchemaDocument.model_validate(document), "user")


def crawl(url: str, *formats: str, **members: Any) -> CrawlRequest:
    return CrawlRequest.model_validate({"url": url, "formats": list(formats or ("markdown",)), **members})


def records_crawl(url: str, schema: SchemaDef, pattern: str, **members: Any) -> CrawlRequest:
    rules = [{"pattern": pattern, "page_kind": "detail"}]
    return crawl(url, "records", schema={"id": str(schema.id)}, page_kind_rules=rules, **members)


async def run(
    engine: AsyncEngine, fetching: Fetching, data: EngineData | None, job_id: JobId, llm: LLMClient = NO_LLM
) -> None:
    """Run a worker loop until the job has ended; role C runs on `llm`."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    handlers: dict[JobKind, TaskHandler] = {"crawl": crawl_handler(fetching, data, None, llm=llm)}
    loop = asyncio.create_task(run_worker(settings, handlers, stop, ending=close_run))
    async with asyncio.timeout(60):
        while (await summary(engine, job_id)).status not in ("completed", "failed", "cancelled"):
            await asyncio.sleep(0.1)
    stop.set()
    await loop


async def summary(engine: AsyncEngine, job_id: JobId) -> jobs.JobSummary:
    async with engine.connect() as conn:
        return await jobs.get_job(conn, job_id)


async def tasks(engine: AsyncEngine, job_id: JobId) -> dict[str, Any]:
    """The job's tasks by URL."""
    async with engine.connect() as conn:
        rows = await conn.execute(select(UrlTask).where(UrlTask.job_id == job_id))
    return {row.url: row for row in rows}


# Submitting.


async def test_a_submitted_crawl_is_a_queued_job_with_the_start_urls_task(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    rules = [{"pattern": f"{own_origin}/*", "page_kind": "listing"}]
    request = crawl(f"{own_origin}/#top", page_kind_rules=rules, include=[f"{own_origin}/p/*"])

    submitted = await submit_crawl(engine, fetching.connector, request, data=None)

    found = await tasks(engine, submitted.job_id)
    job = await summary(engine, submitted.job_id)
    # The start URL is fetched although `include` does not match it, in canonical form.
    assert list(found) == [f"{own_origin}/"]
    root = found[f"{own_origin}/"]
    assert (root.depth, root.parent_task_id, root.page_kind) == (0, None, "listing")
    assert (job.kind, job.status, job.counts.queued) == ("crawl", "queued", 1)


async def test_a_crawls_own_budget_bounds_its_llm_calls_before_the_projects_cap(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    async with engine.begin() as conn:
        await conn.execute(update(Project).values(llm_call_cap=7))
    try:
        capped = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/"), data=None)
        budgeted = await submit_crawl(
            engine, fetching.connector, crawl(f"{own_origin}/", budget={"llm_calls": 2}), data=None
        )
        async with engine.connect() as conn:
            remaining = [await budget_remaining(conn, job.job_id, "llm_calls") for job in (capped, budgeted)]
    finally:
        async with engine.begin() as conn:
            await conn.execute(update(Project).values(llm_call_cap=None))

    assert remaining == [7, 2]


@pytest.mark.parametrize("member", ["url", "webhook_url"])
async def test_a_refused_target_queues_nothing(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, member: str
) -> None:
    private = f"https://{PRIVATE_HOST}/"
    request = crawl(private) if member == "url" else crawl(f"{own_origin}/", webhook_url=private)

    with pytest.raises(TargetsRejected) as rejected:
        await submit_crawl(engine, fetching.connector, request, data=None)

    assert rejected.value.member == member
    async with engine.connect() as conn:
        assert (await conn.execute(select(Job.id).where(Job.kind == "crawl"))).all() == []


async def test_only_urls_a_rule_matches_are_extracted_and_outcomes_match_the_task_table(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    web.pages |= {
        f"{own_origin}/": page("/p/blue", "/p/plain", "/c/kettles", "https://other.example.test/p/1"),
        f"{own_origin}/p/blue": page("/p/plain", product="Blue kettle"),
        f"{own_origin}/p/plain": page(product="Plain kettle", offers=False),
        # A category page carries a complete product too: no rule matches it, so it is never extracted.
        f"{own_origin}/c/kettles": page("/p/blue", product="Category kettle"),
    }
    request = records_crawl(f"{own_origin}/", kettle_schema, f"{own_origin}/p/*")
    submitted = await submit_crawl(engine, fetching.connector, request, data=engine_data)

    await run(engine, fetching, engine_data, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    job = await summary(engine, submitted.job_id)
    assert {url: task.outcome for url, task in found.items()} == {
        f"{own_origin}/": "links_only",
        f"{own_origin}/c/kettles": "links_only",
        f"{own_origin}/p/blue": "extracted",
        # Crawl-discovered: an incomplete page has no record (ARCHITECTURE §10).
        f"{own_origin}/p/plain": "no_match",
    }
    of_job = UrlTask.job_id == submitted.job_id
    async with engine.connect() as conn:
        extracted = (await conn.execute(select(Extraction.url_task_id).join(UrlTask).where(of_job))).scalars().all()
        outcomes = select(UrlTask.outcome, func.count()).where(of_job).group_by(UrlTask.outcome)
        counted: dict[str | None, int] = {outcome: n for outcome, n in await conn.execute(outcomes)}
    assert sorted(extracted) == sorted([found[f"{own_origin}/p/blue"].id, found[f"{own_origin}/p/plain"].id])
    assert job.outcomes.model_dump() == {outcome: counted.get(outcome, 0) for outcome in job.outcomes.model_dump()}
    assert (job.status, job.counts.done) == ("completed", 4)
    results = await _results(engine, fetching, submitted.job_id)
    assert isinstance(results, RecordPage)
    assert [record.fields["title"].value for record in results.items] == ["Blue kettle"]


async def test_a_listing_rule_keeps_each_rows_record_and_follows_the_next_page(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, schema_name: str, engine_data: EngineData
) -> None:
    start, second = f"{own_origin}/c/kettles", f"{own_origin}/c/kettles?page=2"
    web.pages |= {
        start: (200, listing_page(own_origin, ["Blue kettle", "Red kettle"], next_page=second), "ok"),
        second: (200, listing_page(own_origin, ["Green kettle", "Grey kettle"], first=3), "ok"),
    }
    schema = await listing_schema(engine, schema_name)
    rules = [{"pattern": f"{own_origin}/c/*", "page_kind": "listing"}]
    request = crawl(
        start, "records", schema={"id": str(schema.id)}, page_kind_rules=rules, include=[f"{own_origin}/c/*"]
    )
    submitted = await submit_crawl(engine, fetching.connector, request, data=engine_data)

    await run(engine, fetching, engine_data, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    results = await _results(engine, fetching, submitted.job_id)
    assert {url: task.outcome for url, task in found.items()} == {start: "extracted", second: "extracted"}
    assert isinstance(results, RecordPage)
    titles = sorted(str(record.fields["title"].value) for record in results.items)
    assert titles == ["Blue kettle", "Green kettle", "Grey kettle", "Red kettle"]


async def test_a_page_is_parsed_once_for_its_links_and_its_record(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    parses: Mapping[str, ParserCounter],
) -> None:
    web.pages[f"{own_origin}/p/blue"] = page("/p/red", product="Blue kettle")
    request = records_crawl(f"{own_origin}/p/blue", kettle_schema, f"{own_origin}/p/*", max_depth=0)
    submitted = await submit_crawl(engine, fetching.connector, request, data=engine_data)

    await run(engine, fetching, engine_data, submitted.job_id)

    # INV-26: one parse per parser of the one page fetched (the start page; `max_depth` 0 fetches none of its links).
    assert [task.outcome for task in (await tasks(engine, submitted.job_id)).values()] == ["extracted"]
    assert (parses["selectolax"].calls, parses["lxml"].calls <= 1) == (1, True)


async def test_role_c_completes_a_discovered_page_whose_price_is_only_in_its_text(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # SPEC-10 §4.6, ARCHITECTURE §8.4: a crawl's page is extracted cold with role C for its missing required fields;
    # without it, the page would end `no_match`. Role C's client commits usage while the task's transaction is open
    # (D-0346), so the task writes the job's usage only after the extraction.
    url = f"{own_origin}/p/blue"
    status, body, block_class = page(product="Blue kettle", offers=False)
    body = body.replace(b"</main>", b"<aside>19.90 EUR</aside></main>")
    web.pages[url] = (status, body, block_class)
    text = ParsedPage.of(fetch_result(url, 200, body).bundle).cleaned_text.text
    start = text.index("19.90 EUR")
    price = {"shown": True, "ref": "", "value": "19.90 EUR", "start": start, "end": start + len("19.90 EUR")}
    reply = ProviderReply(model="fake-fast", text=json.dumps({"fields": {"price": price}}), tokens_in=7, tokens_out=3)
    request = records_crawl(url, kettle_schema, f"{own_origin}/p/*", max_depth=0)
    submitted = await submit_crawl(engine, fetching.connector, request, data=engine_data)

    await run(engine, fetching, engine_data, submitted.job_id, MeteredClient([FakeProvider([reply])], engine))

    assert [task.outcome for task in (await tasks(engine, submitted.job_id)).values()] == ["extracted"]
    # The page states its price in text only: no structured offer data, so it is rendered once, to no better effect.
    assert web.rendered == [url]
    async with engine.connect() as conn:
        usage: dict[str, int] = (await conn.execute(select(Job.usage).where(Job.id == submitted.job_id))).scalar_one()
    assert usage["llm_calls"] == 1


async def test_with_rules_a_page_no_rule_matches_has_no_formats(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {f"{own_origin}/": page("/p/blue"), f"{own_origin}/p/blue": page(product="Blue kettle")}
    rules = [{"pattern": f"{own_origin}/p/*", "page_kind": "detail"}]
    submitted = await submit_crawl(
        engine, fetching.connector, crawl(f"{own_origin}/", page_kind_rules=rules), data=None
    )

    await run(engine, fetching, None, submitted.job_id)

    results = await _results(engine, fetching, submitted.job_id)
    assert isinstance(results, PageOutputPage)
    by_url = {item.url: item for item in results.items}
    assert (by_url[f"{own_origin}/"].outcome, by_url[f"{own_origin}/"].markdown) == ("links_only", None)
    blue = by_url[f"{own_origin}/p/blue"]
    assert blue.outcome == "extracted"
    assert blue.markdown is not None
    assert "Blue kettle" in blue.markdown


async def test_without_rules_every_reached_page_has_its_formats(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {f"{own_origin}/": page("/p/blue", "/gone"), f"{own_origin}/p/blue": page(product="Blue kettle")}
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/", "links"), data=None)

    await run(engine, fetching, None, submitted.job_id)

    results = await _results(engine, fetching, submitted.job_id)
    assert isinstance(results, PageOutputPage)
    outputs = {item.url: (item.outcome, item.links) for item in results.items}
    assert outputs == {
        f"{own_origin}/": ("extracted", [f"{own_origin}/p/blue", f"{own_origin}/gone"]),
        f"{own_origin}/p/blue": ("extracted", []),
        f"{own_origin}/gone": ("not_found", None),
    }


async def test_depth_is_the_parents_plus_one_and_stops_at_max_depth(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {f"{own_origin}/{name}": page(f"/{child}") for name, child in [("", "a"), ("a", "b"), ("b", "c")]}
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/", max_depth=2), data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    root, a, b = (found[f"{own_origin}/{name}"] for name in ("", "a", "b"))
    assert len(found) == 3
    assert [(task.depth, task.parent_task_id) for task in (root, a, b)] == [(0, None), (1, root.id), (2, a.id)]
    assert f"{own_origin}/c" not in web.fetched


async def test_sitemap_urls_in_scope_are_seeds(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/products.xml"),
        f"{own_origin}/products.xml": urlset(f"{own_origin}/p/1", f"{own_origin}/private/2", f"{own_origin}/p/3"),
        f"{own_origin}/": page("/p/1"),
    }
    request = crawl(f"{own_origin}/", exclude=["*/private/*"], max_depth=0)
    submitted = await submit_crawl(engine, fetching.connector, request, data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    # Seeds are at depth 0, so `max_depth` 0 fetches them, and none of the links they lead to.
    assert sorted(found) == [f"{own_origin}/", f"{own_origin}/p/1", f"{own_origin}/p/3"]
    assert {(task.depth, task.parent_task_id) for task in found.values()} == {(0, None)}


async def test_the_crawl_follows_the_start_page_s_redirect_to_another_host(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, www_origin: str
) -> None:
    # The start URL's host redirects to its `www.` subdomain (RFC 9110 §15.4: the redirect names where the resource
    # is): the site's pages, links and sitemaps are on that host, read under its own robots.txt.
    web.redirects |= {f"{own_origin}/": f"{www_origin}/", f"{own_origin}/robots.txt": f"{www_origin}/robots.txt"}
    web.pages |= {
        f"{www_origin}/robots.txt": robots(f"Sitemap: {www_origin}/products.xml", "Disallow: /private/"),
        f"{www_origin}/products.xml": urlset(f"{www_origin}/p/1", f"{own_origin}/p/9"),
        f"{www_origin}/": page("/c/kettles", f"{own_origin}/c/old", f"{www_origin}/"),
        f"{www_origin}/c/kettles": page("/p/2", "/private/3", "/"),
        f"{www_origin}/p/1": page(product="Blue kettle"),
        f"{www_origin}/p/2": page(product="Red kettle"),
    }
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/"), data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    assert {url: task.outcome for url, task in found.items()} == {
        f"{own_origin}/": "extracted",
        f"{www_origin}/p/1": "extracted",
        f"{www_origin}/c/kettles": "extracted",
        f"{www_origin}/p/2": "extracted",
        f"{www_origin}/private/3": "blocked",
    }
    # The page the start URL redirected to is the start task's, though it and its descendants link to it: no task of
    # its own, never requested at its own URL. Where it is, is stored on the job for the tasks that follow (D-1285).
    assert f"{www_origin}/" not in web.fetched
    async with engine.connect() as conn:
        stored = (await conn.execute(select(Job.start_location).where(Job.id == submitted.job_id))).scalar_one()
    assert stored == f"{www_origin}/"


async def test_a_page_another_task_was_redirected_to_is_not_fetched_again_as_its_own_task(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    # D-1382: /p/old redirects to /p/new; the category page found later links /p/new, already that task's page.
    web.redirects[f"{own_origin}/p/old"] = f"{own_origin}/p/new"
    web.pages |= {
        f"{own_origin}/": page("/p/old", "/c/kettles"),
        f"{own_origin}/c/kettles": page("/p/new", "/p/2"),
        f"{own_origin}/p/new": page(product="Blue kettle"),
        f"{own_origin}/p/2": page(product="Red kettle"),
    }
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/"), data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    assert set(found) == {f"{own_origin}/", f"{own_origin}/p/old", f"{own_origin}/c/kettles", f"{own_origin}/p/2"}
    assert found[f"{own_origin}/p/old"].final_url == f"{own_origin}/p/new"
    assert f"{own_origin}/p/new" not in web.fetched


async def test_a_crawl_that_is_not_redirected_stores_its_start_url_as_where_it_is(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages[f"{own_origin}/"] = page("/p/1")
    web.pages[f"{own_origin}/p/1"] = page(product="Blue kettle")
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/"), data=None)
    before = await summary(engine, submitted.job_id)

    await run(engine, fetching, None, submitted.job_id)

    async with engine.connect() as conn:
        stored = (await conn.execute(select(Job.start_location).where(Job.id == submitted.job_id))).scalar_one()
    assert (before.status, stored) == ("queued", f"{own_origin}/")
    assert set(await tasks(engine, submitted.job_id)) == {f"{own_origin}/", f"{own_origin}/p/1"}


async def test_a_retried_start_page_reads_the_sitemaps_once_on_its_last_attempt(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sitemap = f"{own_origin}/products.xml"
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {sitemap}"),
        sitemap: urlset(f"{own_origin}/p/1"),
        f"{own_origin}/": (503, b"busy", "error"),  # a transient failure on every attempt, `blocked` at the last
        f"{own_origin}/p/1": page(),
    }
    monkeypatch.setattr(politeness, "backoff_delay", lambda tries: timedelta(0))
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/", max_depth=0), data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    start = found[f"{own_origin}/"]
    assert (start.outcome, start.attempts) == ("blocked", MAX_ATTEMPTS)
    assert web.fetched.count(f"{own_origin}/") == MAX_ATTEMPTS
    assert web.fetched.count(sitemap) == 1
    assert sorted(found) == [f"{own_origin}/", f"{own_origin}/p/1"]


async def test_reading_sitemaps_stops_at_the_time_cap_and_is_logged(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/a.xml", f"Sitemap: {own_origin}/b.xml"),
        f"{own_origin}/a.xml": urlset(f"{own_origin}/p/1"),
        f"{own_origin}/b.xml": urlset(f"{own_origin}/p/2"),
        f"{own_origin}/": page(),
    }
    web.held[f"{own_origin}/b.xml"] = asyncio.Event()  # never answers
    monkeypatch.setattr(crawl_handler_module, "SITEMAP_TIMEOUT_S", 0.5)
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/", max_depth=0), data=None)

    with caplog.at_level(logging.INFO, logger="crawlerai"):
        await run(engine, fetching, None, submitted.job_id)

    # The seeds read before the cap are kept.
    assert sorted(await tasks(engine, submitted.job_id)) == [f"{own_origin}/", f"{own_origin}/p/1"]
    lines = [r.getMessage().split(": ", 1)[1] for r in caplog.records if r.name.endswith(".crawl")]
    assert lines == [f"sitemaps of job {submitted.job_id}: 1 seeds; stopped at the 0.5 s time cap"]
    # The run saw part of its listing only, which the listing diff reads (SPEC-11 §4.5).
    async with engine.connect() as conn:
        query = select(JobEvent.payload).where(JobEvent.job_id == submitted.job_id, JobEvent.kind == SITEMAPS_TIMED_OUT)
        payloads: list[dict[str, Any]] = list((await conn.execute(query)).scalars())
    assert payloads == [{"url": f"{own_origin}/", "seeds": 1}]


async def test_a_target_the_guard_refuses_is_never_fetched(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/robots.txt": robots(f"Sitemap: {own_origin}/moved.xml", f"Sitemap: {own_origin}/later.xml"),
        f"{own_origin}/later.xml": urlset(f"{own_origin}/p/1"),
        f"{own_origin}/": page("/moved", "/p/2"),
    }
    web.refused |= {f"{own_origin}/moved", f"{own_origin}/moved.xml"}
    submitted = await submit_crawl(engine, fetching.connector, crawl(f"{own_origin}/"), data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    moved = found[f"{own_origin}/moved"]
    # The page's task fails at once (INV-16); a refused sitemap ends the reading of sitemaps, and the crawl goes on.
    assert (moved.outcome, moved.attempts, moved.last_error) == ("failed", 1, "ssrf_rejected: private_address")
    assert sorted(found) == [f"{own_origin}/", f"{own_origin}/moved", f"{own_origin}/p/2"]
    assert (await summary(engine, submitted.job_id)).status == "completed"


async def _cancel_while_reading_sitemaps(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    request: CrawlRequest,
    data: EngineData | None,
    *rules: str,
) -> None:
    """Cancel the crawl while its start page's task reads the site's sitemap, which can take up to the sitemap time
    cap: the cancel answers at once, and the job ends `cancelled` once that task finishes. `rules` go into
    robots.txt."""
    origin = request.start.removesuffix("/")
    sitemap = f"{origin}/products.xml"
    web.pages |= {f"{origin}/robots.txt": robots(f"Sitemap: {sitemap}", *rules), sitemap: urlset(f"{origin}/p/1")}
    web.held[sitemap] = release = asyncio.Event()
    submitted = await submit_crawl(engine, fetching.connector, request, data=data)
    worker = asyncio.create_task(run(engine, fetching, data, submitted.job_id))
    async with asyncio.timeout(30):
        while sitemap not in web.fetched:
            await asyncio.sleep(0.05)
    try:
        async with asyncio.timeout(5), engine.begin() as conn:
            requested = await jobs.cancel_job(conn, submitted.job_id)
            requested_at: datetime = (await conn.execute(select(func.clock_timestamp()))).scalar_one()
    finally:
        release.set()
    await worker
    assert (requested.status, requested.counts.claimed) == ("running", 1)
    ended = await summary(engine, submitted.job_id)
    assert ended.status == "cancelled"
    # It ended when the task reading the sitemap did, after the cancel was requested (F34).
    assert ended.finished_at is not None
    assert ended.finished_at > requested_at
    assert sorted(await tasks(engine, submitted.job_id)) == [request.start]


async def test_a_cancel_does_not_wait_for_the_sitemaps_being_read(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages[f"{own_origin}/"] = page("/p/2")

    await _cancel_while_reading_sitemaps(engine, fetching, web, crawl(f"{own_origin}/"), None)


async def test_a_cancel_does_not_wait_for_the_sitemaps_after_a_record_was_stored(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # The start page is extracted first: the rows its record adds refer to the job's row.
    web.pages[f"{own_origin}/"] = page("/p/2", product="Blue kettle")
    request = records_crawl(f"{own_origin}/", kettle_schema, f"{own_origin}/*")

    await _cancel_while_reading_sitemaps(engine, fetching, web, request, engine_data)


async def test_a_cancel_does_not_wait_for_the_sitemaps_after_robots_refused_the_start_page(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    # The start page ends `blocked` without being fetched, and robots.txt's fetch counts as the job's usage.
    request = crawl(f"{own_origin}/")

    await _cancel_while_reading_sitemaps(engine, fetching, web, request, None, "Disallow: /$")


async def _results(engine: AsyncEngine, fetching: Fetching, job_id: JobId) -> Any:
    async with engine.connect() as conn:
        return await jobs.job_results(conn, job_id, ResultsQuery(), store=fetching.store)


async def test_a_product_absent_from_two_consecutive_crawls_is_gone(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    web.pages |= {
        f"{own_origin}/p/blue": page(product="Blue kettle"),
        f"{own_origin}/p/red": page(product="Red kettle"),
    }
    request = records_crawl(f"{own_origin}/", kettle_schema, f"{own_origin}/p/*")
    runs = []
    # SPEC-11 §7: the red kettle leaves the listing after the first run.
    for listed in (("/p/blue", "/p/red"), ("/p/blue",), ("/p/blue",)):
        web.pages[f"{own_origin}/"] = page(*listed)
        submitted = await submit_crawl(engine, fetching.connector, request, data=engine_data)
        await run(engine, fetching, engine_data, submitted.job_id)
        runs.append(submitted.job_id)

    host = own_origin.removeprefix("https://")
    query = (
        select(UrlState.canonical_url, UrlState.missing_runs, UrlState.gone_at.is_not(None), UrlState.last_seen_job_id)
        .join(Site)
        .where(Site.host == host)
    )
    async with engine.connect() as conn:
        state = {url: tuple(rest) for url, *rest in await conn.execute(query)}
        events = select(JobEvent.kind, JobEvent.payload).where(JobEvent.job_id == runs[2]).order_by(JobEvent.id)
        last = [(kind, payload) for kind, payload in await conn.execute(events) if kind in ("url_gone", "completed")]
    assert state == {
        f"{own_origin}/p/blue": (0, False, runs[2]),
        f"{own_origin}/p/red": (2, True, runs[0]),
    }
    # The gone URL is announced before the job's end event, which closes the event stream.
    assert last == [("url_gone", {"url": f"{own_origin}/p/red"}), ("completed", {})]


# The frontier on the url_task table.


@pytest.fixture
async def job(conn: AsyncConnection) -> JobId:
    project = select(Project.id).where(Project.name == "default").scalar_subquery()
    values = {"project_id": project, "kind": "crawl", "request": {}, "engine_version": "test"}
    job_id: JobId = (await conn.execute(insert(Job).values(values).returning(Job.id))).scalar_one()
    root = "https://shop.example.test/"
    await conn.execute(insert(UrlTask).values(job_id=job_id, url=root, canonical_url=root))
    return job_id


def frontier(*, limit: int = 10, max_depth: int = 3, rules: tuple[PageKindRule, ...] = ()) -> Frontier:
    return Frontier(Scope("shop.example.test"), rules, max_depth, limit)


async def _urls(conn: AsyncConnection, job_id: JobId) -> list[tuple[str, str | None, int]]:
    rows = await conn.execute(
        select(UrlTask.url, UrlTask.page_kind, UrlTask.depth).where(UrlTask.job_id == job_id).order_by(UrlTask.id)
    )
    return [(url, page_kind, depth) for url, page_kind, depth in rows]


async def test_enqueueing_takes_new_urls_in_scope_once_in_order(conn: AsyncConnection, job: JobId) -> None:
    rules = (PageKindRule(pattern="https://shop.example.test/p/*", page_kind="detail"),)
    urls = [
        "https://shop.example.test/p/2",
        "https://other.example.test/p/1",
        "https://shop.example.test/",
        "https://shop.example.test/c/1",
        "https://shop.example.test/p/2",
    ]

    added = await frontier(rules=rules).enqueue(conn, job, urls, depth=1, parent=None)

    assert added == 2
    assert await _urls(conn, job) == [
        ("https://shop.example.test/", None, 0),
        ("https://shop.example.test/p/2", "detail", 1),
        ("https://shop.example.test/c/1", None, 1),
    ]


async def test_a_url_a_task_was_fetched_at_after_a_redirect_is_never_a_task_of_its_own(
    conn: AsyncConnection, job: JobId
) -> None:
    # D-1382: the task of /old was redirected to /new; /new's page is that task's.
    moved = "https://shop.example.test/old"
    await conn.execute(
        insert(UrlTask).values(job_id=job, url=moved, canonical_url=moved, final_url="https://shop.example.test/new")
    )
    urls = ["https://shop.example.test/new", "https://shop.example.test/c/1"]

    added = await frontier().enqueue(conn, job, urls, depth=1, parent=None)

    assert added == 1
    assert [url for url, _, _ in await _urls(conn, job)] == ["https://shop.example.test/", moved, urls[1]]


async def test_the_limit_counts_every_task_of_the_job(conn: AsyncConnection, job: JobId) -> None:
    urls = [f"https://shop.example.test/p/{n}" for n in range(5)]

    first = await frontier(limit=3).enqueue(conn, job, urls[:1], depth=1, parent=None)
    second = await frontier(limit=3).enqueue(conn, job, urls, depth=1, parent=None)

    assert (first, second) == (1, 1)
    assert [url for url, _, _ in await _urls(conn, job)] == ["https://shop.example.test/", *urls[:2]]


async def test_nothing_is_taken_past_max_depth_or_after_a_cancel(conn: AsyncConnection, job: JobId) -> None:
    deep = await frontier(max_depth=1).enqueue(conn, job, ["https://shop.example.test/a"], depth=2, parent=None)
    await conn.execute(update(Job).where(Job.id == job).values(cancel_requested=True))
    cancelled = await frontier().enqueue(conn, job, ["https://shop.example.test/b"], depth=1, parent=None)

    assert (deep, cancelled) == (0, 0)
    assert len(await _urls(conn, job)) == 1


# Strategies (D-1440).


async def test_a_best_first_crawl_spends_its_limit_on_the_pages_that_match_the_query(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    web.pages |= {
        f"{own_origin}/": page("/blog/holiday", "/blog/news", "/guides/rate-limits", "/about"),
        # The best candidate is found only once the page before it is read: it must still come before the leased rest.
        f"{own_origin}/guides/rate-limits": page("/guides/rate-limits/retry"),
        f"{own_origin}/guides/rate-limits/retry": page(),
        f"{own_origin}/blog/holiday": page(),
        f"{own_origin}/blog/news": page(),
        f"{own_origin}/about": page(),
        f"{own_origin}/team": page(),
    }
    request = crawl(f"{own_origin}/", strategy="best_first", query="rate limits retry", limit=3)
    submitted = await submit_crawl(engine, fetching.connector, request, data=None)

    await run(engine, fetching, None, submitted.job_id)

    found = await tasks(engine, submitted.job_id)
    fetched = [
        url.removeprefix(own_origin)
        for url in web.fetched
        if url.startswith(f"{own_origin}/") and "robots" not in url and "sitemap" not in url
    ]
    assert fetched == ["/", "/guides/rate-limits", "/guides/rate-limits/retry"]
    done = {url for url, task in found.items() if task.status == "done"}
    assert done == {f"{own_origin}{path}" for path in fetched}
    assert all(task.status == "cancelled" for url, task in found.items() if url not in done)
    assert found[f"{own_origin}/guides/rate-limits"].score > found[f"{own_origin}/blog/news"].score


async def test_a_depth_first_crawl_leases_the_deepest_task_first(conn: AsyncConnection, job: JobId) -> None:
    shallow, deep = "https://shop.example.test/a", "https://shop.example.test/b"
    strategy = Frontier(Scope("shop.example.test"), (), 5, 10, "dfs")
    await strategy.enqueue(conn, job, [shallow], depth=1, parent=None)
    await strategy.enqueue(conn, job, [deep], depth=3, parent=None)

    claimed = await queue.claim_tasks(conn, "w", 2)

    assert [task.canonical_url for task in claimed] == [deep, shallow]


async def test_a_full_scored_frontier_replaces_its_weakest_task_by_a_better_candidate(
    conn: AsyncConnection, job: JobId
) -> None:
    frontier = Frontier(Scope("shop.example.test"), (), 5, 1, "dfs")  # capacity 5 tasks: the start task and 4 more
    base = "https://shop.example.test"
    await frontier.enqueue(conn, job, [f"{base}/shallow{n}" for n in range(4)], depth=1, parent=None)

    added = await frontier.enqueue(conn, job, [f"{base}/deep{n}" for n in range(3)], depth=4, parent=None)
    refused = await frontier.enqueue(conn, job, [f"{base}/shallower"], depth=0, parent=None)

    urls = (await conn.execute(select(UrlTask.url).where(UrlTask.job_id == job))).scalars().all()
    assert (added, refused) == (3, 0)
    assert sorted(urls) == sorted([f"{base}/", f"{base}/shallow0", *(f"{base}/deep{n}" for n in range(3))])


async def test_a_leased_task_defers_only_to_a_better_candidate_that_is_due(conn: AsyncConnection, job: JobId) -> None:
    frontier = Frontier(Scope("shop.example.test"), (), 5, 10, "best_first", wanted=("kettle",))
    base = "https://shop.example.test"
    await frontier.enqueue(conn, job, [f"{base}/low"], depth=1, parent=None, inherited=0.0)
    await frontier.enqueue(conn, job, [f"{base}/high"], depth=1, parent=None, inherited=1.0)
    later = UrlTask.canonical_url == f"{base}/high"
    await conn.execute(update(UrlTask).where(later).values(next_attempt_at=func.now() + timedelta(hours=1)))
    [leased] = [task for task in await queue.claim_tasks(conn, "w", 5) if task.canonical_url == f"{base}/low"]

    waiting = await frontier.outranked(conn, leased)
    await conn.execute(update(UrlTask).where(later).values(next_attempt_at=func.now()))
    due = await frontier.outranked(conn, leased)

    assert (waiting, due) == (False, True)
