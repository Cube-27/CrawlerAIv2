"""The Lever adapter (SPEC-02 §4.9): detect job site URLs, fetch the Postings API's JSON, map schema fields to it.

Lever is a multi-tenant platform, not a site (C6, C9). Its hosts come from the adapter module, so no hostname is
written here (C3). Sites and the recorded API responses under `tests/fixtures/lever/` are synthetic.
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.lever import JOB_SITE_APIS, Lever
from crawlerai.db.models import PageKind

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)
JsonSelect = Callable[[str, Any], list[Any]]  # the `select_json` fixture (conftest)
PresetFields = Callable[[str], dict[str, str]]  # the `preset_fields` fixture (conftest)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "lever"
HOSTS = sorted(JOB_SITE_APIS)
HOST = HOSTS[0]
SITE = "example-tenant"
POSTING = "00000000-0000-4000-8000-000000000001"

sites = st.from_regex(r"[A-Za-z0-9._~-]{1,40}", fullmatch=True).filter(lambda s: s.strip("."))
postings = st.uuids().map(str)


async def _no_fetch(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("detection fetches nothing")


ADAPTER = Lever(_no_fetch)


@given(host=st.sampled_from(HOSTS), site=sites)
def test_a_job_site_url_is_a_listing_of_its_site(host: str, site: str) -> None:
    expected = AdapterMatch(tenant=site, page_kind="listing")
    assert ADAPTER.detect(f"https://{host}/{site}") == expected
    assert ADAPTER.detect(f"http://{host.upper()}/{site}/?source=x") == expected


@given(host=st.sampled_from(HOSTS), site=sites, posting=postings)
def test_a_posting_url_is_a_detail_page_of_its_posting(host: str, site: str, posting: str) -> None:
    assert ADAPTER.detect(f"https://{host}/{site}/{posting}?source=x#top") == AdapterMatch(
        tenant=site, page_kind="detail", item=posting
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/{SITE}",  # a job site host's name inside another host
        f"ftp://{HOST}/{SITE}",
        f"https://{HOST}/",  # no site
        f"https://{HOST}/..",  # a dot-segment would move the API path
        f"https://{HOST}/{SITE}/..",
        f"https://{HOST}/{SITE}/{POSTING}/apply",  # the application form, not the posting
        f"https://{HOST}/{SITE}?team=Engineering",  # a filtered list: the unfiltered API list holds more postings
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


@pytest.mark.parametrize("host", HOSTS)
def test_a_posting_page_is_fetched_from_its_instance_get_posting_endpoint(host: str, stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "posting.json").read_bytes()
    endpoint = f"{JOB_SITE_APIS[host]}/{SITE}/{POSTING}"
    page = f"https://{host}/{SITE}/{POSTING}"

    result = asyncio.run(Lever(stand_in_api({endpoint: body})).fetch(page, FetchPolicy()))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == ("api", "ok", page, endpoint)
    assert result.bundle.body == body


def test_a_job_site_page_is_fetched_from_its_instance_list_endpoint_as_json(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "postings.json").read_bytes()
    endpoint = f"{JOB_SITE_APIS[HOST]}/{SITE}?mode=json"

    result = asyncio.run(Lever(stand_in_api({endpoint: body})).fetch(f"https://{HOST}/{SITE}", FetchPolicy()))

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == ("ok", endpoint, body)


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetch = ADAPTER.fetch("https://jobs.example.com/site", FetchPolicy())
    with pytest.raises(ValueError, match="not a job site URL"):
        asyncio.run(fetch)


def test_the_job_detail_preset_maps_to_the_posting_object(preset_fields: PresetFields) -> None:
    assert ADAPTER.map(preset_fields("job_detail"), "detail") == {
        "title": "$['text']",
        "locations": "$['categories']['location']",
        "description": "$['description']",
        "apply_url": "$['hostedUrl']",
    }


def test_the_job_listing_preset_maps_into_each_listed_posting(preset_fields: PresetFields) -> None:
    assert ADAPTER.map(preset_fields("job_listing"), "listing") == {
        "title": "$[*]['text']",
        "url": "$[*]['hostedUrl']",
        "location": "$[*]['categories']['location']",
    }


def test_a_property_the_platform_does_not_document_is_left_out() -> None:
    assert ADAPTER.map({"posted": "JobPosting.datePosted", "title": "JobPosting.title"}, "detail") == {
        "title": "$['text']"
    }


@pytest.mark.parametrize(
    ("preset", "page_kind", "fixture"),
    [("job_detail", "detail", "posting.json"), ("job_listing", "listing", "postings.json")],
)
def test_every_mapped_path_selects_a_string_in_the_recorded_response(
    preset: str, page_kind: PageKind, fixture: str, select_json: JsonSelect, preset_fields: PresetFields
) -> None:
    document = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    posting_count = 1 if page_kind == "detail" else len(document)

    for field, path in ADAPTER.map(preset_fields(preset), page_kind).items():
        values = select_json(path, document)
        assert len(values) == posting_count, field
        assert all(isinstance(value, str) and value for value in values), field
