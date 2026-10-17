"""The Teamtailor adapter: detect career site URLs, fetch the JSON Feed of jobs, read it as schema.org JobPostings.
Hosts come from the adapter module (C3); the feed under `tests/fixtures/teamtailor/` is synthetic."""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from crawlerai.adapters.teamtailor import DOMAIN, Teamtailor
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = Teamtailor()
COMPANY = "example-co"
FEED = f"https://{COMPANY}.{DOMAIN}/jobs.json"
labels = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?", fullmatch=True)


@given(company=labels, path=st.sampled_from(["", "/", "/jobs", "/jobs/"]))
def test_a_company_url_is_a_listing_of_its_company(company: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{company}.{DOMAIN}{path}") == AdapterMatch(tenant=company, page_kind="listing")


@pytest.mark.parametrize(
    "url",
    [
        f"https://{COMPANY}.{DOMAIN}.example.com/jobs",
        f"https://{DOMAIN}/jobs",
        f"ftp://{COMPANY}.{DOMAIN}/jobs",
        f"https://{COMPANY}.{DOMAIN}/jobs?department=x",  # a filtered list
        f"https://{COMPANY}.{DOMAIN}/jobs/101-synthetic-engineer",  # the feed has no endpoint for one job
        f"https://{COMPANY}.{DOMAIN}/people",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_company_page_is_fetched_from_its_feed(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "teamtailor" / "jobs.json").read_bytes()
    page = f"https://{COMPANY}.{DOMAIN}/jobs"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({FEED: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, FEED)
    assert result.bundle.body == body
    assert ADAPTER.serves(AdapterMatch(COMPANY, "listing"), FEED) is True
    assert ADAPTER.serves(AdapterMatch(COMPANY, "listing"), f"https://other.{DOMAIN}/jobs.json") is False


def test_a_company_with_an_empty_feed_is_not_served(stand_in_api: StandInApi) -> None:
    send = stand_in_api({FEED: b'{"version": "https://example.test/feed/1.1", "items": []}'})

    result = asyncio.run(ADAPTER.fetch(f"https://{COMPANY}.{DOMAIN}/jobs", FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a career site URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/jobs", FetchPolicy(), _unused_send))


def test_every_feed_item_is_a_posting_with_the_schema_org_members_of_its_job() -> None:
    body = (FIXTURES / "teamtailor" / "jobs.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "listing"), body)

    row = "adapter:teamtailor:$['items'][{}]"
    place = {
        "address": {
            "streetAddress": "1 Example Way",
            "addressLocality": "Northtown",
            "addressRegion": "Exampleland",
            "postalCode": "00000",
            "addressCountry": "ZZ",
        }
    }
    assert found == {
        (row.format(0), "title"): "Synthetic Engineer",
        (row.format(0), "url"): "https://example-co.careers.example.test/jobs/101-synthetic-engineer",
        (row.format(0), "description"): "<p>Build things.</p>",
        (row.format(0), "date_posted"): "2026-09-30T09:00:00+02:00",
        (row.format(0), "identifier"): 101,
        (row.format(0), "locations"): [place],
        (row.format(0), "company"): "Example Co",
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "url"): "https://example-co.careers.example.test/jobs/102-placeholder-analyst",
        (row.format(1), "description"): "<p>Analyse things.</p>",
        (row.format(1), "date_posted"): "2026-09-29T09:00:00+02:00",
        (row.format(1), "identifier"): 102,
    }
