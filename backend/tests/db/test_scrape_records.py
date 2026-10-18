"""`records` and `max_age` in the scrape service (SPEC-07 §4.4 steps 2 and 3, INV-22, INV-26): the page's record in
the §13.1 field shape, the rows it leaves, and a recent capture reused instead of a fetch.

The web is a stub that answers synthetic pages on RFC 2606 hosts, and the resolver a stub: no network.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.db.models import (
    Capture,
    Extraction,
    ExtractionConfig,
    Job,
    ProgressiveState,
    Project,
    Record,
    SchemaId,
    Site,
    UrlTask,
)
from crawlerai.db.models import SchemaDef as SchemaRow
from crawlerai.llm.client import MeteredClient, ProviderRefused, ProviderReply
from crawlerai.llm.providers.fake import FakeProvider
from crawlerai.llm.roles.s_wire import to_wire
from crawlerai.resolve import pipeline
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.pipeline import EngineData
from crawlerai.resolve.preference import PRECEDENCE_FILE, load_precedence
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaChanges, SchemaDef, SchemaDocument, document_digest
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.services.scrape_steps import SchemaUnusable
from crawlerai.storage.fs import FsStore
from tests.db.conftest import LISTING_FIELDS, listing_page, listing_schema

pytestmark = pytest.mark.anyio

PAGE = b"""<!doctype html><html lang="en"><head><title>Blue kettle</title></head>
<body><main><h1>Blue kettle</h1>
<p>A kettle that boils water quickly and quietly, with a handle that stays cool to the touch while it pours.</p>
<p>It holds one and a half litres and switches itself off once the water boils, so it never boils dry.</p>
</main></body></html>"""
# A role S reply: a draft schema document without a name (SPEC-06 §4.5).
DRAFT_REPLY = ProviderReply(
    model="fake-strong",
    text=json.dumps(
        to_wire(
            {
                "page_kind": "detail",
                "fields": {"title": {"type": "text", "required": True, "description": "Product name"}},
            }
        )
    ),
    tokens_in=900,
    tokens_out=80,
)


@dataclass
class Web:
    """Answers each URL from `pages` as (status, body, block class) over HTTP; anything else is a 404."""

    fetch_result: Callable[..., FetchResult]
    pages: dict[str, tuple[int, bytes, BlockClass]] = field(default_factory=dict)
    fetched: list[tuple[CaptureMethod, str]] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.fetched.append(("http", url))
        status, body, block_class = self.pages.get(url, (404, b"gone", "not_found"))
        return self.fetch_result(url, status, body, block_class=block_class)

    def page_fetches(self) -> list[tuple[CaptureMethod, str]]:
        return [(method, url) for method, url in self.fetched if not url.endswith("/robots.txt")]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    return Web(fetch_result, {f"{own_origin}/robots.txt": (200, b"User-agent: *\nAllow: /\n", "ok")})


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    async def resolve(_host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    return Fetching(Rungs(http=web.http, browser=web.http), SafeConnector(resolve), FsStore(tmp_path), HostLimiter())


def request(url: str, *formats: str, **fields: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": url, "formats": list(formats), **fields})


async def _row(engine: AsyncEngine, statement: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(statement)).one()


async def _failed(engine: AsyncEngine, url: str) -> tuple[str, str | None, str]:
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask).where(UrlTask.url == url))).one()
        job_status = (await conn.execute(select(Job.status).where(Job.id == task.job_id))).scalar_one()
    return task.status, task.last_error, job_status


TITLE = {"type": "text", "required": True, "description": "The product's name", "schema_org": "Product.name"}
PRICE = {"type": "money", "required": True, "description": "The price", "schema_org": "Offer.price+priceCurrency"}


def _product_page(url: str, *, offers: bool = True) -> bytes:
    node: dict[str, Any] = {"@context": "https://schema.org", "@type": "Product", "name": "Blue kettle", "url": url}
    if offers:
        node["offers"] = {"@type": "Offer", "price": "19.90", "priceCurrency": "EUR"}
    script = f'<script type="application/ld+json">{json.dumps(node)}</script>'
    return PAGE.replace(b"</head>", f"{script}</head>".encode())


def _document(name: str, **fields: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "page_kind": "detail", "fields": fields or {"title": TITLE, "price": PRICE}}


@pytest.fixture
async def kettle_schema(engine: AsyncEngine, schema_name: str) -> SchemaDef:
    document = SchemaDocument.model_validate(_document(schema_name))
    async with engine.begin() as conn:
        return await registry.create(conn, document, "user")


def _records(url: str, schema: dict[str, Any], *formats: str, **fields: Any) -> ScrapeRequest:
    return request(url, *formats, "records", schema=schema, page_kind="detail", **fields)


async def _pages_extracted(engine: AsyncEngine, schema_id: SchemaId) -> list[int]:
    async with engine.connect() as conn:
        query = select(ProgressiveState.pages_extracted).where(ProgressiveState.schema_id == schema_id)
        return list((await conn.execute(query)).scalars())


async def test_a_record_is_stored_with_its_job_task_and_schema(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # The record's field shape over HTTP is `test_scrape_api.py`'s; here, the rows the scrape leaves.
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), data=engine_data)

    assert result.records is not None
    (record,) = result.records
    title = record.fields["title"]
    assert (result.outcome, title.value, title.source_kind) == ("extracted", "Blue kettle", "jsonld")
    async with engine.connect() as conn:
        row = (await conn.execute(select(Record).where(Record.id == record.id))).one()
        task = (await conn.execute(select(UrlTask.outcome).where(UrlTask.job_id == result.job_id))).scalar_one()
        job_schema = (await conn.execute(select(Job.schema_id).where(Job.id == result.job_id))).scalar_one()
    assert (row.job_id, row.schema_id, row.data["title"], row.complete) == (
        result.job_id,
        kettle_schema.id,
        "Blue kettle",
        True,
    )
    assert (task, job_schema) == ("extracted", kettle_schema.id)


async def test_a_page_without_a_required_field_is_partial_and_keeps_its_record(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url, offers=False), "ok")

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), data=engine_data)

    assert result.outcome == "partial"
    assert result.records is not None
    (record,) = result.records
    assert record.complete is False
    price = record.fields["price"]
    assert (price.status, price.value, price.evidence, price.locator) == ("missing", None, None, None)
    # A missing required field asks role C, and this test configures no LLM provider.
    assert price.reason == "llm_unavailable"
    task = await _row(engine, select(UrlTask.status, UrlTask.outcome).where(UrlTask.job_id == result.job_id))
    assert tuple(task) == ("done", "partial")


async def test_a_detail_page_whose_offer_only_a_render_holds_is_read_from_the_browser(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # Owner #49: the HTTP page holds no Offer and no price; its scripts would render them.
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url, offers=False), "ok")

    async def browser(target: str, policy: FetchPolicy) -> FetchResult:
        return fetch_result(target, 200, _product_page(target), method="browser")

    rendering = Fetching(Rungs(http=web.http, browser=browser), fetching.connector, fetching.store, HostLimiter())

    result = await scrape(engine, rendering, _records(url, {"id": str(kettle_schema.id)}), data=engine_data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method) == ("extracted", "browser")
    assert [a.method for a in result.fetch.attempts] == ["http", "browser"]
    assert result.records is not None
    (record,) = result.records
    assert record.fields["price"].value == {"amount": "19.90", "currency": "EUR"}


async def test_a_listing_whose_rows_only_a_render_holds_is_read_from_the_browser(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # Owner #54: the HTTP page holds repeated links that are not its items (related posts) and no rows; its scripts
    # would render the grid. Role C reads the HTTP page once (no provider here); the render's rows are kept.
    url = f"{own_origin}/c/kettles"
    related = "".join(f'<li><a href="{own_origin}/blog/{n}">Post {n}</a></li>' for n in range(1, 4))
    template = f"<!doctype html><html><head><title>Kettles</title></head><body><ul>{related}</ul></body></html>"
    web.pages[url] = (200, template.encode(), "ok")
    rendered: list[str] = []

    async def browser(target: str, policy: FetchPolicy) -> FetchResult:
        rendered.append(target)
        return fetch_result(target, 200, listing_page(own_origin, ["Blue kettle", "Red kettle"]), method="browser")

    rendering = Fetching(Rungs(http=web.http, browser=browser), fetching.connector, fetching.store, HostLimiter())
    schema = await listing_schema(engine, schema_name)
    scraped = request(url, "records", schema={"id": str(schema.id)}, page_kind="listing")

    result = await scrape(engine, rendering, scraped, data=engine_data)

    assert result.fetch is not None
    assert (result.outcome, result.fetch.method, rendered) == ("extracted", "browser", [url])
    assert [a.method for a in result.fetch.attempts] == ["http", "browser"]
    assert result.records is not None
    assert [record.fields["title"].value for record in result.records] == ["Blue kettle", "Red kettle"]
    # The kept capture's extraction is the check's: one extraction is stored, from the render.
    async with engine.connect() as conn:
        stored = (await conn.execute(select(func.count()).select_from(Extraction))).scalar_one()
    assert stored == 1


async def test_a_listing_without_rows_says_why_and_answers_its_page_fields(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, schema_name: str, engine_data: EngineData
) -> None:
    # No structured rows and no item blocks, so role C is not asked for rows; the page states its next page.
    url = f"{own_origin}/c/kettles"
    head = f'<title>Kettles</title><link rel="next" href="{own_origin}/c/kettles?page=2">'
    web.pages[url] = (200, f"<!doctype html><html><head>{head}</head><body><p>Kettles</p></body></html>".encode(), "ok")
    fields = {
        **LISTING_FIELDS,
        "next_page_url": {"type": "url", "description": "The next page", "scope": "page"},
    }
    document = SchemaDocument.model_validate({"name": schema_name, "page_kind": "listing", "fields": fields})
    async with engine.begin() as conn:
        schema = await registry.create(conn, document, "user")

    # The committed precedence ranks `dom`, which states `rel=next` (the fixture's order does not).
    data = replace(engine_data, orders=load_precedence(Path(__file__).parents[2] / "data" / PRECEDENCE_FILE))
    scraped = request(url, "records", schema={"id": str(schema.id)}, page_kind="listing")

    result = await scrape(engine, fetching, scraped, data=data)

    assert (result.records, result.reason) == ([], "no_rows: not_asked")
    assert result.page is not None
    assert result.page["next_page_url"].value == f"{own_origin}/c/kettles?page=2"
    assert set(result.page) == {"next_page_url"}
    task = await _row(engine, select(UrlTask.last_error).where(UrlTask.url == url))
    assert task.last_error == "no_rows: not_asked"
    assert "page" in result.model_dump(by_alias=True)


async def test_a_scrapes_minimum_confidence_leaves_a_calibrated_bucket_below_it_unpublished(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    calibration = Calibration(git_sha="0" * 40, buckets={"money|structured": Bucket(n=40, precision=0.6)})
    data = replace(engine_data, calibration=calibration)
    url = f"{own_origin}/kettles/1"
    web.pages[url] = (200, _product_page(url), "ok")
    schema = {"id": str(kettle_schema.id)}

    free = await scrape(engine, fetching, _records(url, schema), data=data)
    gated = await scrape(engine, fetching, _records(url, schema, min_confidence=0.9), data=data)

    assert free.records is not None
    assert gated.records is not None
    price = free.records[0].fields["price"]
    assert (price.status, price.confidence, price.calibrated) == ("published", 0.6, True)
    held = gated.records[0].fields["price"]
    assert (held.status, held.reason, held.value) == ("abstained", "below_min_confidence", None)


async def test_a_detail_page_answers_no_page_member(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/1"
    web.pages[url] = (200, _product_page(url), "ok")

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), data=engine_data)

    assert (result.outcome, result.reason, result.page) == ("extracted", None, None)
    assert "page" not in result.model_dump(by_alias=True)


async def test_role_c_fills_a_required_field_the_page_has_only_in_its_text(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    # SPEC-07 §4.4 step 3: `records` extracts with role C when required fields are missing (SPEC-06).
    url = f"{own_origin}/kettles/blue"
    body = _product_page(url, offers=False).replace(b"</main>", b"<aside>19.90 EUR</aside></main>")
    web.pages[url] = (200, body, "ok")
    text = ParsedPage.of(fetch_result(url, 200, body).bundle).cleaned_text.text
    start = text.index("19.90 EUR")
    price = {"shown": True, "ref": "", "value": "19.90 EUR", "start": start, "end": start + len("19.90 EUR")}
    reply = ProviderReply(model="fake-fast", text=json.dumps({"fields": {"price": price}}), tokens_in=7, tokens_out=3)
    llm = MeteredClient([FakeProvider([reply])], engine)

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), llm=llm, data=engine_data)

    assert result.outcome == "extracted"
    assert result.records is not None
    price_field = result.records[0].fields["price"]
    assert (price_field.value, price_field.source_kind) == ({"amount": "19.90", "currency": "EUR"}, "llm")
    assert result.usage.llm_calls == 1


async def test_a_refused_role_c_call_keeps_the_structured_values_and_answers(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # SPEC-06 §4.7: the provider refusing the request (a 400) leaves the asked fields missing with its reason.
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url, offers=False), "ok")
    provider = FakeProvider([ProviderRefused("fake", "fake-fast", 400, "schema refused")])

    result = await scrape(
        engine,
        fetching,
        _records(url, {"id": str(kettle_schema.id)}),
        llm=MeteredClient([provider], engine),
        data=engine_data,
    )

    assert (result.outcome, len(provider.calls), result.usage.llm_calls) == ("partial", 1, 0)
    assert result.records is not None
    fields = result.records[0].fields
    assert (fields["price"].status, fields["price"].reason) == ("missing", "llm_refused")
    assert fields["title"].status == "published"


async def test_a_role_c_call_that_fails_after_answering_counts_its_calls_as_usage_does(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # F30: two answered, invalid replies (the one retry, SPEC-06 §4.2) are charged; the extraction says so too.
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url, offers=False), "ok")
    invalid = ProviderReply(model="fake-fast", text="not json", tokens_in=7, tokens_out=3)
    provider = FakeProvider([invalid, invalid])

    result = await scrape(
        engine,
        fetching,
        _records(url, {"id": str(kettle_schema.id)}),
        llm=MeteredClient([provider], engine),
        data=engine_data,
    )

    async with engine.connect() as conn:
        extraction = (await conn.execute(select(Extraction.llm_calls, Extraction.diagnostics))).one()
    assert (len(provider.calls), result.usage.llm_calls, extraction.llm_calls) == (2, 2, 2)
    assert "role C: llm_output_invalid" in extraction.diagnostics


async def test_each_extracted_or_partial_page_counts_toward_progressive_state(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    complete, partial, gone = (f"{own_origin}/kettles/{name}" for name in ("blue", "red", "gone"))
    web.pages[complete] = (200, _product_page(complete), "ok")
    web.pages[partial] = (200, _product_page(partial, offers=False), "ok")
    schema = {"id": str(kettle_schema.id)}

    outcomes = [
        (await scrape(engine, fetching, _records(url, schema), data=engine_data)).outcome
        for url in (complete, partial, gone)
    ]

    assert outcomes == ["extracted", "partial", "not_found"]
    assert await _pages_extracted(engine, kettle_schema.id) == [2]


def _holds_head_script(parser_input: object) -> bool:
    text = parser_input.decode() if isinstance(parser_input, bytes) else parser_input
    return isinstance(text, str) and "application/ld+json" in text


async def test_formats_and_records_read_one_parse_of_the_page(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    parses: Mapping[str, Any],
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    formats = ("markdown", "html", "raw_html", "links", "metadata")

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}, *formats), data=engine_data)

    assert result.outcome == "extracted"
    # INV-26: every format and the records read one selectolax parse and one lxml parse of the page. trafilatura's
    # readability fallback parses its own output, a new document without the `<head>`, so a parse of the page is one
    # whose input still holds the head's JSON-LD block.
    body_parses = {name: sum(map(_holds_head_script, counter.inputs)) for name, counter in parses.items()}
    assert body_parses == {"selectolax": 1, "lxml": 1}


async def test_an_inline_schema_is_stored_once_and_reused(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    inline = {"inline": _document(schema_name)}

    first = await scrape(engine, fetching, _records(url, inline), data=engine_data)
    second = await scrape(engine, fetching, _records(url, inline), data=engine_data)

    assert first.records is not None
    assert second.records is not None
    assert first.records[0].fields["title"].value == "Blue kettle"
    jobs = [first.job_id, second.job_id]
    async with engine.connect() as conn:
        stored = (await conn.execute(select(SchemaRow.id, SchemaRow.origin).where(SchemaRow.name == schema_name))).all()
        used = set((await conn.execute(select(Record.schema_id).where(Record.job_id.in_(jobs)))).scalars())
    ((schema_id, origin),) = stored
    assert (origin, used) == ("user", {schema_id})


async def _unusable_schema(engine: AsyncEngine, schema: SchemaDef, problem: str) -> SchemaId:
    """A schema id records cannot use: a retired schema, or a listing schema."""
    async with engine.begin() as conn:
        if problem == "retired":
            return (await registry.retire(conn, schema.id)).id
        changes = SchemaChanges(page_kind="listing")
        return (await registry.update_schema(conn, schema, changes)).id


@pytest.mark.parametrize(
    ("problem", "message"),
    [("retired", "is retired"), ("listing", "is for listing pages")],
)
async def test_a_schema_id_records_cannot_use_is_refused_before_any_job(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    problem: str,
    message: str,
) -> None:
    schema_id = await _unusable_schema(engine, kettle_schema, problem)
    scrape_request = _records(f"{own_origin}/kettles/blue", {"id": str(schema_id)})

    with pytest.raises(SchemaUnusable, match=message):
        await scrape(engine, fetching, scrape_request, data=engine_data)

    assert web.fetched == []


async def test_a_page_not_reached_has_no_records(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (403, b"<html><body>no</body></html>", "blocked")
    scrape_request = _records(url, {"id": str(kettle_schema.id)})

    result = await scrape(engine, fetching, scrape_request, data=engine_data)

    assert result.outcome == "blocked"
    assert "records" not in result.model_dump(by_alias=True)
    async with engine.connect() as conn:
        extractions = select(func.count()).select_from(Extraction).join(UrlTask).where(UrlTask.job_id == result.job_id)
        assert (await conn.execute(extractions)).scalar_one() == 0


async def test_a_page_whose_resolution_fails_is_failed_without_formats_or_records(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")

    def broken(*_args: object) -> None:
        raise RuntimeError("resolution bug")

    monkeypatch.setattr(pipeline, "_read_and_resolve", broken)

    result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}, "markdown"), data=engine_data)

    assert result.outcome == "failed"
    assert (result.records, result.markdown) == (None, None)
    assert await _failed(engine, url) == ("failed", "extraction_error", "failed")


async def test_a_prompt_draft_is_the_schema_of_the_records(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    llm = MeteredClient([FakeProvider([DRAFT_REPLY])], engine)

    result = await scrape(engine, fetching, _records(url, {"prompt": prompt}), llm=llm, data=engine_data)

    assert result.schema_ is not None
    assert result.records is not None
    (record,) = result.records
    assert list(record.fields) == ["title"]
    stored = await _row(engine, select(Record.schema_id).where(Record.id == record.id))
    assert stored.schema_id == result.schema_.id


async def test_one_page_is_one_entity_whatever_the_order_of_its_query_pairs(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # SPEC-10 §4.1: a scrape keys its task by the canonical form a crawl and an extract use (query pairs sorted), so the
    # entity key (SPEC-05 §4.10) of a page does not depend on the job kind that fetched it.
    urls = [f"{own_origin}/p?id=5&color=red", f"{own_origin}/p?color=red&id=5"]
    for url in urls:
        web.pages[url] = (200, _product_page(url), "ok")

    results = [
        await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), data=engine_data) for url in urls
    ]

    async with engine.connect() as conn:
        jobs = [result.job_id for result in results]
        canonical = set((await conn.execute(select(UrlTask.canonical_url).where(UrlTask.job_id.in_(jobs)))).scalars())
        keys = set((await conn.execute(select(Record.entity_key).where(Record.job_id.in_(jobs)))).scalars())
    assert (canonical, len(keys)) == ({f"{own_origin}/p?color=red&id=5"}, 1)


async def test_a_prompt_draft_of_another_page_kind_fails_the_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, prompt: str, engine_data: EngineData
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    title: dict[str, JsonValue] = {"type": "text", "required": True, "description": "Product name", "scope": "row"}
    listing = ProviderReply(
        model="fake-strong",
        text=json.dumps(to_wire({"page_kind": "listing", "fields": {"title": title}})),
        tokens_in=1,
        tokens_out=1,
    )
    llm = MeteredClient([FakeProvider([listing])], engine)
    scrape_request = _records(url, {"prompt": prompt})

    with pytest.raises(SchemaUnusable, match="is for listing pages, not detail"):
        await scrape(engine, fetching, scrape_request, llm=llm, data=engine_data)

    assert await _failed(engine, url) == ("failed", "invalid_schema", "failed")


async def test_max_age_reuses_a_recent_capture_without_fetching(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    first = await scrape(engine, fetching, request(url, "raw_html"))
    scrape_request = _records(url, {"id": str(kettle_schema.id)}, "raw_html", max_age=3600)

    second = await scrape(engine, fetching, scrape_request, data=engine_data)

    assert web.page_fetches() == [("http", url)]
    assert (second.outcome, second.capture_id, second.fetched_at) == ("extracted", first.capture_id, first.fetched_at)
    assert second.fetch == first.fetch
    assert second.raw_html == first.raw_html
    assert second.records is not None
    assert second.records[0].complete
    assert second.usage.http_requests == 0
    task = await _row(engine, select(UrlTask.outcome, UrlTask.capture_id).where(UrlTask.job_id == second.job_id))
    assert tuple(task) == ("extracted", first.capture_id)


@pytest.mark.parametrize("max_age", [0, 60])
async def test_a_capture_outside_max_age_is_fetched_again(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str, max_age: int
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, PAGE, "ok")
    first = await scrape(engine, fetching, request(url, "raw_html"))
    async with engine.begin() as conn:
        aged = Capture.fetched_at - timedelta(hours=1)
        await conn.execute(update(Capture).where(Capture.id == first.capture_id).values(fetched_at=aged))

    second = await scrape(engine, fetching, request(url, "raw_html", max_age=max_age))

    assert len(web.page_fetches()) == 2
    assert second.capture_id != first.capture_id


async def test_a_capture_that_did_not_reach_the_page_is_not_reused(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (403, b"<html><body>no</body></html>", "blocked")
    await scrape(engine, fetching, request(url, "raw_html", fetch={"method_hint": "http"}))
    web.pages[url] = (200, PAGE, "ok")

    second = await scrape(engine, fetching, request(url, "raw_html", max_age=3600))

    assert len(web.page_fetches()) == 2
    assert (second.outcome, second.raw_html) == ("extracted", PAGE.decode())


async def test_a_site_with_an_active_config_is_scraped_in_config_mode_and_the_page_joins_its_drift_window(
    engine: AsyncEngine,
    fetching: Fetching,
    web: Web,
    own_origin: str,
    kettle_schema: SchemaDef,
    engine_data: EngineData,
) -> None:
    # SPEC-08 §4.8, §4.9: the site's active config runs on the page, and the page is added to the config's window.
    url = f"{own_origin}/kettles/blue"
    web.pages[url] = (200, _product_page(url), "ok")
    host = own_origin.removeprefix("https://")
    ir = {
        "ir_version": "1",
        "site": host,
        "schema": {"name": kettle_schema.name, "digest": document_digest(kettle_schema)},
        "page_kind": "detail",
        "fetch": {"method": "http"},
        "fields": {"title": {"steps": [{"xpath": "normalize-space(//h1)"}], "status": "corroborated"}},
        "provenance": {
            "origin": "induced",
            "validated_on": [],
            "learned_at": "2026-10-01T00:00:00Z",
            "engine_version": "test",
        },
    }
    async with engine.begin() as conn:
        project = select(Project.id).where(Project.name == "default").scalar_subquery()
        site_id = (
            await conn.execute(insert(Site).values(project_id=project, host=host).returning(Site.id))
        ).scalar_one()
        config = insert(ExtractionConfig).values(
            site_id=site_id,
            schema_id=kettle_schema.id,
            page_kind="detail",
            version=3,
            status="active",
            ir=ir,
            origin="induced",
            field_status={"title": "corroborated"},
        )
        config_id = (await conn.execute(config.returning(ExtractionConfig.id))).scalar_one()
    try:
        result = await scrape(engine, fetching, _records(url, {"id": str(kettle_schema.id)}), data=engine_data)

        assert result.records is not None
        (record,) = result.records
        assert (result.outcome, record.mode) == ("extracted", "config")
        extraction = await _row(engine, select(Extraction.mode, Extraction.config_version))
        window = await _row(engine, select(ExtractionConfig.drift_window).where(ExtractionConfig.id == config_id))
        assert (tuple(extraction), window.drift_window) == (("config", 3), {"title": [[True, True]]})
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(ExtractionConfig).where(ExtractionConfig.id == config_id))
