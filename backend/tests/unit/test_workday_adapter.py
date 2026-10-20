"""The Workday adapter: detect career site URLs, fetch the JSON their own pages call, read it as schema.org JobPostings.

Workday is a multi-tenant platform, not a site (C6, C9). Its domains come from the adapter module, so no hostname is
written here (C3). Tenants, sites and the recorded answers under `tests/fixtures/workday/` are synthetic.
"""

import asyncio
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, PageRefs
from crawlerai.adapters.workday import FIRST_PAGE, JOBS_DOMAIN, Workday
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


@given(tenant=labels, dc=labels, site=sites, locale=locales)
def test_a_career_site_url_is_a_listing_of_its_root(tenant: str, dc: str, site: str, locale: str) -> None:
    root = f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{site}"
    expected = AdapterMatch(tenant=root, page_kind="listing", locale=locale.strip("/") or None)
    assert ADAPTER.detect(f"https://{tenant}.{dc}.{JOBS_DOMAIN}/{locale}{site}") == expected
    assert ADAPTER.detect(f"http://{tenant.upper()}.{dc}.{JOBS_DOMAIN}/{locale}{site}/") == expected


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


def _refs(*own: str, links: tuple[str, ...] = ()) -> PageRefs:
    return PageRefs(own=own, links=links)


def test_a_listing_stands_for_the_one_career_site_its_links_belong_to() -> None:
    links = (
        f"{ROOT}/{JOB_PATH}",
        f"https://{HOST}/en-US/{SITE}/login",
        f"{ROOT}/?source=careers",
        "https://www.example.com/",
    )
    refs = _refs("https://careers.example.test/", links=links)
    jobs = ("JobPosting",)
    assert ADAPTER.referred(refs, "listing", jobs) == ROOT
    assert ADAPTER.referred(refs, "detail", jobs) is None
    assert ADAPTER.referred(refs, None, jobs) is None
    # A listing read for other items (a store's footer linking to its careers site) is not the career site's.
    assert ADAPTER.referred(refs, "listing", ("Offer", "Product")) is None
    # The page's own URL is its identity, whatever it is read for (RFC 6596, RFC 9110 §15.4).
    assert ADAPTER.referred(_refs(ROOT, links=links), "listing", ("Product",)) == ROOT


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
        (row.format(0), "locations"): ["Northtown"],
        (row.format(1), "title"): "Example Support Analyst",
        (row.format(1), "url"): f"{ROOT}/job/Southville/Example-Support-Analyst_R-0002",
        (row.format(1), "locations"): ["2 Locations"],
        (row.format(2), "title"): "Placeholder Designer",
        (row.format(2), "url"): f"{ROOT}/job/Remote/Placeholder-Designer_R-0003",
    }


def test_a_listing_under_a_locale_has_rows_equal_to_the_links_the_page_renders() -> None:
    match = ADAPTER.detect(f"https://{HOST}/en-US/{SITE}")
    assert match is not None
    candidates = _candidates(match, "jobs.json", "job_listing")

    urls = sorted(str(v) for (_, field), v in candidates.items() if field == "url")
    assert urls == [
        f"https://{HOST}/en-US/{SITE}/job/Northtown/Synthetic-Data-Engineer_R-0001",
        f"https://{HOST}/en-US/{SITE}/job/Remote/Placeholder-Designer_R-0003",
        f"https://{HOST}/en-US/{SITE}/job/Southville/Example-Support-Analyst_R-0002",
    ]
