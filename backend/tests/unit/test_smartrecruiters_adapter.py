"""The SmartRecruiters adapter: detect company career site URLs, fetch the Posting API's pages and a posting's answer,
read them as schema.org JobPostings. Hosts come from the adapter module (C3); companies and answers under
`tests/fixtures/smartrecruiters/` are synthetic."""

import asyncio
import json
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.smartrecruiters import API, PAGE_SIZE, SITE_HOST, SITE_HOSTS, SmartRecruiters
from tests.unit.adapter_support import FIXTURES, candidates

ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]  # `scripted_api` (conftest)

ADAPTER = SmartRecruiters()
COMPANY = "ExampleCo"
HOSTS = sorted(SITE_HOSTS)
companies = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(host=st.sampled_from(HOSTS), company=companies)
def test_a_company_url_is_a_listing_of_its_company(host: str, company: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{company}") == AdapterMatch(tenant=company, page_kind="listing")


@pytest.mark.parametrize(
    "url",
    [
        f"https://{SITE_HOST}.example.com/{COMPANY}",
        f"ftp://{SITE_HOST}/{COMPANY}",
        f"https://{SITE_HOST}/",
        f"https://{SITE_HOST}/..",
        f"https://{SITE_HOST}/{COMPANY}?search=x",  # a search of the list
        f"https://{SITE_HOST}/{COMPANY}/not-a-posting",
        f"https://{SITE_HOST}/{COMPANY}/123/apply",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def _postings(first: int, count: int, total: int) -> bytes:
    content = [{"id": str(i), "name": f"Job {i}"} for i in range(first, first + count)]
    return json.dumps({"offset": first, "limit": PAGE_SIZE, "totalFound": total, "content": content}).encode()


def test_a_company_list_is_paged_by_offset_until_the_total(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        offset = int(request.url.rsplit("offset=", 1)[1])
        return _postings(offset, min(PAGE_SIZE, 230 - offset), total=230)

    result = asyncio.run(ADAPTER.fetch(f"https://{SITE_HOST}/{COMPANY}", FetchPolicy(), scripted_api(answer, sent)))

    assert [r.url for r in sent] == [f"{API}/{COMPANY}/postings?limit={PAGE_SIZE}&offset={o}" for o in (0, 100, 200)]
    assert [p["id"] for p in json.loads(result.bundle.body)["content"]] == [str(i) for i in range(230)]
    assert ADAPTER.serves(AdapterMatch(COMPANY, "listing"), result.bundle.manifest.final_url) is True


def test_every_listed_posting_is_a_job_whose_page_is_under_its_company() -> None:
    body = (FIXTURES / "smartrecruiters" / "postings.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "listing"), body)

    row = "adapter:smartrecruiters:$['content'][{}]"
    assert found[(row.format(0), "url")] == f"https://{SITE_HOST}/{COMPANY}/1001"
    assert found[(row.format(1), "url")] == f"https://{SITE_HOST}/{COMPANY}/1002"
    assert found[(row.format(0), "title")] == "Synthetic Platform Engineer"
    assert found[(row.format(0), "date_posted")] == "2026-09-30T10:00:00.000Z"
    assert found[(row.format(0), "employment_type")] == "Full-time"
    assert found[(row.format(0), "locations")] == ["Northtown, Exampleland"]
    assert found[(row.format(0), "identifier")] == "1001"
    assert found[(row.format(0), "company")] == "Example Co"
    assert (row.format(0), "description") not in found  # the list carries no ad


def test_a_postings_description_is_its_ads_job_sections_in_page_order() -> None:
    body = (FIXTURES / "smartrecruiters" / "posting.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "detail", item="1001"), body)

    # The company's own section describes the hiring organization, not the job.
    assert found[("adapter:smartrecruiters:$", "description")] == (
        "<p>Build example platforms.</p>\n<h2>Qualifications</h2><p>Three years.</p>\n<h2>More</h2><p>Extra.</p>"
    )
