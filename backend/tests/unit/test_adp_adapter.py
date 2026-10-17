"""The ADP Workforce Now adapter: detect career center URLs (company and center ids from the query), fetch the
requisition list, and for a job page the requisition whose external id the URL names. Hosts come from the adapter
module (C3); answers under `tests/fixtures/adp/` are synthetic."""

import asyncio
import json
from collections.abc import Callable, Mapping
from urllib.parse import urlencode

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.adp import ADP, API, HOST, PAGE_PATH
from crawlerai.adapters.base import NOT_SERVED, AdapterMatch
from tests.unit.adapter_support import FIXTURES, candidates

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)

ADAPTER = ADP()
CID = "00000000-0000-4000-8000-0000000000e1"
CC_ID = "19000101_000001"
TENANT = f"{CID}|{CC_ID}|en_US"
LIST = f"{API}?cid={CID}&ccId={CC_ID}&lang=en_US&locale=en_US"
ITEM = "5000000000001_1"
PAGE_URL = f"https://{HOST}{PAGE_PATH}?cid={CID}&ccId={CC_ID}&lang=en_US&jobId="


def _page(**extra: str) -> str:
    return f"https://{HOST}{PAGE_PATH}?" + urlencode({"cid": CID, "ccId": CC_ID, "lang": "en_US", **extra})


@given(cid=st.uuids().map(str), day=st.integers(10**7, 10**8 - 1), seq=st.integers(0, 999999))
def test_a_career_center_url_is_a_listing_of_its_company_and_center(cid: str, day: int, seq: int) -> None:
    url = f"https://{HOST}{PAGE_PATH}?cid={cid}&ccId={day}_{seq:06d}&lang=en_US&selectedMenuKey=CurrentOpenings"

    assert ADAPTER.detect(url) == AdapterMatch(tenant=f"{cid}|{day}_{seq:06d}|en_US", page_kind="listing")


def test_a_job_id_makes_a_detail_page_and_a_missing_language_stays_missing() -> None:
    url = f"https://{HOST}{PAGE_PATH}?cid={CID}&ccId={CC_ID}&jobId=555001"

    assert ADAPTER.detect(url) == AdapterMatch(tenant=f"{CID}|{CC_ID}|", page_kind="detail", item="555001")


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com{PAGE_PATH}?cid={CID}&ccId={CC_ID}",
        f"ftp://{HOST}{PAGE_PATH}?cid={CID}&ccId={CC_ID}",
        f"https://{HOST}/other.html?cid={CID}&ccId={CC_ID}",
        f"https://{HOST}{PAGE_PATH}",
        f"https://{HOST}{PAGE_PATH}?cid={CID}",
        f"https://{HOST}{PAGE_PATH}?cid=not-a-uuid&ccId={CC_ID}",
        f"https://{HOST}{PAGE_PATH}?cid={CID}&ccId=x",
        f"https://{HOST}{PAGE_PATH}?cid={CID}&ccId={CC_ID}&lang=../x",
        f"https://{HOST}{PAGE_PATH}?cid={CID}&ccId={CC_ID}&jobId=a/b",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def test_a_career_center_is_fetched_from_its_requisition_list(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "adp" / "list.json").read_bytes()

    result = asyncio.run(ADAPTER.fetch(_page(), FetchPolicy(), stand_in_api({LIST: body})))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", _page(), LIST)
    requisitions = json.loads(result.bundle.body)["jobRequisitions"]
    assert [r["externalJobID"] for r in requisitions] == ["555001", "555002"]  # recorded with the id the page names
    assert requisitions[0]["requisitionTitle"] == json.loads(body)["jobRequisitions"][0]["requisitionTitle"]
    assert ADAPTER.serves(AdapterMatch(TENANT, "listing"), LIST) is True
    assert ADAPTER.serves(AdapterMatch(TENANT, "listing"), LIST.replace(CID, CID[:-1] + "2")) is False


def test_a_job_page_is_fetched_from_the_requisition_its_external_id_names(stand_in_api: StandInApi) -> None:
    routes = {
        LIST: (FIXTURES / "adp" / "list.json").read_bytes(),
        f"{API}/{ITEM}?cid={CID}&ccId={CC_ID}&lang=en_US&locale=en_US": (FIXTURES / "adp" / "detail.json").read_bytes(),
    }

    result = asyncio.run(ADAPTER.fetch(_page(jobId="555001"), FetchPolicy(), stand_in_api(routes)))

    assert (result.block_class, result.bundle.manifest.final_url) == ("ok", f"{API}/{ITEM}?{LIST.split('?')[1]}")
    answer = json.loads(result.bundle.body)
    assert (answer["itemID"], answer["externalJobID"]) == (ITEM, "555001")
    assert len(result.attempts) == 2  # the list and the requisition
    assert ADAPTER.serves(AdapterMatch(TENANT, "detail", "555001"), result.bundle.manifest.final_url) is True


def test_a_job_id_no_requisition_states_is_not_served(stand_in_api: StandInApi) -> None:
    send = stand_in_api({LIST: (FIXTURES / "adp" / "list.json").read_bytes()})

    result = asyncio.run(ADAPTER.fetch(_page(jobId="000000"), FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


def test_a_company_with_no_requisition_is_not_served(stand_in_api: StandInApi) -> None:
    send = stand_in_api({LIST: b'{"jobRequisitions": [], "meta": {}}'})

    result = asyncio.run(ADAPTER.fetch(_page(), FetchPolicy(), send))

    assert (result.block_class, result.attempts[-1].error) == ("error", NOT_SERVED)


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a career center URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/center", FetchPolicy(), _unused_send))


def test_every_listed_requisition_is_a_posting_with_its_places_and_stated_pay(stand_in_api: StandInApi) -> None:
    send = stand_in_api({LIST: (FIXTURES / "adp" / "list.json").read_bytes()})
    fetched = asyncio.run(ADAPTER.fetch(_page(), FetchPolicy(), send))

    found = candidates(ADAPTER, AdapterMatch(TENANT, "listing"), fetched.bundle.body.decode())

    row = "adapter:adp:$['jobRequisitions'][{}]"
    assert found == {
        (row.format(0), "title"): "Synthetic Engineer",
        (row.format(0), "date_posted"): "2026-09-30T10:00:00.000-04:00",
        (row.format(0), "identifier"): "R-100",
        (row.format(0), "url"): f"{PAGE_URL}555001",
        (row.format(0), "locations"): [" Northtown, ZZ", " Eastport, ZZ"],
        (row.format(0), "salary"): {"currency": "USD", "minValue": 85000.0, "maxValue": 115000.0},
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "date_posted"): "2026-09-29T10:00:00.000-04:00",
        (row.format(1), "identifier"): "R-101",
        (row.format(1), "url"): f"{PAGE_URL}555002",
    }


def test_a_requisition_answer_adds_its_description(stand_in_api: StandInApi) -> None:
    routes = {
        LIST: (FIXTURES / "adp" / "list.json").read_bytes(),
        f"{API}/{ITEM}?{LIST.split('?')[1]}": (FIXTURES / "adp" / "detail.json").read_bytes(),
    }
    fetched = asyncio.run(ADAPTER.fetch(_page(jobId="555001"), FetchPolicy(), stand_in_api(routes)))

    found = candidates(ADAPTER, AdapterMatch(TENANT, "detail", "555001"), fetched.bundle.body.decode())

    assert found[("adapter:adp:$", "description")] == "<p>Build things.</p>"
    assert found[("adapter:adp:$", "identifier")] == "R-100"
    assert found[("adapter:adp:$", "url")] == f"{PAGE_URL}555001"
    assert found[("adapter:adp:$", "salary")] == {"currency": "USD", "minValue": 85000.0, "maxValue": 115000.0}
