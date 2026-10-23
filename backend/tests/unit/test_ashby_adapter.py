"""The Ashby adapter: detect hosted board URLs, fetch the Job Postings API's list with compensation, read it as
schema.org JobPostings. Hosts come from the adapter module (C3); boards and answers under `tests/fixtures/ashby/` are
synthetic."""

import asyncio

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.types import FetchPolicy
from crawlerai.adapters.ashby import API, BOARD_HOST, Ashby
from crawlerai.adapters.base import AdapterMatch
from tests.stand_in import StandInApi
from tests.unit.adapter_support import FIXTURES, candidates

ADAPTER = Ashby()
BOARD = "example-board"
ENDPOINT = f"{API}/{BOARD}?includeCompensation=true"
boards = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(board=boards)
def test_a_board_url_is_a_listing_of_its_board(board: str) -> None:
    expected = AdapterMatch(tenant=board, page_kind="listing")
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{board}") == expected
    assert ADAPTER.detect(f"http://{BOARD_HOST.upper()}/{board}/") == expected


def test_a_board_is_fetched_from_its_list_with_compensation(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "ashby" / "board.json").read_bytes()
    page = f"https://{BOARD_HOST}/{BOARD}"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({ENDPOINT: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, ENDPOINT)
    assert result.bundle.body == body
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), ENDPOINT) is True
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), f"{API}/{BOARD}-2?includeCompensation=true") is False


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
