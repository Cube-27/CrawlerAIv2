"""The UKG Pro adapter: detect job board URLs, fetch the search API's pages (a POST with Top and Skip) and a job page's
embedded opportunity, read them as schema.org JobPostings. Hosts come from the adapter module (C3); answers under
`tests/fixtures/ukg/` are synthetic."""

import asyncio
import json
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from crawlerai.adapters.ukg import HOSTS, PAGE_SIZE, UltiPro
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)
ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]  # `scripted_api` (conftest)

ADAPTER = UltiPro()
HOST = sorted(HOSTS)[0]
COMPANY = "EXA1000EXC"
BOARD = "00000000-0000-4000-8000-0000000000a1"
OPPORTUNITY = "00000000-0000-4000-8000-0000000000d1"
BASE = f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}"
TENANT = f"{HOST}/{COMPANY}/{BOARD}"
SEARCH = f"{BASE}/JobBoardView/LoadSearchResults"
companies = st.from_regex(r"[A-Za-z0-9]{1,20}", fullmatch=True)


@given(host=st.sampled_from(sorted(HOSTS)), company=companies, board=st.uuids().map(str))
def test_a_board_url_is_a_listing_of_its_board(host: str, company: str, board: str) -> None:
    expected = AdapterMatch(tenant=f"{host}/{company}/{board}", page_kind="listing")

    assert ADAPTER.detect(f"https://{host}/{company}/JobBoard/{board}") == expected
    assert ADAPTER.detect(f"https://{host}/{company}/JobBoard/{board}/?q=&o=postedDateDesc") == expected


@given(company=companies, board=st.uuids().map(str), job=st.uuids().map(str))
def test_an_opportunity_url_is_a_detail_page_of_its_opportunity(company: str, board: str, job: str) -> None:
    url = f"https://{HOST}/{company}/JobBoard/{board}/OpportunityDetail?opportunityId={job}"

    assert ADAPTER.detect(url) == AdapterMatch(tenant=f"{HOST}/{company}/{board}", page_kind="detail", item=job)


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/{COMPANY}/JobBoard/{BOARD}",
        f"ftp://{HOST}/{COMPANY}/JobBoard/{BOARD}",
        f"https://{HOST}/{COMPANY}/JobBoard",
        f"https://{HOST}/{COMPANY}/JobBoard/not-a-uuid",
        f"https://{HOST}/{COMPANY}/Other/{BOARD}",
        f"https://{HOST}/../JobBoard/{BOARD}",
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}?q=engineer",  # a search of the list
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}?w=remote",  # a filtered list
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}/OpportunityDetail",
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}/OpportunityDetail?opportunityId=1",
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}/OpportunityDetail?opportunityId={OPPORTUNITY}&x=1",
        f"https://{HOST}/{COMPANY}/JobBoard/{BOARD}/Elsewhere",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def _search(first: int, count: int, total: int) -> bytes:
    rows = [{"Id": f"id-{i}", "Title": f"Job {i}"} for i in range(first, first + count)]
    return json.dumps({"opportunities": rows, "totalCount": total}).encode()


def test_a_board_list_is_paged_by_top_and_skip_until_the_total(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []
    total = PAGE_SIZE * 2 + 7

    def answer(request: JsonRequest) -> bytes:
        search = json.loads(request.body or "")["opportunitySearch"]
        return _search(search["Skip"], min(search["Top"], total - search["Skip"]), total)

    result = asyncio.run(ADAPTER.fetch(BASE, FetchPolicy(), scripted_api(answer, sent)))

    assert {(r.method, r.url, r.headers) for r in sent} == {
        ("POST", SEARCH, (("Content-Type", "application/json; charset=utf-8"),))
    }
    assert [json.loads(r.body or "")["opportunitySearch"]["Skip"] for r in sent] == [0, PAGE_SIZE, PAGE_SIZE * 2]
    assert all(json.loads(r.body or "")["opportunitySearch"]["Top"] == PAGE_SIZE for r in sent)
    assert [o["Id"] for o in json.loads(result.bundle.body)["opportunities"]] == [f"id-{i}" for i in range(total)]
    assert ADAPTER.serves(AdapterMatch(TENANT, "listing"), result.bundle.manifest.final_url) is True


def test_a_board_with_no_opportunity_does_not_serve_the_page(stand_in_api: StandInApi) -> None:
    send = stand_in_api({SEARCH: _search(0, 0, total=0)})

    result = asyncio.run(ADAPTER.fetch(BASE, FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


def test_an_opportunity_page_is_recorded_as_the_object_it_embeds(scripted_api: ScriptedApi) -> None:
    html = (FIXTURES / "ukg" / "detail.html").read_bytes()
    sent: list[JsonRequest] = []
    page = f"{BASE}/OpportunityDetail?opportunityId={OPPORTUNITY}"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), scripted_api(lambda _: html, sent)))

    assert [(r.method, r.url, r.raw, r.headers) for r in sent] == [("GET", page, True, (("Accept", "text/html"),))]
    embedded = json.loads(result.bundle.body)
    assert (result.block_class, embedded["Id"], embedded["Description"]) == (
        "ok",
        OPPORTUNITY,
        '<p>Build {things} and "more".</p>',
    )
    assert ADAPTER.serves(AdapterMatch(TENANT, "detail", OPPORTUNITY), page) is True
    assert (
        ADAPTER.serves(AdapterMatch(TENANT, "detail", OPPORTUNITY), f"{BASE}-2/OpportunityDetail?opportunityId=1")
        is False
    )


@pytest.mark.parametrize(
    "html",
    [
        b"<html><body>nothing here</body></html>",
        b"<script>new US.Opportunity.CandidateOpportunityDetail({broken);</script>",
        b"<script>new US.Opportunity.CandidateOpportunityDetail([1, 2]);</script>",
    ],
)
def test_a_page_that_embeds_no_opportunity_is_not_served(scripted_api: ScriptedApi, html: bytes) -> None:
    page = f"{BASE}/OpportunityDetail?opportunityId={OPPORTUNITY}"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), scripted_api(lambda _: html, [])))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a job board URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/board", FetchPolicy(), _unused_send))


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


def test_an_opportunity_answer_adds_its_description_and_annual_pay() -> None:
    html = (FIXTURES / "ukg" / "detail.html").read_text(encoding="utf-8")
    embedded = json.dumps(json.JSONDecoder().raw_decode(html, html.index("({") + 1)[0])

    found = candidates(ADAPTER, AdapterMatch(TENANT, "detail", OPPORTUNITY), embedded)

    assert found == {
        ("adapter:ukg:$", "title"): "Synthetic Engineer",
        ("adapter:ukg:$", "description"): '<p>Build {things} and "more".</p>',
        ("adapter:ukg:$", "date_posted"): "2026-09-30T10:00:00.000Z",
        ("adapter:ukg:$", "locations"): ["Northtown, Exampleland", "Remote"],
        ("adapter:ukg:$", "identifier"): "REQ0001",
        ("adapter:ukg:$", "salary"): {"currency": "USD", "minValue": 100000.0, "maxValue": 150000.0},
    }
