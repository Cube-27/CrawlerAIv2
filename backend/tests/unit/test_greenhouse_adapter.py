"""The Greenhouse adapter: detect board URLs, fetch the Job Board API's JSON, name its endpoints.

Greenhouse is a multi-tenant platform, not a site (C6, C9). Its hosts come from the adapter module, so no hostname is
written here (C3). Tenants and the recorded API responses under `tests/fixtures/greenhouse/` are synthetic.
"""

import asyncio
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.acquire.types import FetchPolicy
from snowcrawl.adapters.base import AdapterMatch
from snowcrawl.adapters.greenhouse import API, BOARD_HOSTS, Greenhouse
from tests.stand_in import StandInApi

FIXTURES = Path(__file__).parents[1] / "fixtures" / "greenhouse"
HOST = sorted(BOARD_HOSTS)[0]
TENANT = "example-tenant"

tokens = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda t: t.strip(".") and t != "embed")


ADAPTER = Greenhouse()


@given(host=st.sampled_from(sorted(BOARD_HOSTS)), token=tokens, scheme=st.sampled_from(["http", "https"]))
def test_a_board_url_is_a_listing_of_its_tenant_on_its_host(host: str, token: str, scheme: str) -> None:
    expected = AdapterMatch(tenant=token, page_kind="listing", host=host)
    assert ADAPTER.detect(f"{scheme}://{host}/{token}") == expected
    assert ADAPTER.detect(f"{scheme}://{host.upper()}/{token}/") == expected


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
