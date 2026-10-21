"""`extract` jobs (jobs spec): submitted through the extract service, with globs expanded by a map of their host
and a prompt drafted from the first pages while the caller waits, then run by a worker loop through the real queue.

The web is a stub that answers synthetic pages and sitemaps on RFC 2606 hosts, the resolver a stub, and the LLM a
fake provider: no network. The limiter's clock jumps ahead on every reading, so a site's rate never makes a test wait.
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from pydantic import JsonValue, SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.settings import Settings
from crawlerai.db.models import Job, JobId, ProgressiveState, Record, UrlTask
from crawlerai.llm.client import (
    BudgetExhausted,
    LLMClient,
    MeteredClient,
    ProviderRefused,
    ProviderReply,
    Unconfigured,
)
from crawlerai.llm.roles.s_schema import draft_name
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef
from crawlerai.services import jobs
from crawlerai.services.extract import DraftTimedOut, ExtractRequest, NoSamplePage, NothingToExtract, submit_extract
from crawlerai.services.fetching import Fetching, TargetsRejected
from crawlerai.services.scrape import RecordsUnavailable
from crawlerai.services.scrape_request import SchemaUnusable
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import run_worker
from tests.db import support
from tests.db.support import PRICE, PRIVATE_HOST, TITLE
from tests.support.fake_llm import FakeProvider

pytestmark = pytest.mark.anyio

NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
NO_LLM = Unconfigured("no provider")


def _draft_reply(page_kind: str = "detail") -> ProviderReply:
    """A role S reply: a draft schema document without a name (llm spec)."""
    document: dict[str, JsonValue] = {"page_kind": page_kind, "fields": {"title": TITLE, "price": PRICE}}
    return ProviderReply(model="fake-strong", text=json.dumps(to_wire(document)), tokens_in=900, tokens_out=80)


def _page(name: str, *, offers: bool = True) -> bytes:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": name}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    return (
        f'<!doctype html><html lang="en"><head><title>{name}</title>'
        f'<script type="application/ld+json">{json.dumps(node)}</script></head>'
        f"<body><main><h1>{name}</h1><p>{name} boils water quickly and quietly.</p></main></body></html>"
    ).encode()


def _urlset(*locs: str) -> bytes:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0"?><urlset xmlns="{NS}">{entries}</urlset>'.encode()


@dataclass
class Web(support.Web):
    """`support.Web`, where `slow` URLs take a minute, and `held` ones answer once their event is set."""

    slow: set[str] = field(default_factory=set)
    held: dict[str, asyncio.Event] = field(default_factory=dict)

    async def fetch(self, method: CaptureMethod, url: str, policy: FetchPolicy) -> FetchResult:
        self.fetched.append((method, url))
        if url in self.slow:
            await asyncio.sleep(60)
        if url in self.held:
            await self.held[url].wait()
        return self.answer(url, method, policy)


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    web = Web(fetch_result)
    web.robots(own_origin, f"User-agent: *\nAllow: /\nSitemap: {own_origin}/sitemap.xml\n".encode())
    web.serve(f"{own_origin}/", b'<!doctype html><html><body><a href="/p/4">Four</a></body></html>')
    return web


def _request(urls: list[str], schema: dict[str, Any], **members: Any) -> ExtractRequest:
    return ExtractRequest.model_validate({"urls": urls, "schema": schema, "page_kind": "detail", **members})


def _by_id(schema: SchemaDef) -> dict[str, Any]:
    return {"id": str(schema.id)}


async def _tasks(engine: AsyncEngine, job_id: JobId) -> list[tuple[str, str, str | None]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            select(UrlTask.url, UrlTask.canonical_url, UrlTask.page_kind)
            .where(UrlTask.job_id == job_id)
            .order_by(UrlTask.id)
        )
        return [(row.url, row.canonical_url, row.page_kind) for row in rows]


async def _job(engine: AsyncEngine, job_id: JobId) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(select(Job).where(Job.id == job_id))).one()


async def _extract_jobs(engine: AsyncEngine) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(select(Job.id, Job.status).where(Job.kind == "extract"))).all())


async def _run(
    engine: AsyncEngine, fetching: Fetching, data: EngineData, job_id: JobId, llm: LLMClient = NO_LLM
) -> jobs.JobSummary:
    """Run a worker loop until the job has ended, and return its summary."""
    url = engine.url.render_as_string(hide_password=False)
    settings = Settings(database_url=SecretStr(url), object_store="fs:///unused")
    stop = asyncio.Event()
    loop = asyncio.create_task(run_worker(settings, {"extract": scrape_handler(fetching, data, None, llm=llm)}, stop))
    async with asyncio.timeout(60):
        while (await _job(engine, job_id)).status not in ("completed", "failed", "cancelled"):
            await asyncio.sleep(0.1)
    stop.set()
    await loop
    async with engine.connect() as conn:
        return await jobs.get_job(conn, job_id)


# Submitting.


async def test_the_tasks_are_the_given_urls_then_each_globs_once_in_canonical_form(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    web.serve(
        f"{own_origin}/sitemap.xml",
        _urlset(*(f"{own_origin}{path}" for path in ("/p/1", "/c/1", "/p/2", "/p/3?b=2&amp;a=1"))),
    )
    urls = [f"{own_origin}/p/2#reviews", f"{own_origin.upper()}/p/*", f"{own_origin}/x/9"]

    submitted = await submit_extract(
        engine, fetching, _request(urls, _by_id(kettle_schema)), llm=NO_LLM, data=engine_data
    )

    assert submitted.schema_ == kettle_schema
    assert await _tasks(engine, submitted.job_id) == [
        (f"{own_origin}/p/2#reviews", f"{own_origin}/p/2", "detail"),
        (f"{own_origin}/x/9", f"{own_origin}/x/9", "detail"),
        (f"{own_origin}/p/1", f"{own_origin}/p/1", "detail"),
        (f"{own_origin}/p/3?a=1&b=2", f"{own_origin}/p/3?a=1&b=2", "detail"),
        (f"{own_origin}/p/4", f"{own_origin}/p/4", "detail"),
    ]
    job = await _job(engine, submitted.job_id)
    assert (job.kind, job.status, job.schema_id) == ("extract", "queued", kettle_schema.id)
    assert job.pinned is not None  # INV-28: what its pages run with is pinned at submit
    async with engine.connect() as conn:
        maps: list[str] = list(
            (await conn.execute(select(Job.request["url"].astext).where(Job.kind == "map"))).scalars()
        )
    assert maps == [f"{own_origin}/"]


async def test_limit_keeps_the_first_tasks(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    web.serve(f"{own_origin}/sitemap.xml", _urlset(f"{own_origin}/p/1", f"{own_origin}/p/2"))
    request = _request([f"{own_origin}/x/9", f"{own_origin}/p/*"], _by_id(kettle_schema), limit=2)

    submitted = await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    assert [url for url, _, _ in await _tasks(engine, submitted.job_id)] == [f"{own_origin}/x/9", f"{own_origin}/p/1"]


async def test_globs_that_match_nothing_queue_no_job(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, kettle_schema: SchemaDef, engine_data: EngineData
) -> None:
    request = _request([f"{own_origin}/q/*"], _by_id(kettle_schema))

    with pytest.raises(NothingToExtract):
        await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    assert await _extract_jobs(engine) == []


@pytest.mark.parametrize(
    ("members", "refused"),
    [
        ({"urls": ["{origin}/p/1", f"https://{PRIVATE_HOST}/p/1"]}, "urls[1]"),
        ({"urls": ["{origin}/p/1", f"https://{PRIVATE_HOST}/p/*"]}, "urls[1]"),
        ({"urls": ["{origin}/p/1"], "webhook_url": f"https://{PRIVATE_HOST}/done"}, "webhook_url"),
    ],
)
async def test_a_refused_target_queues_nothing_and_fetches_nothing(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    members: dict[str, Any],
    refused: str,
) -> None:
    urls = [url.format(origin=own_origin) for url in members.pop("urls")]
    request = _request(urls, _by_id(kettle_schema), **members)

    with pytest.raises(TargetsRejected) as rejected:
        await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    assert rejected.value.member == refused
    assert (await _extract_jobs(engine), web.urls()) == ([], [])


async def test_records_need_the_engine_data(
    engine: AsyncEngine, fetching: Fetching, own_origin: str, kettle_schema: SchemaDef
) -> None:
    request = _request([f"{own_origin}/p/1"], _by_id(kettle_schema))

    with pytest.raises(RecordsUnavailable):
        await submit_extract(engine, fetching, request, llm=NO_LLM, data=None)


# A prompt.


async def test_a_prompt_is_drafted_from_the_first_pages_reached_and_returned(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    urls = [f"{own_origin}/p/{n}" for n in range(1, 6)]
    web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[2], _page("Red kettle"))
    web.serve(urls[3], _page("Green kettle"))
    provider = FakeProvider([_draft_reply()])

    submitted = await submit_extract(
        engine, fetching, _request(urls, {"prompt": prompt}), llm=MeteredClient([provider], engine), data=engine_data
    )

    assert (submitted.schema_.name, submitted.schema_.origin) == (draft_name(prompt), "prompt_draft")
    # The first three URLs are fetched for samples; the two reached are the samples (llm spec: cleaned text).
    call = provider.calls[0]  # the draft; its label synonyms (`s_labels`) follow in the background
    assert "Blue kettle boils" in call.user
    assert "Red kettle boils" in call.user
    assert "Green kettle" not in call.user
    assert "<h1>" not in call.user
    job = await _job(engine, submitted.job_id)
    assert (job.status, job.schema_id, job.pinned is not None) == ("running", submitted.schema_.id, True)
    assert [url for url, _, _ in await _tasks(engine, submitted.job_id)] == urls
    async with engine.connect() as conn:
        summary = await jobs.get_job(conn, submitted.job_id)
    assert (summary.usage["llm_calls"], summary.usage["http_requests"]) == (1, 3)  # the three samples


async def test_a_prompt_drafted_before_is_returned_without_a_call(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    web.serve(f"{own_origin}/p/1", _page("Blue kettle"))
    request = _request([f"{own_origin}/p/1"], {"prompt": prompt})
    first = await submit_extract(
        engine, fetching, request, llm=MeteredClient([FakeProvider([_draft_reply()])], engine), data=engine_data
    )

    second = await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    assert second.schema_ == first.schema_
    assert second.job_id != first.job_id


@pytest.mark.parametrize(
    ("served", "reply", "budget", "error"),
    [
        (False, _draft_reply(), 10, NoSamplePage),
        (True, _draft_reply(), 0, BudgetExhausted),
        (True, _draft_reply("listing"), 10, SchemaUnusable),
    ],
)
async def test_a_prompt_without_a_draft_fails_its_job_with_no_tasks(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    prompt: str,
    engine_data: EngineData,
    served: bool,
    reply: ProviderReply,
    budget: int,
    error: type[Exception],
) -> None:
    urls = [f"{own_origin}/p/{n}" for n in range(1, 5)]
    if served:
        web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[3], _page("Red kettle"))  # past the first three: never a sample
    request = _request(urls, {"prompt": prompt}, budget={"llm_calls": budget})
    llm = MeteredClient([FakeProvider([reply])], engine)

    with pytest.raises(error):
        await submit_extract(engine, fetching, request, llm=llm, data=engine_data)

    [(job_id, status)] = await _extract_jobs(engine)
    assert (status, await _tasks(engine, job_id)) == ("failed", [])
    assert urls[3] not in web.urls()


async def test_a_cache_only_prompt_is_drafted_from_stored_captures_and_fetches_nothing(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    prompt: str,
    engine_data: EngineData,
    kettle_schema: SchemaDef,
) -> None:
    urls = [f"{own_origin}/p/1", f"{own_origin}/p/2"]
    web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[1], _page("Red kettle"))
    stored = await submit_extract(
        engine, fetching, _request(urls[:1], _by_id(kettle_schema)), llm=NO_LLM, data=engine_data
    )
    await _run(engine, fetching, engine_data, stored.job_id)
    fetched = len(web.urls())
    provider = FakeProvider([_draft_reply()])
    request = _request(urls, {"prompt": prompt}, fetch={"cache": "only"})

    await submit_extract(engine, fetching, request, llm=MeteredClient([provider], engine), data=engine_data)

    # `cache: only` never fetches (jobs spec, "Request context and actions per page"): the sample is the stored page;
    # the page with no capture is none.
    call = provider.calls[0]  # the draft; its label synonyms (`s_labels`) follow in the background
    assert "Blue kettle boils" in call.user
    assert "Red kettle" not in call.user
    assert len(web.urls()) == fetched


async def test_a_cache_only_prompt_without_a_stored_capture_fetches_nothing_and_fails(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    url = f"{own_origin}/p/1"
    web.serve(url, _page("Blue kettle"))
    request = _request([url], {"prompt": prompt}, fetch={"cache": "only"})
    llm = MeteredClient([FakeProvider([_draft_reply()])], engine)

    with pytest.raises(NoSamplePage):
        await submit_extract(engine, fetching, request, llm=llm, data=engine_data)

    assert web.urls() == []


async def test_a_draft_past_its_timeout_fails_its_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    url = f"{own_origin}/p/1"
    web.serve(url, _page("Blue kettle"))
    web.slow.add(url)
    request = _request([url], {"prompt": prompt})

    with pytest.raises(DraftTimedOut):
        await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data, draft_timeout_s=0.2)

    [(job_id, status)] = await _extract_jobs(engine)
    assert (status, await _tasks(engine, job_id)) == ("failed", [])


async def test_a_job_cancelled_during_its_draft_queues_no_task(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    url = f"{own_origin}/p/1"
    web.serve(url, _page("Blue kettle"))
    web.held[url] = release = asyncio.Event()
    llm = MeteredClient([FakeProvider([_draft_reply()])], engine)
    submitting = asyncio.create_task(
        submit_extract(engine, fetching, _request([url], {"prompt": prompt}), llm=llm, data=engine_data)
    )
    async with asyncio.timeout(30):
        while url not in web.urls():
            await asyncio.sleep(0.05)
    [(job_id, _)] = await _extract_jobs(engine)
    async with engine.begin() as conn:
        await jobs.cancel_job(conn, job_id)
    release.set()

    submitted = await submitting

    assert submitted.job_id == job_id
    assert ((await _job(engine, job_id)).status, await _tasks(engine, job_id)) == ("cancelled", [])


# Running.


async def test_each_page_keeps_its_record_and_counts_toward_its_sites_progressive_state(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    web.serve(f"{own_origin}/sitemap.xml", _urlset(f"{own_origin}/p/1", f"{own_origin}/p/2"))
    web.serve(f"{own_origin}/p/1", _page("Blue kettle"))
    web.serve(f"{own_origin}/p/2", _page("Plain kettle", offers=False))  # a glob's URL is caller-supplied too
    request = _request([f"{own_origin}/p/*", f"{own_origin}/gone"], _by_id(kettle_schema))
    submitted = await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    summary = await _run(engine, fetching, engine_data, submitted.job_id)

    assert summary.status == "completed"
    # `/gone`, and `/p/4`, which the start page links to, are not there.
    assert (summary.outcomes.extracted, summary.outcomes.partial, summary.outcomes.not_found) == (1, 1, 2)
    async with engine.connect() as conn:
        records = (await conn.execute(select(Record.schema_id, Record.complete))).all()
        pages = (await conn.execute(select(ProgressiveState.pages_extracted, ProgressiveState.mode))).one()
    assert sorted(records) == [(kettle_schema.id, False), (kettle_schema.id, True)]
    assert tuple(pages) == (2, "cold")


async def test_a_prompts_job_extracts_with_its_draft(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    urls = [f"{own_origin}/p/1", f"{own_origin}/p/2"]
    web.serve(urls[0], _page("Blue kettle"))
    web.serve(urls[1], _page("Red kettle"))
    llm = MeteredClient([FakeProvider([_draft_reply()])], engine)
    submitted = await submit_extract(engine, fetching, _request(urls, {"prompt": prompt}), llm=llm, data=engine_data)

    summary = await _run(engine, fetching, engine_data, submitted.job_id)

    async with engine.connect() as conn:
        records = (await conn.execute(select(Record.schema_id, Record.complete))).all()
    assert (summary.status, summary.outcomes.extracted) == ("completed", 2)
    assert records == [(submitted.schema_.id, True)] * 2


async def test_role_c_fills_a_required_field_the_page_has_only_in_its_text(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # jobs spec, extraction spec: an extract page is extracted cold, and role C reads a missing required field from
    # the page text. The client commits its usage on its own connection while the task's transaction is open (D-0346).
    url = f"{own_origin}/p/1"
    body = _page("Blue kettle", offers=False).replace(b"</main>", b"<aside>19.90 EUR</aside></main>")
    web.serve(url, body)
    text = ParsedPage.of(fetch_result(url, 200, body).bundle).cleaned_text.text
    start = text.index("19.90 EUR")
    price = {"shown": True, "ref": "", "value": "19.90 EUR", "start": start, "end": start + len("19.90 EUR")}
    reply = ProviderReply(model="fake-fast", text=json.dumps({"fields": {"price": price}}), tokens_in=7, tokens_out=3)
    llm = MeteredClient([FakeProvider([reply])], engine)
    request = _request([url], _by_id(kettle_schema))
    submitted = await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    summary = await _run(engine, fetching, engine_data, submitted.job_id, llm)

    assert (summary.status, summary.outcomes.extracted) == ("completed", 1)
    async with engine.connect() as conn:
        record = (await conn.execute(select(Record.complete, Record.data))).one()
    assert (record.complete, record.data["price"]) == (True, {"amount": "19.90", "currency": "EUR"})
    assert (await _job(engine, submitted.job_id)).usage["llm_calls"] == 1


async def test_a_refused_role_c_call_leaves_the_field_missing_and_is_not_retried(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # llm spec: a call the provider refuses gives no reply, like an unavailable provider; the page keeps its
    # structured values, and its task ends instead of being retried with the same request.
    url = f"{own_origin}/p/1"
    web.serve(url, _page("Blue kettle", offers=False))
    provider = FakeProvider([ProviderRefused("fake", "fake-fast", 400, "schema refused")] * 3)
    request = _request([url], _by_id(kettle_schema))
    submitted = await submit_extract(engine, fetching, request, llm=NO_LLM, data=engine_data)

    summary = await _run(engine, fetching, engine_data, submitted.job_id, MeteredClient([provider], engine))

    assert (summary.status, summary.outcomes.partial, len(provider.calls)) == ("completed", 1, 1)
    async with engine.connect() as conn:
        record = (await conn.execute(select(Record.complete, Record.data))).one()
        task = (await conn.execute(select(UrlTask.status, UrlTask.attempts))).one()
    assert (record.complete, record.data["title"], record.data.get("price")) == (False, "Blue kettle", None)
    assert tuple(task) == ("done", 1)
    assert (await _job(engine, submitted.job_id)).usage.get("llm_calls", 0) == 0
