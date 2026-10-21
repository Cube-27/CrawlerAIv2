"""`fetch.cache`, the request context and the proxy pool check in the scrape service and job submission (D-1432,
D-1434, D-1435): a stored capture is reused only when made the way the request fetches, `only` never fetches,
`bypass` always does, and a caller's secrets are never stored with a scrape or answered with a job's request.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchResult
from crawlerai.core.egress import Egresses
from crawlerai.core.proxy import ProxyPool
from crawlerai.core.redaction import REDACTED
from crawlerai.db.models import Capture, Job
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetch_options import UnknownProxyPool
from crawlerai.services.fetching import Fetching
from crawlerai.services.jobs import job_request
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.services.stored_captures import NotCached
from tests.db.support import Web, fetching_from, resolve

pytestmark = pytest.mark.anyio

_PAGE = b"""<!doctype html><html lang="en"><head><title>A lamp</title></head><body><main><h1>A lamp</h1>
<p>A lamp that lights a desk evenly, with an arm that holds its place and a base that does not tip.</p>
<a href="/lamps/a">A</a> <a href="/lamps/b">B</a></main></body></html>"""


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult], own_origin: str) -> Web:
    """`own_origin`, robots.txt allowing everything, serving `_PAGE` at `/lamps/a`."""
    site = Web.site(fetch_result, own_origin)
    site.serve(f"{own_origin}/lamps/a", _PAGE)
    return site


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    return fetching_from(web, tmp_path, egresses=Egresses({"eu": ProxyPool.parse("http://proxy.test:3128")}))


def _scrape(url: str, **members: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": url, "formats": ["markdown"], **members})


async def test_cache_only_serves_the_stored_capture_of_any_age_and_bypass_fetches_again(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/lamps/a"
    first = await scrape(engine, fetching, _scrape(url))

    stored = await scrape(engine, fetching, _scrape(url, fetch={"cache": "only"}))
    again = await scrape(engine, fetching, _scrape(url, max_age=3600, fetch={"cache": "bypass"}))

    assert stored.capture_id == first.capture_id
    assert stored.markdown == first.markdown
    assert again.capture_id not in (None, first.capture_id)
    assert web.page_fetches() == [("http", url), ("http", url)]


async def test_cache_only_serves_a_capture_only_to_the_same_cookie_value(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    url = f"{own_origin}/lamps/a"
    first = await scrape(engine, fetching, _scrape(url, fetch={"cookies": {"sid": "alice"}}))

    same = await scrape(engine, fetching, _scrape(url, fetch={"cache": "only", "cookies": {"sid": "alice"}}))
    assert same.capture_id == first.capture_id
    for other in ({"cookies": {"sid": "bob"}}, {}):
        with pytest.raises(NotCached):
            await scrape(engine, fetching, _scrape(url, fetch={"cache": "only", **other}))
    async with engine.connect() as conn:
        policy: dict[str, Any] = (
            await conn.execute(select(Capture.fetch_policy).where(Capture.id == first.capture_id))
        ).scalar_one()
    assert "alice" not in json.dumps(policy)


async def test_a_scrape_stores_its_request_with_the_cookie_redacted(
    engine: AsyncEngine, fetching: Fetching, own_origin: str
) -> None:
    result = await scrape(engine, fetching, _scrape(f"{own_origin}/lamps/a", fetch={"cookies": {"sid": "s3cret"}}))

    async with engine.connect() as conn:
        stored: dict[str, Any] = (await conn.execute(select(Job.request).where(Job.id == result.job_id))).scalar_one()
    assert stored["fetch"]["cookies"] == {"sid": REDACTED}


async def test_a_batch_keeps_the_cookie_for_its_workers_and_answers_it_redacted(
    engine: AsyncEngine, own_origin: str
) -> None:
    request = BatchScrapeRequest.model_validate(
        {"urls": [f"{own_origin}/lamps/a"], "formats": ["markdown"], "fetch": {"cookies": {"sid": "s3cret"}}}
    )
    submitted = await submit_batch(engine, SafeConnector(resolve), request, data=None)

    async with engine.connect() as conn:
        stored: dict[str, Any] = (
            await conn.execute(select(Job.request).where(Job.id == submitted.job_id))
        ).scalar_one()
        answered = await job_request(conn, submitted.job_id)
    assert stored["fetch"]["cookies"] == {"sid": "s3cret"}
    assert answered["fetch"]["cookies"] == {"sid": REDACTED}


async def test_a_proxy_pool_not_configured_is_refused_before_any_job(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    request = _scrape(f"{own_origin}/lamps/a", fetch={"proxy_pool": "us"})

    with pytest.raises(UnknownProxyPool):
        await scrape(engine, fetching, request)

    batch = BatchScrapeRequest.model_validate(
        {"urls": [request.url], "formats": ["markdown"], "fetch": {"proxy_pool": "us"}}
    )
    with pytest.raises(UnknownProxyPool):
        await submit_batch(engine, fetching.connector, batch, data=None, egresses=fetching.egresses)
    assert web.fetched == []


async def test_a_job_pins_one_pool_and_its_egress_at_submit(engine: AsyncEngine) -> None:
    pool = ProxyPool.parse({"endpoints": ["http://p.test:3128"], "mode": "rotate", "country": "DE"})
    egresses = Egresses({"eu": pool, "other": ProxyPool.parse("http://q.test:3128")}, "US")

    async def pinned(url: str, **fetch: Any) -> tuple[str | None, str | None, str]:
        request = BatchScrapeRequest.model_validate({"urls": [url], "formats": ["markdown"], "fetch": fetch})
        job = await submit_batch(engine, SafeConnector(resolve), request, data=None, egresses=egresses)
        columns = (Job.request, Job.egress_country, Job.egress_basis)
        async with engine.connect() as conn:
            row = (await conn.execute(select(*columns).where(Job.id == job.job_id))).one()
        return row.request["fetch"]["proxy_pool"], row.egress_country, row.egress_basis

    # The request's pool gives its declared country, a pool without one is unknown (never the machine's), and a job
    # with no pool goes out from the machine.
    assert await pinned("https://pooled.example.test/a", proxy_pool="eu") == ("eu", "DE", "pool")
    assert await pinned("https://pooled.example.test/a", proxy_pool="other") == ("other", None, "unknown")
    assert await pinned("https://plain.example.test/a") == (None, "US", "machine")
