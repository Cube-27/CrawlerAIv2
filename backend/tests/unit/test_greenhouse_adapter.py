"""The Greenhouse adapter (SPEC-02 §4.9): detect board URLs, fetch the Job Board API's JSON, map schema fields to it.

Greenhouse is a multi-tenant platform, not a site (C6, C9). Its hosts come from the adapter module, so no hostname is
written here (C3). Tenants and the recorded API responses under `tests/fixtures/greenhouse/` are synthetic.
"""

import asyncio
import json
import re
from functools import partial
from ipaddress import ip_address
from pathlib import Path
from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest, fetch_json
from crawlerai.acquire.ssrf import IPAddress, SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.greenhouse import API, BOARD_HOSTS, Greenhouse
from crawlerai.db.models import PageKind
from crawlerai.schemas.registry import load_presets

FIXTURES = Path(__file__).parents[1] / "fixtures" / "greenhouse"
HOST = sorted(BOARD_HOSTS)[0]
TENANT = "example-tenant"

tokens = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda t: t.strip(".") and t != "embed")
job_ids = st.integers(min_value=1, max_value=10**12).map(str)


async def _no_fetch(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("detection fetches nothing")


ADAPTER = Greenhouse(_no_fetch)


@given(host=st.sampled_from(sorted(BOARD_HOSTS)), token=tokens, scheme=st.sampled_from(["http", "https"]))
def test_a_board_url_is_a_listing_of_its_tenant(host: str, token: str, scheme: str) -> None:
    expected = AdapterMatch(tenant=token, page_kind="listing")
    assert ADAPTER.detect(f"{scheme}://{host}/{token}") == expected
    assert ADAPTER.detect(f"{scheme}://{host.upper()}/{token}/") == expected


@given(host=st.sampled_from(sorted(BOARD_HOSTS)), token=tokens, job_id=job_ids)
def test_a_job_url_is_a_detail_page_of_its_job(host: str, token: str, job_id: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{token}/jobs/{job_id}?source=x#apply") == AdapterMatch(
        tenant=token, page_kind="detail", item=job_id
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
        f"https://jobs.example.com/{TENANT}",  # not a board host
        f"https://{HOST}.example.com/{TENANT}",  # a board host's name inside another host
        f"ftp://{HOST}/{TENANT}",
        f"https://{HOST}/",  # no tenant
        f"https://{HOST}/{TENANT}/jobs",  # no job
        f"https://{HOST}/{TENANT}/jobs/not-a-number",
        f"https://{HOST}/{TENANT}/jobs/1/extra",
        f"https://{HOST}/..",  # a dot-segment would move the API path
        f"https://{HOST}/{TENANT}%2Fjobs",
        f"https://{HOST}/embed/job_board",  # no `for`
        f"https://{HOST}/embed/job_board?for=a&for=b",  # two tenants
        f"https://{HOST}/embed/job_app?for={TENANT}",  # no job token
        f"https://{HOST}/embed/job_app?for={TENANT}&token=x",
        f"https://{HOST}/embed/other?for={TENANT}",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def _api(routes: dict[str, bytes]) -> JsonFetcher:
    """`fetch_json` against a stand-in API serving `routes` (path and query -> body), resolving every host to a
    public address."""

    async def resolve(_host: str) -> list[IPAddress]:
        return [ip_address("93.184.215.14")]

    def handler(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.raw_path.decode())
        return httpx.Response(404, json={}) if body is None else httpx.Response(200, content=body)

    return partial(
        fetch_json, engine_version="test", connector=SafeConnector(resolve), transport=httpx.MockTransport(handler)
    )


def _api_path(endpoint: str) -> str:
    return httpx.URL(endpoint).raw_path.decode()


def test_a_job_page_is_fetched_from_the_retrieve_job_endpoint() -> None:
    body = (FIXTURES / "job.json").read_bytes()
    endpoint = f"{API}/{TENANT}/jobs/4000001"
    page = f"https://{HOST}/{TENANT}/jobs/4000001"

    result = asyncio.run(Greenhouse(_api({_api_path(endpoint): body})).fetch(page, FetchPolicy()))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, endpoint)
    assert result.bundle.body == body


def test_a_board_page_is_fetched_from_the_list_jobs_endpoint_with_content() -> None:
    body = (FIXTURES / "jobs.json").read_bytes()
    endpoint = f"{API}/{TENANT}/jobs?content=true"

    result = asyncio.run(Greenhouse(_api({_api_path(endpoint): body})).fetch(f"https://{HOST}/{TENANT}", FetchPolicy()))

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)


def test_a_missing_job_is_not_found() -> None:
    result = asyncio.run(Greenhouse(_api({})).fetch(f"https://{HOST}/{TENANT}/jobs/1", FetchPolicy()))

    assert result.block_class == "not_found"


def test_a_url_it_does_not_detect_is_refused() -> None:
    with pytest.raises(ValueError, match="not a job board URL"):
        asyncio.run(ADAPTER.fetch("https://jobs.example.com/board", FetchPolicy()))


def _schema_org(preset: str) -> dict[str, str]:
    (schema,) = (s for s in load_presets() if s.name == preset)
    return {name: spec.schema_org for name, spec in schema.fields.items() if spec.schema_org is not None}


def test_the_job_detail_preset_maps_to_the_job_object() -> None:
    assert ADAPTER.map(_schema_org("job_detail"), "detail") == {
        "title": "$['title']",
        "company": "$['company_name']",
        "locations": "$['location']['name']",
        "description": "$['content']",
        "apply_url": "$['absolute_url']",
        "date_posted": "$['first_published']",
    }


def test_the_job_listing_preset_maps_into_each_listed_job() -> None:
    assert ADAPTER.map(_schema_org("job_listing"), "listing") == {
        "title": "$['jobs'][*]['title']",
        "url": "$['jobs'][*]['absolute_url']",
        "location": "$['jobs'][*]['location']['name']",
    }


def test_a_property_the_platform_does_not_document_is_left_out() -> None:
    assert ADAPTER.map({"salary": "JobPosting.baseSalary", "title": "JobPosting.title"}, "detail") == {
        "title": "$['title']"
    }


def _select(path: str, document: Any) -> list[Any]:
    """The values a mapped path selects: `$`, then `['name']` member and `[*]` wildcard segments (RFC 9535 §2.5)."""
    nodes = [document]
    for segment in re.findall(r"\['([^']*)'\]|\[\*\]", path.removeprefix("$")):
        if segment:
            nodes = [node[segment] for node in nodes if isinstance(node, dict) and segment in node]
        else:
            nodes = [item for node in nodes for item in node]
    return nodes


@pytest.mark.parametrize(
    ("preset", "page_kind", "fixture"), [("job_detail", "detail", "job.json"), ("job_listing", "listing", "jobs.json")]
)
def test_every_mapped_path_selects_a_string_in_the_recorded_response(
    preset: str, page_kind: PageKind, fixture: str
) -> None:
    document = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))

    selected = {field: _select(path, document) for field, path in ADAPTER.map(_schema_org(preset), page_kind).items()}

    expected_count = 1 if page_kind == "detail" else len(document["jobs"])
    assert {field: len(values) for field, values in selected.items()} == dict.fromkeys(selected, expected_count)
    assert all(isinstance(value, str) and value for values in selected.values() for value in values)
