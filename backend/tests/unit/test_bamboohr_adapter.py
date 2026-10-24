"""The BambooHR adapter: detect career site URLs, fetch the careers list and a job's answer, read them as schema.org
JobPostings. Hosts come from the adapter module (C3); answers under `tests/fixtures/bamboohr/` are synthetic."""

import asyncio

from hypothesis import given
from hypothesis import strategies as st

from snowcrawl.acquire.types import FetchPolicy
from snowcrawl.adapters.bamboohr import DOMAIN, BambooHR
from snowcrawl.adapters.base import AdapterMatch
from tests.stand_in import StandInApi
from tests.unit.adapter_support import FIXTURES, candidates

ADAPTER = BambooHR()
COMPANY = "example-co"
API = f"https://{COMPANY}.{DOMAIN}/careers"
labels = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?", fullmatch=True)


@given(company=labels, path=st.sampled_from(["/careers", "/careers/"]))
def test_a_careers_url_is_a_listing_of_its_company(company: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{company}.{DOMAIN}{path}") == AdapterMatch(tenant=company, page_kind="listing")


@given(company=labels, job=st.integers(1, 10**9))
def test_a_job_url_is_a_detail_page_of_its_job(company: str, job: int) -> None:
    assert ADAPTER.detect(f"https://{company}.{DOMAIN}/careers/{job}?x=1") == AdapterMatch(
        tenant=company, page_kind="detail", item=str(job)
    )


def test_a_list_page_is_fetched_from_the_careers_list(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "bamboohr" / "list.json").read_bytes()
    page = f"https://{COMPANY}.{DOMAIN}/careers"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({f"{API}/list": body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == (
        "api",
        "ok",
        page,
        f"{API}/list",
    )
    assert result.bundle.body == body
    assert ADAPTER.serves(AdapterMatch(COMPANY, "listing"), f"{API}/list") is True
    assert ADAPTER.serves(AdapterMatch(COMPANY, "listing"), f"https://other.{DOMAIN}/careers/list") is False


def test_a_job_page_is_fetched_from_its_detail_endpoint(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "bamboohr" / "detail.json").read_bytes()
    endpoint = f"{API}/7/detail"

    result = asyncio.run(
        ADAPTER.fetch(f"https://{COMPANY}.{DOMAIN}/careers/7", FetchPolicy(), stand_in_api({endpoint: body}))
    )

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)


def test_every_listed_job_is_a_posting_with_its_page_and_place() -> None:
    body = (FIXTURES / "bamboohr" / "list.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "listing"), body)

    row = "adapter:bamboohr:$['result'][{}]"
    assert found == {
        (row.format(0), "title"): "Synthetic Engineer",
        (row.format(0), "url"): f"{API}/7",
        (row.format(0), "employment_type"): "Full-Time",
        (row.format(0), "locations"): [{"address": {"addressLocality": "Northtown", "addressRegion": "Exampleland"}}],
        (row.format(0), "identifier"): "7",
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "url"): f"{API}/8",
        (row.format(1), "employment_type"): "Part-Time",
        (row.format(1), "locations"): [{"address": {"addressLocality": "Eastport", "addressCountry": "Exampleland"}}],
        (row.format(1), "identifier"): "8",
    }
