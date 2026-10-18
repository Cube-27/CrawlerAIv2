"""The UKG Pro adapter: detect job board URLs, fetch the search API's pages (a POST with Top and Skip) and a job page's
embedded opportunity, read them as schema.org JobPostings. Hosts come from the adapter module (C3); answers under
`tests/fixtures/ukg/` are synthetic."""

import json

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.ukg import HOSTS, UltiPro
from tests.unit.adapter_support import candidates

ADAPTER = UltiPro()
HOST = sorted(HOSTS)[0]
COMPANY = "EXA1000EXC"
BOARD = "00000000-0000-4000-8000-0000000000a1"
OPPORTUNITY = "00000000-0000-4000-8000-0000000000d1"
BASE = f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}"
TENANT = f"{HOST}/{COMPANY}/{BOARD}"
companies = st.from_regex(r"[A-Za-z0-9]{1,20}", fullmatch=True)


@given(host=st.sampled_from(sorted(HOSTS)), company=companies, board=st.uuids().map(str))
def test_a_board_url_is_a_listing_of_its_board(host: str, company: str, board: str) -> None:
    expected = AdapterMatch(tenant=f"{host}/{company}/{board}", page_kind="listing")

    assert ADAPTER.detect(f"https://{host}/{company}/JobBoard/{board}") == expected
    assert ADAPTER.detect(f"https://{host}/{company}/JobBoard/{board}/?q=&o=postedDateDesc") == expected


def test_every_listed_opportunity_is_a_posting_whose_page_is_under_its_board() -> None:
    body = json.dumps(
        {
            "opportunities": [
                {
                    "Id": OPPORTUNITY,
                    "Title": "Synthetic Engineer",
                    "RequisitionNumber": "REQ0001",
                    "Locations": [{"LocalizedName": "Northtown"}, {"LocalizedName": "Eastport"}],
                    "PostedDate": "2026-09-30T10:00:00.000Z",
                    "BriefDescription": "Build things.",
                }
            ],
            "totalCount": 1,
        }
    )

    found = candidates(ADAPTER, AdapterMatch(TENANT, "listing"), body)

    row = "adapter:ukg:$['opportunities'][0]"
    assert found == {
        (row, "title"): "Synthetic Engineer",
        (row, "url"): f"{BASE}/OpportunityDetail?opportunityId={OPPORTUNITY}",
        (row, "description"): "Build things.",
        (row, "date_posted"): "2026-09-30T10:00:00.000Z",
        (row, "locations"): ["Northtown", "Eastport"],
        (row, "identifier"): "REQ0001",
    }
