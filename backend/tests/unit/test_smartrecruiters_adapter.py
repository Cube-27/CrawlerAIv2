"""The SmartRecruiters adapter: detect company career site URLs, fetch the Posting API's pages and a posting's answer,
read them as schema.org JobPostings. Hosts come from the adapter module (C3); companies and answers under
`tests/fixtures/smartrecruiters/` are synthetic."""

import asyncio
import json
from collections.abc import Callable, Mapping

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from crawlerai.adapters.smartrecruiters import API, PAGE_SIZE, SITE_HOST, SITE_HOSTS, SmartRecruiters
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)
ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]  # `scripted_api` (conftest)

ADAPTER = SmartRecruiters()
COMPANY = "ExampleCo"
HOSTS = sorted(SITE_HOSTS)
companies = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))


@given(host=st.sampled_from(HOSTS), company=companies)
def test_a_company_url_is_a_listing_of_its_company(host: str, company: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{company}") == AdapterMatch(tenant=company, page_kind="listing")


@given(
    host=st.sampled_from(HOSTS), company=companies, posting=st.integers(1, 10**15), slug=st.sampled_from(["", "-a-b"])
)
def test_a_posting_url_is_a_detail_page_of_its_posting_id(host: str, company: str, posting: int, slug: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{company}/{posting}{slug}?x=1") == AdapterMatch(
        tenant=company, page_kind="detail", item=str(posting)
    )


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


def test_the_requests_row_target_bounds_the_pages(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        return _postings(int(request.url.rsplit("offset=", 1)[1]), PAGE_SIZE, total=5000)

    asyncio.run(ADAPTER.fetch(f"https://{SITE_HOST}/{COMPANY}", FetchPolicy(max_rows=100), scripted_api(answer, sent)))

    assert len(sent) == 1


def test_a_company_with_no_postings_does_not_serve_the_page(stand_in_api: StandInApi) -> None:
    endpoint = f"{API}/{COMPANY}/postings?limit={PAGE_SIZE}&offset=0"
    send = stand_in_api({endpoint: _postings(0, 0, total=0)})

    result = asyncio.run(ADAPTER.fetch(f"https://{SITE_HOST}/{COMPANY}", FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


def test_a_posting_page_is_fetched_from_its_posting_endpoint(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "smartrecruiters" / "posting.json").read_bytes()
    endpoint = f"{API}/{COMPANY}/postings/1001"

    result = asyncio.run(
        ADAPTER.fetch(f"https://{SITE_HOST}/{COMPANY}/1001-synthetic", FetchPolicy(), stand_in_api({endpoint: body}))
    )

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)
    assert ADAPTER.serves(AdapterMatch(COMPANY, "detail", "1001"), endpoint) is True
    assert ADAPTER.serves(AdapterMatch(COMPANY, "detail", "1001"), f"{API}/{COMPANY}2/postings/1001") is False


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a career site URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/company", FetchPolicy(), _unused_send))


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


def test_a_posting_answer_is_one_job_with_its_ad() -> None:
    body = (FIXTURES / "smartrecruiters" / "posting.json").read_text(encoding="utf-8")

    found = candidates(ADAPTER, AdapterMatch(COMPANY, "detail", "1001"), body)

    assert found[("adapter:smartrecruiters:$", "url")] == (
        "https://jobs.example.test/ExampleCo/1001-synthetic-platform-engineer"
    )
    assert found[("adapter:smartrecruiters:$", "description")] == "<p>Build example platforms.</p>"
    assert found[("adapter:smartrecruiters:$", "identifier")] == "1001"
