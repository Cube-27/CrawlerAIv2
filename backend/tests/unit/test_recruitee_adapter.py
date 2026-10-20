"""The Recruitee adapter: detect company career site URLs, fetch the offers API, read it as schema.org JobPostings.
The platform's domain comes from the adapter module (C3); companies and answers under `tests/fixtures/recruitee/` are
synthetic."""

import asyncio
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.recruitee import DOMAIN, Recruitee
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = Recruitee()
COMPANY = "example-company"
HOST = f"{COMPANY}.{DOMAIN}"
API = f"https://{HOST}/api/offers"
companies = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?", fullmatch=True)


@given(company=companies, path=st.sampled_from(["", "/", "/o", "/o/"]))
def test_a_company_site_url_is_a_listing_of_its_company(company: str, path: str) -> None:
    assert ADAPTER.detect(f"https://{company}.{DOMAIN}{path}") == AdapterMatch(tenant=company, page_kind="listing")


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/",
        f"https://a.{HOST}/",
        f"https://{DOMAIN}/",  # no company
        f"ftp://{HOST}/",
        f"https://{HOST}/?department=1",  # a filtered list
        f"https://{HOST}/o/..",
        f"https://{HOST}/o/offer/c/new",  # the application form
        f"https://{HOST}/about",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_company_page_is_fetched_from_its_offers_list(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "recruitee" / "offers.json").read_bytes()
    page = f"https://{HOST}/"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), stand_in_api({f"{API}/": body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == (
        "api",
        "ok",
        page,
        f"{API}/",
    )
    assert result.bundle.body == body


def test_every_listed_offer_is_a_job_with_its_stated_fields() -> None:
    body = (FIXTURES / "recruitee" / "offers.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "listing"), body)

    first = "adapter:recruitee:$['offers'][0]"
    assert found[(first, "title")] == "Synthetic Engineer"
    assert found[(first, "url")] == "https://careers.example.test/o/synthetic-engineer"
    # The page shows the requirements after the description.
    assert found[(first, "description")] == "<p>Do Synthetic Engineer.</p>\n<p>Req.</p>"
    assert found[(first, "date_posted")] == "2026-09-30 10:00:00 UTC"
    assert found[(first, "employment_type")] == "fulltime_permanent"
    assert found[(first, "locations")] == ["Northtown, Exampleland"]
    assert found[(first, "identifier")] == "g1"
    assert found[(first, "company")] == "Example Co"
    assert found[(first, "salary")] == {"currency": "EUR", "minValue": "60000", "maxValue": "80000", "unitText": "year"}
    # An offer whose salary states no amount has no salary.
    assert ("adapter:recruitee:$['offers'][1]", "salary") not in found
