"""The Greenhouse adapter (SPEC-02 §4.9): detect board URLs, fetch the Job Board API's JSON, name its endpoints.

Greenhouse is a multi-tenant platform, not a site (C6, C9). Its hosts come from the adapter module, so no hostname is
written here (C3). Tenants and the recorded API responses under `tests/fixtures/greenhouse/` are synthetic.
"""

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.greenhouse import API, BOARD_HOSTS, Greenhouse

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "greenhouse"
HOST = sorted(BOARD_HOSTS)[0]
TENANT = "example-tenant"

tokens = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda t: t.strip(".") and t != "embed")
job_ids = st.integers(min_value=1, max_value=10**12).map(str)


ADAPTER = Greenhouse()


@given(host=st.sampled_from(sorted(BOARD_HOSTS)), token=tokens, scheme=st.sampled_from(["http", "https"]))
def test_a_board_url_is_a_listing_of_its_tenant_on_its_host(host: str, token: str, scheme: str) -> None:
    expected = AdapterMatch(tenant=token, page_kind="listing", host=host)
    assert ADAPTER.detect(f"{scheme}://{host}/{token}") == expected
    assert ADAPTER.detect(f"{scheme}://{host.upper()}/{token}/") == expected


@given(host=st.sampled_from(sorted(BOARD_HOSTS)), token=tokens, job_id=job_ids)
def test_a_job_url_is_a_detail_page_of_its_job(host: str, token: str, job_id: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{token}/jobs/{job_id}?source=x#apply") == AdapterMatch(
        tenant=token, page_kind="detail", item=job_id, host=host
    )


@given(token=tokens, job_id=job_ids)
def test_embedded_boards_and_jobs_are_detected_from_their_query(token: str, job_id: str) -> None:
    assert ADAPTER.detect(f"https://{HOST}/embed/job_board?for={token}") == AdapterMatch(token, "listing")
    assert ADAPTER.detect(f"https://{HOST}/embed/job_app?for={token}&token={job_id}") == AdapterMatch(
        token, "detail", job_id
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/{TENANT}",  # a board host's name inside another host
        f"ftp://{HOST}/{TENANT}",
        f"https://{HOST}/",  # no tenant
        f"https://{HOST}/{TENANT}/jobs/not-a-number",
        f"https://{HOST}/{TENANT}/jobs/1/extra",
        f"https://{HOST}/..",  # a dot-segment would move the API path
        f"https://{HOST}/embed/job_board",  # no `for`
        f"https://{HOST}/embed/job_board?for=a&for=b",  # two tenants
        f"https://{HOST}/embed/job_app?for={TENANT}",  # no job token
        f"https://{HOST}/embed/job_app?for={TENANT}&token=x",
        f"https://{HOST}/embed/other?for={TENANT}",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_job_page_is_fetched_from_the_retrieve_job_endpoint(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "job.json").read_bytes()
    endpoint = f"{API}/{TENANT}/jobs/4000001"
    page = f"https://{HOST}/{TENANT}/jobs/4000001"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({endpoint: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, endpoint)
    assert result.bundle.body == body


def test_a_board_page_is_fetched_from_the_list_jobs_endpoint_with_content(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "jobs.json").read_bytes()
    endpoint = f"{API}/{TENANT}/jobs?content=true"

    result = asyncio.run(ADAPTER.fetch(f"https://{HOST}/{TENANT}", FetchPolicy(), stand_in_api({endpoint: body})))

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetch = ADAPTER.fetch("https://jobs.example.com/board", FetchPolicy(), _unused_send)
    with pytest.raises(ValueError, match="not a job board URL"):
        asyncio.run(fetch)


def test_it_serves_the_endpoints_it_fetches_and_no_page() -> None:
    board = AdapterMatch(tenant="example-tenant", page_kind="listing")
    assert ADAPTER.serves(board, f"{API}/example-tenant/jobs") is True
    assert ADAPTER.serves(board, f"{API}/example-tenant/jobs/12") is True
    assert ADAPTER.serves(board, f"{API}/other-tenant/jobs") is False
    assert ADAPTER.serves(board, f"{API}/example-tenant-2/jobs") is False
    assert ADAPTER.serves(board, f"https://{HOST}/example-tenant") is False
