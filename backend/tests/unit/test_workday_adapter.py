"""The Workday adapter: detect career site URLs, fetch the JSON their own pages call, read it as schema.org JobPostings.

Workday is a multi-tenant platform, not a site (C6, C9). Its domains come from the adapter module, so no hostname is
written here (C3). Tenants, sites and the recorded answers under `tests/fixtures/workday/` are synthetic.
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, PageRefs
from crawlerai.adapters.workday import FIRST_PAGE, JOBS_DOMAIN, SITES_DOMAIN, Workday
from crawlerai.collect.adapter import AdapterCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

StandInApi = Callable[[Mapping[str, bytes]], JsonFetcher]  # the `stand_in_api` fixture (conftest)
ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]  # `scripted_api` (conftest)

FIXTURES = Path(__file__).parents[1] / "fixtures"
TENANT, SITE, DC = "example-tenant", "External", "wd1"
HOST = f"{TENANT}.{DC}.{JOBS_DOMAIN}"
ROOT = f"https://{HOST}/{SITE}"
API = f"https://{HOST}/wday/cxs/{TENANT}/{SITE}"
JOB_PATH = "job/Southville/Example-Support-Analyst_R-0002"

ADAPTER = Workday()

labels = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?", fullmatch=True)
sites = st.from_regex(r"[A-Za-z0-9_~-]{1,30}", fullmatch=True).filter(lambda s: s != "recruiting")
locales = st.sampled_from(["", "en-US/", "fr-FR/", "ja-JP/"])
slugs = st.from_regex(r"[A-Za-z0-9-]{1,30}_[A-Z0-9-]{1,12}", fullmatch=True)


@given(tenant=labels, dc=labels, site=sites, locale=locales)
def test_a_career_site_url_is_a_listing_of_its_root(tenant: str, dc: str, site: str, locale: str) -> None:
    root = f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{site}"
    expected = AdapterMatch(tenant=root, page_kind="listing")
    assert ADAPTER.detect(f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{locale}{site}") == expected
    assert ADAPTER.detect(f"http://{tenant.upper()}.{dc}.{JOBS_DOMAIN}/{locale}{site}/") == expected


@given(tenant=labels, dc=labels, site=sites, locale=locales, place=slugs, slug=slugs)
def test_a_job_url_is_a_detail_page_of_its_job_path(
    tenant: str, dc: str, site: str, locale: str, place: str, slug: str
) -> None:
    url = f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{locale}{site}/job/{place}/{slug}?source=x#apply"
    assert ADAPTER.detect(url) == AdapterMatch(
        tenant=f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{site}", page_kind="detail", item=f"job/{place}/{slug}"
    )


@given(tenant=labels, dc=labels, site=sites, locale=locales)
def test_a_shared_host_names_the_tenant_in_its_path(tenant: str, dc: str, site: str, locale: str) -> None:
    root = f"https://{dc}.{SITES_DOMAIN}/recruiting/{tenant}/{site}"
    assert ADAPTER.detect(f"https://{dc}.{SITES_DOMAIN}/{locale}recruiting/{tenant}/{site}") == AdapterMatch(
        tenant=root, page_kind="listing"
    )
    assert ADAPTER.detect(f"{root}/{JOB_PATH}") == AdapterMatch(tenant=root, page_kind="detail", item=JOB_PATH)


@pytest.mark.parametrize(
    "url",
    [
        f"https://{HOST}.example.com/{SITE}",  # the platform's domain inside another host
        f"https://{DC}.{JOBS_DOMAIN}/{SITE}",  # no tenant label
        f"https://a.{HOST}/{SITE}",  # a label too many
        f"ftp://{HOST}/{SITE}",
        f"https://{HOST}/",  # no site
        f"https://{HOST}/en-US",  # a locale and no site
        f"https://{HOST}/..",  # a dot-segment would move the API path
        f"{ROOT}?locations=0001",  # a filtered list: the unfiltered first page holds other postings
        f"{ROOT}/job/Southville",  # no job slug
        f"{ROOT}/{JOB_PATH}/apply",  # the application form
        f"{ROOT}/details/Example_R-0002",
        f"https://{DC}.{SITES_DOMAIN}/recruiting/{TENANT}",  # no site
        f"https://{DC}.{SITES_DOMAIN}/{SITE}",
        f"https://{TENANT}.{DC}.{SITES_DOMAIN}/recruiting/{TENANT}/{SITE}",
    ],
)
def test_other_urls_are_not_detected(url: str) -> None:
    assert ADAPTER.detect(url) is None


def _recording(stand_in_api: StandInApi, routes: Mapping[str, bytes], sent: list[JsonRequest]) -> JsonFetcher:
    send = stand_in_api(routes)

    async def recorded(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        sent.append(request)
        return await send(request, policy)

    return recorded


def test_a_listing_is_the_first_page_of_postings_asked_in_the_pages_locale(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "workday" / "jobs.json").read_bytes()
    sent: list[JsonRequest] = []
    page = f"https://{HOST}/fr-FR/{SITE}"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), _recording(stand_in_api, {f"{API}/jobs": body}, sent)))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == (
        "api",
        "ok",
        page,
        f"{API}/jobs",
    )
    assert result.bundle.body == body
    (request,) = sent
    assert (request.method, json.loads(request.body or "")) == ("POST", FIRST_PAGE)
    assert ("Accept-Language", "fr-FR") in request.headers


def test_a_job_page_is_fetched_from_its_job_path(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "workday" / "job.json").read_bytes()
    sent: list[JsonRequest] = []
    send = _recording(stand_in_api, {f"{API}/{JOB_PATH}": body}, sent)

    result = asyncio.run(ADAPTER.fetch(f"{ROOT}/{JOB_PATH}", FetchPolicy(), send))

    assert (result.block_class, result.bundle.manifest.final_url, result.bundle.body) == (
        "ok",
        f"{API}/{JOB_PATH}",
        body,
    )
    assert [(r.method, r.body, r.headers) for r in sent] == [("GET", None, ())]


def _postings(count: int, first: int, *, total: int | None) -> bytes:
    rows = [{"title": f"Job {i}", "externalPath": f"/job/Northtown/Job-{i}_R-{i}"} for i in range(first, first + count)]
    return json.dumps({"total": total, "jobPostings": rows} if total is not None else {"jobPostings": rows}).encode()


def test_a_list_is_paged_by_offset_until_a_short_page(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        offset = json.loads(request.body or "")["offset"]
        # Only the first page states `total`, which the other pages do not repeat (here more than the list holds).
        return _postings(min(20, 45 - offset), offset, total=999 if offset == 0 else None)

    result = asyncio.run(ADAPTER.fetch(ROOT, FetchPolicy(), scripted_api(answer, sent)))

    bodies = [json.loads(r.body or "") for r in sent]
    assert [(b["offset"], b["limit"]) for b in bodies] == [(0, 20), (20, 20), (40, 20)]
    merged = json.loads(result.bundle.body)
    assert [p["title"] for p in merged["jobPostings"]] == [f"Job {i}" for i in range(45)]
    assert merged["total"] == 999
    assert ADAPTER.serves(AdapterMatch(ROOT, "listing"), result.bundle.manifest.final_url) is True


def test_a_list_stops_at_the_total_the_first_page_states(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        offset = json.loads(request.body or "")["offset"]
        return _postings(20, offset, total=40 if offset == 0 else None)

    result = asyncio.run(ADAPTER.fetch(ROOT, FetchPolicy(), scripted_api(answer, sent)))

    assert [json.loads(r.body or "")["offset"] for r in sent] == [0, 20]
    assert len(json.loads(result.bundle.body)["jobPostings"]) == 40


def test_the_requests_row_target_bounds_the_pages(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        offset = json.loads(request.body or "")["offset"]
        return _postings(20, offset, total=1000 if offset == 0 else None)

    result = asyncio.run(ADAPTER.fetch(ROOT, FetchPolicy(max_rows=30), scripted_api(answer, sent)))

    assert len(sent) == 2
    assert len(json.loads(result.bundle.body)["jobPostings"]) == 40


def _refs(*own: str, links: tuple[str, ...] = ()) -> PageRefs:
    return PageRefs(own=own, links=links)


def test_a_page_that_names_a_career_site_as_itself_stands_for_it() -> None:
    own = f"https://{HOST}/en-US/{SITE}"
    assert ADAPTER.referred(_refs("https://careers.example.test/", own), "listing") == own
    # A job page is not the list a listing scrape asks for, and the other way round.
    job = f"{ROOT}/{JOB_PATH}"
    assert ADAPTER.referred(_refs("https://careers.example.test/", job), "listing") is None
    assert ADAPTER.referred(_refs(job), "detail") == job
    assert ADAPTER.referred(_refs(ROOT), None) == ROOT


def test_a_listing_stands_for_the_one_career_site_its_links_belong_to() -> None:
    links = (
        f"{ROOT}/{JOB_PATH}",
        f"https://{HOST}/en-US/{SITE}/login",
        f"{ROOT}/?source=careers",
        "https://www.example.com/",
    )
    refs = _refs("https://careers.example.test/", links=links)
    assert ADAPTER.referred(refs, "listing") == ROOT
    assert ADAPTER.referred(refs, "detail") is None
    assert ADAPTER.referred(refs, None) is None


def test_links_to_two_career_sites_do_not_say_which_the_page_stands_for() -> None:
    links = (f"{ROOT}/{JOB_PATH}", f"https://{HOST}/Other/job/Southville/Example_R-9")
    assert ADAPTER.referred(_refs("https://careers.example.test/", links=links), "listing") is None


def test_a_page_that_states_no_career_site_stands_for_none() -> None:
    refs = _refs("https://careers.example.test/", links=("https://www.example.com/jobs",))
    assert ADAPTER.referred(refs, "listing") is None


async def _unused_send(_request: JsonRequest, _policy: FetchPolicy) -> FetchResult:
    raise AssertionError("a refused URL sends nothing")


def test_a_url_it_does_not_detect_is_refused() -> None:
    fetch = ADAPTER.fetch("https://jobs.example.com/External", FetchPolicy(), _unused_send)
    with pytest.raises(ValueError, match="not a career site URL"):
        asyncio.run(fetch)


def test_it_serves_its_sites_endpoints_and_no_page() -> None:
    listing = AdapterMatch(tenant=ROOT, page_kind="listing")
    assert ADAPTER.serves(listing, f"{API}/jobs") is True
    assert ADAPTER.serves(listing, f"{API}/{JOB_PATH}") is True
    assert ADAPTER.serves(listing, f"https://{HOST}/wday/cxs/{TENANT}/Other/jobs") is False
    assert ADAPTER.serves(listing, f"{API}-2/jobs") is False
    assert ADAPTER.serves(listing, ROOT) is False


VOCABULARY = Vocabulary.read(FIXTURES / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


def _candidates(match: AdapterMatch, fixture: str, preset: str) -> dict[tuple[str, str], JsonValue]:
    (document,) = (d for d in load_presets() if d.name == preset)
    schema = SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **document.model_dump())
    if preset == "job_detail":
        employment = FieldSpec(type=FieldType.TEXT, description="d", schema_org="JobPosting.employmentType")
        schema = schema.model_copy(update={"fields": {**schema.fields, "employment_type": employment}})
    body = (FIXTURES / "workday" / fixture).read_text(encoding="utf-8")
    result = AdapterCollector(ADAPTER, match, VOCABULARY).collect(ParsedPage(body), schema, CTX)
    return {(c.entity_id, c.field): c.raw for c in result.candidates}


def test_every_listing_row_carries_its_jobs_url_under_the_career_site_root() -> None:
    candidates = _candidates(AdapterMatch(ROOT, "listing"), "jobs.json", "job_listing")

    row = "adapter:workday:$['jobPostings'][{}]"
    assert candidates == {
        (row.format(0), "title"): "Synthetic Data Engineer",
        (row.format(0), "url"): f"{ROOT}/job/Northtown/Synthetic-Data-Engineer_R-0001",
        (row.format(0), "location"): "Northtown",
        (row.format(1), "title"): "Example Support Analyst",
        (row.format(1), "url"): f"{ROOT}/job/Southville/Example-Support-Analyst_R-0002",
        (row.format(1), "location"): "2 Locations",
        (row.format(2), "title"): "Placeholder Designer",
        (row.format(2), "url"): f"{ROOT}/job/Remote/Placeholder-Designer_R-0003",
    }


def test_a_job_answer_is_one_posting_with_its_stated_fields() -> None:
    candidates = _candidates(AdapterMatch(ROOT, "detail", JOB_PATH), "job.json", "job_detail")

    assert candidates == {
        ("adapter:workday:$", "title"): "Example Support Analyst",
        ("adapter:workday:$", "description"): (
            "<p>Answer synthetic questions.</p><ul><li>Two years of example experience.</li></ul>"
        ),
        (
            "adapter:workday:$",
            "apply_url",
        ): "https://jobs.example.com/External/job/Southville/Example-Support-Analyst_R-0002",
        ("adapter:workday:$", "date_posted"): "2026-09-28",
        ("adapter:workday:$", "employment_type"): "Full time",
        ("adapter:workday:$", "locations"): ["Southville", "Eastport"],
        ("adapter:workday:$", "company"): "Example Org Ltd",
    }
