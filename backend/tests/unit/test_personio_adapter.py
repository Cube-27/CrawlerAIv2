"""The Personio adapter: detect career site URLs, fetch the XML feed (read into JSON by the bounded XML reader), read it
as schema.org JobPostings. Hosts come from the adapter module (C3); the feed under `tests/fixtures/personio/` is
synthetic."""

import asyncio

import pytest
from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.acquire.types import FetchPolicy
from snowcrawl.adapters.base import AdapterMatch
from snowcrawl.adapters.personio import DOMAINS, Personio
from tests.stand_in import StandInApi
from tests.unit.adapter_support import FIXTURES, candidates

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
