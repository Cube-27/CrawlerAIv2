"""The Workable adapter: detect hosted board URLs, fetch the widget API's list with details, read it as schema.org
JobPostings. Hosts come from the adapter module (C3); accounts and answers under `tests/fixtures/workable/` are
synthetic."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.workable import BOARD_HOST, Workable
from tests.unit.adapter_support import FIXTURES, candidates

ADAPTER = Workable()
ACCOUNT = "example-account"
accounts = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(account=accounts)
def test_an_account_url_is_a_listing_of_its_account(account: str) -> None:
    expected = AdapterMatch(tenant=account, page_kind="listing")
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{account}") == expected
    assert ADAPTER.detect(f"http://{BOARD_HOST.upper()}/{account}/") == expected


@pytest.mark.parametrize(
    "url",
    [
        f"https://{BOARD_HOST}.example.com/{ACCOUNT}",
        f"ftp://{BOARD_HOST}/{ACCOUNT}",
        f"https://{BOARD_HOST}/",
        f"https://{BOARD_HOST}/..",
        f"https://{BOARD_HOST}/{ACCOUNT}?query=x",  # a search of the list
        f"https://{BOARD_HOST}/j/ABCDEF1234",  # a job's page takes the page rungs
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_every_listed_job_is_a_posting_whose_places_state_their_address_parts() -> None:
    body = (FIXTURES / "workable" / "widget.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(ACCOUNT, "listing"), body)

    first, second = "adapter:workable:$['jobs'][0]", "adapter:workable:$['jobs'][1]"
    assert found[(first, "title")] == "Synthetic Engineer"
    assert found[(first, "url")] == "https://jobs.example.test/j/AAA111"
    assert found[(first, "description")] == "<p>Synthetic Engineer duties.</p>"
    assert found[(first, "date_posted")] == "2026-09-30"
    assert found[(first, "employment_type")] == "Full-time"
    assert found[(first, "identifier")] == "AAA111"
    assert found[(first, "locations")] == [
        {"address": {"addressLocality": "Northtown", "addressRegion": "North Region", "addressCountry": "Exampleland"}}
    ]
    assert found[(second, "locations")] == [
        {"address": {"addressLocality": "Eastport", "addressRegion": "East Region", "addressCountry": "Exampleland"}},
        {"address": {"addressLocality": "Westham", "addressRegion": "", "addressCountry": "Otherland"}},
    ]
