"""The Rippling adapter: detect hosted board URLs, fetch the board API's list and a job's answer, read them as
schema.org JobPostings. Hosts come from the adapter module (C3); boards and answers under
`tests/fixtures/rippling/` are synthetic."""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.rippling import API, BOARD_HOST, Rippling
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = Rippling()
BOARD = "example-board"
JOB = "00000000-0000-4000-8000-0000000000b1"
boards = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(board=boards, path=st.sampled_from(["", "/jobs", "/jobs/"]))
def test_a_board_url_is_a_listing_of_its_board(board: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{board}{path}") == AdapterMatch(tenant=board, page_kind="listing")


@given(board=boards, job=st.uuids().map(str))
def test_a_job_url_is_a_detail_page_of_its_job(board: str, job: str) -> None:
    assert ADAPTER.detect(f"https://{BOARD_HOST}/{board}/jobs/{job}?x=1") == AdapterMatch(
        tenant=board, page_kind="detail", item=job
    )


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


def test_a_job_page_is_fetched_from_its_job_endpoint(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "rippling" / "job.json").read_bytes()
    endpoint = f"{API}/{BOARD}/jobs/{JOB}"

    result = asyncio.run(
        ADAPTER.fetch(f"https://{BOARD_HOST}/{BOARD}/jobs/{JOB}", FetchPolicy(), stand_in_api({endpoint: body}))
    )

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)
    assert ADAPTER.serves(AdapterMatch(BOARD, "detail", JOB), endpoint) is True
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), f"{API}/{BOARD}/jobs") is True
    assert ADAPTER.serves(AdapterMatch(BOARD, "listing"), f"{API}/{BOARD}-2/jobs") is False


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetching = ADAPTER.fetch("https://jobs.example.com/board/jobs", FetchPolicy(), _unused_send)
    with pytest.raises(ValueError, match="not a job board URL"):
        asyncio.run(fetching)


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


def test_a_job_answer_adds_its_description_date_type_and_pay() -> None:
    body = (FIXTURES / "rippling" / "job.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(BOARD, "detail", JOB), body)

    assert found == {
        ("adapter:rippling:$", "title"): " Synthetic Engineer ",
        (
            "adapter:rippling:$",
            "url",
        ): "https://ats.example.test/example-board/jobs/00000000-0000-4000-8000-0000000000b1",
        ("adapter:rippling:$", "description"): "<p>Build things.</p>",
        ("adapter:rippling:$", "date_posted"): "2026-09-30T16:36:07.947000-07:00",
        ("adapter:rippling:$", "employment_type"): "Salaried, full-time",
        ("adapter:rippling:$", "locations"): ["Northtown", "Eastport"],
        ("adapter:rippling:$", "identifier"): "00000000-0000-4000-8000-0000000000b1",
        ("adapter:rippling:$", "company"): "Example Co",
        ("adapter:rippling:$", "salary"): {
            "currency": "USD",
            "minValue": 100000.0,
            "maxValue": 150000.0,
            "unitText": "YEAR",
        },
    }
