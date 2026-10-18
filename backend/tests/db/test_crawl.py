"""`crawl` jobs (jobs spec): submitted through the crawl service, run by a worker loop through
the real queue, and read back through the jobs service. The frontier's enqueueing is also tested on its own, against the
`url_task` table."""

import asyncio
import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass
from crawlerai.core.settings import Settings
from crawlerai.crawl.frontier import Frontier
from crawlerai.crawl.rules import PageKindRule, Scope
from crawlerai.db.models import Extraction, Job, JobEvent, JobId, JobKind, Project, Site, UrlState, UrlTask
from crawlerai.llm.client import NO_LLM, LLMClient
from crawlerai.recurring.listing_diff import close_run
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef, SchemaDocument
from crawlerai.services import jobs
from crawlerai.services.crawl import CrawlRequest, submit_crawl
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.jobs import ResultsQuery
from crawlerai.services.records import RecordPage
from crawlerai.storage.fs import FsStore
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.loop import TaskHandler, run_worker
from tests.db.conftest import PRIVATE_HOST, resolve

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
        # Crawl-discovered: an incomplete page has no record.
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
    # jobs spec: the red kettle leaves the listing after the first run.
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


# Strategies (D-1440).
