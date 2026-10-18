"""`fetch.cache`, the request context and the proxy pool check in the scrape service and job submission (D-1432,
D-1434, D-1435): a stored capture is reused only when made the way the request fetches, `only` never fetches,
`bypass` always does, and a caller's secrets are never stored with a scrape or answered with a job's request.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.acquire.politeness import HostLimiter
from crawlerai.acquire.rungs import Rungs
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.redaction import REDACTED
from crawlerai.db.models import Job, UrlTask
from crawlerai.services.batch import BatchScrapeRequest, submit_batch
from crawlerai.services.fetch_options import UnknownProxyPool
from crawlerai.services.fetching import Fetching
from crawlerai.services.jobs import job_request
from crawlerai.services.scrape import ScrapeRequest, scrape
from crawlerai.services.stored_captures import NotCached
from crawlerai.storage.fs import FsStore

pytestmark = pytest.mark.anyio

_PAGE = b"""<!doctype html><html lang="en"><head><title>A lamp</title></head><body><main><h1>A lamp</h1>
<p>A lamp that lights a desk evenly, with an arm that holds its place and a base that does not tip.</p>
<a href="/lamps/a">A</a> <a href="/lamps/b">B</a></main></body></html>"""


@dataclass
class Web:
    """Answers every page with `_PAGE` through the policy it was fetched with, and robots.txt allowing everything."""

    fetch_result: Callable[..., FetchResult]
    fetched: list[tuple[CaptureMethod, str]] = field(default_factory=list)

    def rung(self, method: CaptureMethod) -> Callable[[str, FetchPolicy], Any]:
        async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
            self.fetched.append((method, url))
            body = b"User-agent: *\nAllow: /\n" if url.endswith("/robots.txt") else _PAGE
            return self.fetch_result(url, 200, body, method=method, policy=policy)

        return fetch

    def pages(self) -> list[tuple[CaptureMethod, str]]:
        return [(method, url) for method, url in self.fetched if not url.endswith("/robots.txt")]


async def _public(host: str) -> list[IPAddress]:
    return [ip_address("93.184.215.14")]


@pytest.fixture
def web(fetch_result: Callable[..., FetchResult]) -> Web:
    return Web(fetch_result)


@pytest.fixture
def fetching(web: Web, tmp_path: Path) -> Fetching:
    rungs = Rungs(http=web.rung("http"), browser=web.rung("browser"))
    return Fetching(rungs, SafeConnector(_public), FsStore(tmp_path), HostLimiter(), frozenset({"eu"}))


def _scrape(url: str, **members: Any) -> ScrapeRequest:
    return ScrapeRequest.model_validate({"url": url, "formats": ["markdown"], **members})


async def test_cache_only_with_nothing_stored_fails_without_fetching(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    request = _scrape(f"{own_origin}/lamps/a", fetch={"cache": "only"})

    with pytest.raises(NotCached):
        await scrape(engine, fetching, request)

    assert web.fetched == []
    async with engine.connect() as conn:
        error = (await conn.execute(select(UrlTask.last_error).where(UrlTask.url == request.url))).scalar_one()
    assert error == "not_cached"


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
    assert web.pages() == [("http", url), ("http", url)]


async def test_a_capture_made_with_page_steps_does_not_stand_for_the_page_without_them(
    engine: AsyncEngine, fetching: Fetching, web: Web, own_origin: str
) -> None:
    url = f"{own_origin}/lamps/b"
    clicked = {"actions": [{"type": "click", "selector": "button.more"}]}
    made = await scrape(engine, fetching, _scrape(url, fetch=clicked))

    reused = await scrape(engine, fetching, _scrape(url, max_age=3600, fetch=clicked))
    plain = await scrape(engine, fetching, _scrape(url, max_age=3600))

    assert web.pages()[0] == ("browser", url)  # the steps run in the browser
    assert reused.capture_id == made.capture_id
    assert plain.capture_id != made.capture_id


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
    submitted = await submit_batch(engine, SafeConnector(_public), request, data=None)

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
        await submit_batch(engine, fetching.connector, batch, data=None, proxy_pools=fetching.proxy_pools)
    assert web.fetched == []
