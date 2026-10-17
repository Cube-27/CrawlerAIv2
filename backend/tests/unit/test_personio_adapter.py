"""The Personio adapter: detect career site URLs, fetch the XML feed (read into JSON by the bounded XML reader), read it
as schema.org JobPostings. Hosts come from the adapter module (C3); the feed under `tests/fixtures/personio/` is
synthetic."""

import asyncio
import json
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from crawlerai.adapters.personio import DOMAINS, Personio
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = Personio()
DOMAIN = sorted(DOMAINS)[0]
HOST = f"example-co.{DOMAIN}"
FEED = f"https://{HOST}/xml"
labels = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?", fullmatch=True)


@given(company=labels, domain=st.sampled_from(sorted(DOMAINS)), path=st.sampled_from(["", "/"]))
def test_a_company_url_is_a_listing_of_its_host(company: str, domain: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{company}.{domain}{path}") == AdapterMatch(
        tenant=f"{company}.{domain}", page_kind="listing"
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/",
        f"https://{DOMAIN}/",
        f"https://{HOST}.{DOMAIN}/",
        f"ftp://{HOST}/",
        f"https://{HOST}/?language=en",
        f"https://{HOST}/job/9001",  # the feed has no endpoint for one job
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_company_page_is_fetched_from_its_feed_and_recorded_as_json(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "personio" / "feed.xml").read_bytes()
    page = f"https://{HOST}/"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({FEED: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, FEED)
    positions = json.loads(result.bundle.body)["workzag-jobs"][0]["position"]
    assert [p["id"] for p in positions] == [["9001"], ["9002"]]
    assert ADAPTER.serves(AdapterMatch(HOST, "listing"), FEED) is True
    assert ADAPTER.serves(AdapterMatch(HOST, "listing"), f"https://other.{DOMAIN}/xml") is False


@pytest.mark.parametrize(
    "body",
    [
        b"<!doctype html><title>Page Not Found</title>",
        b'<!DOCTYPE r [<!ENTITY a "aaaa">]><workzag-jobs><position><name>&a;</name></position></workzag-jobs>',
        b"<workzag-jobs></workzag-jobs>",
    ],
)
def test_an_answer_that_is_not_a_feed_with_positions_is_not_served(stand_in_api: StandInApi, body: bytes) -> None:
    result = asyncio.run(ADAPTER.fetch(f"https://{HOST}/", FetchPolicy(), stand_in_api({FEED: body})))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a career site URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/", FetchPolicy(), _unused_send))


def test_every_position_is_a_posting_with_its_page_offices_and_ad(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "personio" / "feed.xml").read_bytes()
    fetched = asyncio.run(ADAPTER.fetch(f"https://{HOST}/", FetchPolicy(), stand_in_api({FEED: body})))

    found = candidates(ADAPTER, AdapterMatch(HOST, "listing"), fetched.bundle.body.decode())

    row = "adapter:personio:$['workzag-jobs'][0]['position'][{}]"
    assert found == {
        (row.format(0), "title"): "Synthetic Engineer",
        (row.format(0), "url"): f"https://{HOST}/job/9001",
        (
            row.format(0),
            "description",
        ): "<h2>Your role</h2><p>Build <strong>things</strong>.</p>\n<h2>Your profile</h2><p>Care.</p>",
        (row.format(0), "date_posted"): "2026-09-30T16:36:07+00:00",
        (row.format(0), "employment_type"): "full-time",
        (row.format(0), "locations"): ["Northtown", "Eastport"],
        (row.format(0), "identifier"): "9001",
        (row.format(0), "company"): "Example Co & Partners",
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "url"): f"https://{HOST}/job/9002",
        (row.format(1), "date_posted"): "2026-09-29T10:00:00+00:00",
        (row.format(1), "employment_type"): "part-time",
        (row.format(1), "locations"): ["Eastport"],
        (row.format(1), "identifier"): "9002",
    }
