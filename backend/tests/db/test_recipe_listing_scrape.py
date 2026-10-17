"""A listing scrape of a site whose active config has a listing recipe (Appendix A #59, SPEC-09 §4.8): the recipe
serves the listing's pages over HTTP, one capture each, until the request's `records` target, with no browser; when it
does not serve the first page, the browser actions run as before (§4.10).

The web is a stub answering synthetic JSON on RFC 2606 hosts, the listing rung a stub that records being asked: no
network.
"""

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.browser_tab import Drive
from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult, PagedFetch
from crawlerai.db.models import Capture, Extraction, ExtractionConfig, SiteId, UrlTask
from crawlerai.resolve.pipeline import EngineData
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.services.fetching import Fetching
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.storage.fs import FsStore
from tests.db.conftest import listing_page, listing_schema, resolve

pytestmark = pytest.mark.anyio

NAMES = [f"Kettle {letter}" for letter in "ABCDEFGH"]
PAGE_SIZE = 3


@dataclass
class Web:
    """robots.txt over HTTP, the listing endpoint as JSON (`up`: whether it answers), and the listing rung."""

    fetch_result: Callable[..., FetchResult]
    origin: str
    up: bool = True
    requested: list[JsonRequest] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)

    async def http(self, url: str, policy: FetchPolicy) -> FetchResult:
        assert url.endswith("/robots.txt"), "a listing recipe fetches no HTML page"
        return self.fetch_result(url, 200, b"User-agent: *\nAllow: /\n")

    async def json(self, request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        self.requested.append(request)
        if not self.up:
            return self.fetch_result(request.page_url, 500, b"{}", block_class="error", method="api")
        after = parse_qs(urlsplit(request.url).query).get("after", ["0"])[0]
        start = int(after)
        rows = [
            {"label": name, "href": f"{self.origin}/kettles/{start + i}"}
            for i, name in enumerate(NAMES[start : start + PAGE_SIZE])
        ]
        following = start + PAGE_SIZE if start + PAGE_SIZE < len(NAMES) else None
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


def _request(url: str, schema: SchemaDef, records: int) -> ScrapeRequest:
    body = {
        "url": url,
        "formats": ["records"],
        "schema": {"id": str(schema.id)},
        "page_kind": "listing",
        "browser_actions": {"records": records},
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
