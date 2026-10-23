"""The Rippling adapter: detect hosted board URLs, fetch the board API's list and a job's answer, read them as
schema.org JobPostings. Hosts come from the adapter module (C3); boards and answers under
`tests/fixtures/rippling/` are synthetic."""

import asyncio

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.types import FetchPolicy
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.rippling import API, BOARD_HOST, Rippling
from tests.stand_in import StandInApi
from tests.unit.adapter_support import FIXTURES, candidates

ADAPTER = Rippling()
BOARD = "example-board"
JOB = "00000000-0000-4000-8000-0000000000b1"
boards = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(board=boards, path=st.sampled_from(["", "/jobs", "/jobs/"]))
def test_a_board_url_is_a_listing_of_its_board(board: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{board}{path}") == AdapterMatch(tenant=board, page_kind="listing")


@pytest.mark.parametrize(
    "url",
    [
        f"https://{BOARD_HOST}.example.com/{BOARD}/jobs",
        f"ftp://{BOARD_HOST}/{BOARD}/jobs",
        f"https://{BOARD_HOST}/",
        f"https://{BOARD_HOST}/../jobs",
        f"https://{BOARD_HOST}/{BOARD}/jobs?department=x",  # a filtered list
        f"https://{BOARD_HOST}/{BOARD}/jobs/not-a-uuid",
        f"https://{BOARD_HOST}/{BOARD}/jobs/{JOB}/apply",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_board_is_fetched_from_its_list(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "rippling" / "jobs.json").read_bytes()
    endpoint = f"{API}/{BOARD}/jobs"
    page = f"https://{BOARD_HOST}/{BOARD}/jobs"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({endpoint: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, endpoint)
    assert result.bundle.body == body


def test_every_listed_job_is_a_posting_with_its_page_and_location() -> None:
    body = (FIXTURES / "rippling" / "jobs.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(BOARD, "listing"), body)

    row = "adapter:rippling:$[{}]"
    assert found == {
        (row.format(0), "title"): " Synthetic Engineer ",
        (row.format(0), "url"): "https://ats.example.test/example-board/jobs/00000000-0000-4000-8000-0000000000b1",
        (row.format(0), "locations"): ["Northtown"],
        (row.format(0), "identifier"): "00000000-0000-4000-8000-0000000000b1",
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "url"): "https://ats.example.test/example-board/jobs/00000000-0000-4000-8000-0000000000b2",
        (row.format(1), "locations"): ["Remote (Exampleland)"],
        (row.format(1), "identifier"): "00000000-0000-4000-8000-0000000000b2",
    }
