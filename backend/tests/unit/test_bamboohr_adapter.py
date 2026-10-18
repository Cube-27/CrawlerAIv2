"""The BambooHR adapter: detect career site URLs, fetch the careers list and a job's answer, read them as schema.org
JobPostings. Hosts come from the adapter module (C3); answers under `tests/fixtures/bamboohr/` are synthetic."""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.bamboohr import DOMAIN, BambooHR
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

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


@pytest.mark.parametrize(
    "url",
    [
        f"https://{COMPANY}.{DOMAIN}.example.com/careers",
        f"https://{DOMAIN}/careers",
        f"https://{COMPANY}.{COMPANY}.{DOMAIN}/careers",
        f"ftp://{COMPANY}.{DOMAIN}/careers",
        f"https://{COMPANY}.{DOMAIN}/",
        f"https://{COMPANY}.{DOMAIN}/careers?department=x",  # a filtered list
        f"https://{COMPANY}.{DOMAIN}/careers/not-a-job",
        f"https://{COMPANY}.{DOMAIN}/careers/7/apply",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


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


def test_a_company_without_a_careers_site_is_not_served(stand_in_api: StandInApi) -> None:
    # Such a company's list endpoint redirects to the platform's own site: an HTML page, not JSON.
    send = stand_in_api({f"{API}/list": b"<!doctype html><title>Platform</title>"})

    result = asyncio.run(ADAPTER.fetch(f"https://{COMPANY}.{DOMAIN}/careers", FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


def test_a_company_with_an_empty_list_is_not_served(stand_in_api: StandInApi) -> None:
    send = stand_in_api({f"{API}/list": b'{"meta": {"totalCount": 0}, "result": []}'})

    result = asyncio.run(ADAPTER.fetch(f"https://{COMPANY}.{DOMAIN}/careers", FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetching = ADAPTER.fetch("https://jobs.example.com/careers", FetchPolicy(), _unused_send)
    with pytest.raises(ValueError, match="not a career site URL"):
        asyncio.run(fetching)


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


def test_a_detail_answer_adds_its_description_date_and_pay_text() -> None:
    body = (FIXTURES / "bamboohr" / "detail.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "detail", "7"), body)

    job = "adapter:bamboohr:$['result']['jobOpening']"
    assert found == {
        (job, "title"): "Synthetic Engineer",
        (job, "url"): "https://example-co.careers.example.test/careers/7",
        (job, "description"): "<p>Build things.</p>",
        (job, "date_posted"): "2026-09-30",
        (job, "employment_type"): "Full-Time",
        (job, "locations"): [
            {
                "address": {
                    "addressLocality": "Northtown",
                    "addressRegion": "Exampleland",
                    "postalCode": "00000",
                    "addressCountry": "Exampleland",
                }
            }
        ],
        (job, "salary"): "$100,000 - $150,000 a year",
    }
