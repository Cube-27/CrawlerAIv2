"""A scrape's browser actions (owner #52): the listing rung's kept document states each become a capture with its own
extraction, the answer lists their records once each with the actions' report, and robots.txt is asked first.

The listing rung is a stub that returns synthetic ItemList pages on RFC 2606 hosts; the browser itself is
`tests/unit/test_paging_browser.py`'s. No network.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.browser_tab import Drive
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.session import CookieExport, SiteSessions
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import ActionsReport, BrowserActions, FetchPolicy, FetchResult, PagedFetch
from crawlerai.core.capture import BlockClass
from crawlerai.db.models import Capture, Extraction, UrlTask
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.fs import FsStore
from tests.db.conftest import listing_page, listing_schema

pytestmark = pytest.mark.anyio

REPORT = ActionsReport(mechanism="pagination", stop="records", actions=1, pages=2, items=4)


@dataclass
class Listing:
    """The listing rung: answers with `pages` and `REPORT`, and records what it was asked."""

    fetch_result: Callable[..., FetchResult]
    pages: list[tuple[str, bytes]] = field(default_factory=list)
    asked: list[tuple[str, FetchPolicy]] = field(default_factory=list)
    drives: list[Drive] = field(default_factory=list)

    async def __call__(self, url: str, policy: FetchPolicy, drive: Drive) -> PagedFetch:
        self.asked.append((url, policy))
        self.drives.append(drive)
        results = tuple(
            self.fetch_result(url, 200, body, method="browser", policy=policy, final_url=final)
            for final, body in self.pages
        )
        return PagedFetch(pages=results, report=REPORT)


@pytest.fixture
def listing(fetch_result: Callable[..., FetchResult]) -> Listing:
    return Listing(fetch_result)


@pytest.fixture
def fetching(fetch_result: Callable[..., FetchResult], listing: Listing, own_origin: str, tmp_path: Path) -> Fetching:
    robots = f"{own_origin}/robots.txt"

    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        assert url == robots, "a listing with browser actions is fetched by the listing rung only"
        return fetch_result(url, 200, b"User-agent: *\nDisallow: /private\n")

    async def resolve(_host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    rungs = Rungs(http=http, browser=http, listing=listing)
    return Fetching(rungs, SafeConnector(resolve), FsStore(tmp_path), HostLimiter())


def _request(url: str, schema_id: object, **fields: Any) -> ScrapeRequest:
    body = {"url": url, "formats": ["records"], "schema": {"id": str(schema_id)}, "page_kind": "listing", **fields}
    return ScrapeRequest.model_validate(body)


async def test_each_kept_state_is_a_capture_and_the_answer_lists_every_record_once(
    engine: AsyncEngine,
    fetching: Fetching,
    listing: Listing,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
) -> None:
    url, second = f"{own_origin}/kettles", f"{own_origin}/kettles?page=2"
    listing.pages = [
        (url, listing_page(own_origin, ["Blue kettle", "Red kettle"], next_page=second)),
        # The second state repeats the first one's last row.
        (second, listing_page(own_origin, ["Red kettle", "Green kettle", "Grey kettle"], first=2)),
    ]
    schema = await listing_schema(engine, schema_name)

    result = await scrape(engine, fetching, _request(url, schema.id, browser_actions={"records": 4}), data=engine_data)

    assert result.records is not None
    assert [r.fields["title"].value for r in result.records] == [
        "Blue kettle",
        "Red kettle",
        "Green kettle",
        "Grey kettle",
    ]
    assert (result.outcome, result.browser_actions) == ("extracted", REPORT)
    assert result.final_url == url  # the scrape's capture is the first state's
    ((asked_url, policy),) = listing.asked
    assert (asked_url, policy.page_kind) == (url, "listing")
    async with engine.connect() as conn:
        task = (await conn.execute(select(UrlTask.id).where(UrlTask.job_id == result.job_id))).scalar_one()
        extractions = (
            await conn.execute(select(func.count()).select_from(Extraction).where(Extraction.url_task_id == task))
        ).scalar_one()
        captures = (
            await conn.execute(
                select(func.count())
                .select_from(Capture)
                .join(Extraction, Extraction.capture_id == Capture.id)
                .where(Extraction.url_task_id == task)
            )
        ).scalar_one()
    assert (extractions, captures) == (2, 2)


async def test_the_callers_page_steps_go_to_the_listing_rung_with_the_paging_actions(
    engine: AsyncEngine,
    fetching: Fetching,
    listing: Listing,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
) -> None:
    url = f"{own_origin}/kettles"
    listing.pages = [(url, listing_page(own_origin, ["Blue kettle", "Red kettle"]))]
    schema = await listing_schema(engine, schema_name)
    request = _request(
        url,
        schema.id,
        browser_actions={},
        fetch={"wait_for": 500, "actions": [{"type": "click", "text": "Accept"}]},
    )

    result = await scrape(engine, fetching, request, data=engine_data)

    ((_, policy),) = listing.asked
    assert [(step.action, step.text) for step in policy.steps] == [("wait", None), ("click", "Accept")]
    assert (result.outcome, result.browser_actions) == ("extracted", REPORT)


async def test_a_listing_robots_txt_disallows_is_not_fetched(
    engine: AsyncEngine,
    fetching: Fetching,
    listing: Listing,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
) -> None:
    schema = await listing_schema(engine, schema_name)

    result = await scrape(
        engine, fetching, _request(f"{own_origin}/private/kettles", schema.id, browser_actions={}), data=engine_data
    )

    assert (result.outcome, result.capture_id, result.browser_actions, listing.asked) == ("blocked", None, None, [])


def test_browser_actions_default_to_a_soft_target_of_100_rows_and_no_hint() -> None:
    request = _request("https://shop.example.test/kettles", "0192f5a4-0000-7000-8000-000000000001", browser_actions={})

    assert request.browser_actions == BrowserActions(records=100, hint=None)


def _growing(
    fetching: Fetching,
    own_origin: str,
    page: bytes,
    fetch_result: Callable[..., FetchResult],
    block_class: BlockClass = "ok",
) -> Fetching:
    """`fetching` whose HTTP rung serves `page` at every URL but robots.txt, as `block_class`, with site sessions and
    their exporting browser rung, as the API process has them."""
    robots = f"{own_origin}/robots.txt"

    async def http(url: str, policy: FetchPolicy) -> FetchResult:
        if url == robots:
            return fetch_result(url, 200, b"User-agent: *\nDisallow: /private\n")
        return fetch_result(url, 200, page, policy=policy, block_class=block_class)

    async def exporting(url: str, policy: FetchPolicy, *, export: CookieExport) -> FetchResult:
        raise AssertionError("a growing scrape renders with the listing rung")

    rungs = Rungs(http=http, browser=http, listing=fetching.rungs.listing, sessions=SiteSessions(), exporting=exporting)
    return Fetching(rungs, fetching.connector, fetching.store, HostLimiter())


@pytest.mark.parametrize("http_class", ["ok", "shell"])
async def test_a_listing_scrape_that_renders_grows_its_list_by_default(
    engine: AsyncEngine,
    fetching: Fetching,
    listing: Listing,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
    http_class: BlockClass,
) -> None:
    # Master plan 2026-10-18 decision 11: a single-URL listing scrape in `auto`, rendered because its HTTP document
    # shows no item blocks, takes the default browser actions (100 records) without asking for them.
    url, second = f"{own_origin}/kettles", f"{own_origin}/kettles?page=2"
    template = b"<!doctype html><html><head><title>Kettles</title></head><body><div id='grid'></div></body></html>"
    listing.pages = [
        (url, listing_page(own_origin, ["Blue kettle", "Red kettle"], next_page=second)),
        (second, listing_page(own_origin, ["Green kettle", "Grey kettle"], first=3)),
    ]
    schema = await listing_schema(engine, schema_name)
    growing = _growing(fetching, own_origin, template, fetch_result, http_class)

    result = await scrape(engine, growing, _request(url, schema.id), data=engine_data)

    assert result.records is not None
    titles = [r.fields["title"].value for r in result.records]
    assert titles == ["Blue kettle", "Red kettle", "Green kettle", "Grey kettle"]
    assert (result.outcome, result.browser_actions) == ("extracted", REPORT)
    assert result.fetch is not None
    assert [a.method for a in result.fetch.attempts] == ["http", "browser"]
    (drive,) = listing.drives
    assert isinstance(drive, partial)
    assert drive.keywords["request"] == BrowserActions()


async def test_a_listing_scrape_whose_http_page_shows_its_items_is_not_rendered_nor_grown(
    engine: AsyncEngine,
    fetching: Fetching,
    listing: Listing,
    own_origin: str,
    schema_name: str,
    engine_data: EngineData,
    fetch_result: Callable[..., FetchResult],
) -> None:
    url = f"{own_origin}/kettles"
    cards = "".join(
        f'<li><a href="{own_origin}/kettles/{n}"><img src="/i/{n}.jpg" alt="">Kettle {n}</a></li>' for n in range(1, 6)
    )
    page = f"<!doctype html><html><body><main><ul>{cards}</ul></main></body></html>".encode()
    schema = await listing_schema(engine, schema_name)

    growing = _growing(fetching, own_origin, page, fetch_result)

    result = await scrape(engine, growing, _request(url, schema.id), data=engine_data)

    assert listing.asked == []
    assert result.browser_actions is None
