"""The Ashby adapter: detect hosted board URLs, fetch the Job Postings API's list with compensation, read it as
schema.org JobPostings. Hosts come from the adapter module (C3); boards and answers under `tests/fixtures/ashby/` are
synthetic."""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.ashby import API, BOARD_HOST, Ashby
from crawlerai.adapters.base import AdapterMatch
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = Ashby()
BOARD = "example-board"
ENDPOINT = f"{API}/{BOARD}?includeCompensation=true"
boards = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(board=boards)
def test_a_board_url_is_a_listing_of_its_board(board: str) -> None:
    expected = AdapterMatch(tenant=board, page_kind="listing")
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{board}") == expected
    assert ADAPTER.detect(f"http://{BOARD_HOST.upper()}/{board}/") == expected


@pytest.mark.parametrize(
    "url",
    [
        f"https://{BOARD_HOST}.example.com/{BOARD}",
        f"ftp://{BOARD_HOST}/{BOARD}",
        f"https://{BOARD_HOST}/",
        f"https://{BOARD_HOST}/..",
        f"https://{BOARD_HOST}/{BOARD}?departmentId=1",  # a filtered list
        f"https://{BOARD_HOST}/{BOARD}/00000000-0000-4000-8000-0000000000a1",  # the API has no posting endpoint
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_board_is_fetched_from_its_list_with_compensation(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "ashby" / "board.json").read_bytes()
    page = f"https://{BOARD_HOST}/{BOARD}"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({ENDPOINT: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, ENDPOINT)
    assert result.bundle.body == body
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), ENDPOINT) is True
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), f"{API}/{BOARD}-2?includeCompensation=true") is False


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a job board URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/board", FetchPolicy(), _unused_send))


def test_every_listed_posting_is_a_job_with_its_stated_fields() -> None:
    body = (FIXTURES / "ashby" / "board.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(BOARD, "listing"), body)

    first, second = "adapter:ashby:$['jobs'][0]", "adapter:ashby:$['jobs'][1]"
    assert found[(first, "title")] == " Synthetic Platform Engineer"
    assert found[(first, "url")] == "https://jobs.example.test/example-board/00000000-0000-4000-8000-0000000000a1"
    assert found[(first, "description")] == "<p>Build example platforms.</p>"
    assert found[(first, "date_posted")] == "2026-09-30T10:00:00.000+00:00"
    assert found[(first, "employment_type")] == "FullTime"
    assert found[(first, "locations")] == ["Northtown", "Remote (Exampleland)"]  # the primary, then the others
    assert found[(first, "identifier")] == "00000000-0000-4000-8000-0000000000a1"
    assert found[(second, "locations")] == ["Eastport"]


def test_only_a_compensation_component_with_an_amount_is_a_salary() -> None:
    body = (FIXTURES / "ashby" / "board.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(BOARD, "listing"), body)

    assert found[("adapter:ashby:$['jobs'][0]", "salary")] == {
        "currency": "USD",
        "minValue": 100000,
        "maxValue": 150000,
        "unitText": "YEAR",
    }
    # The second posting lists equity alone, which states no amount.
    assert ("adapter:ashby:$['jobs'][1]", "salary") not in found
