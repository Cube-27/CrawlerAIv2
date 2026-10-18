"""The Oracle Recruiting Cloud adapter: detect career site URLs, fetch the REST resources their own pages call, read
the answers as schema.org JobPostings.

Oracle Recruiting Cloud is a multi-tenant platform, not a site (C6, C9). Its domain comes from the adapter module, so
no hostname is written here (C3). Pods, sites and the recorded answers under `tests/fixtures/oracle_recruiting/` are
synthetic.
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
from crawlerai.adapters.base import AdapterMatch
from crawlerai.adapters.oracle_recruiting import DOMAIN, PAGE_SIZE, RESOURCES, OracleRecruiting
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
HOST = f"example-pod.fa.dc1.{DOMAIN}"
SITE = "CX_1"
ROOT = f"https://{HOST}/hcmUI/CandidateExperience/en/sites/{SITE}"
API = f"https://{HOST}{RESOURCES}"
LIST_ENDPOINT = (
    f"{API}/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber={SITE},limit={PAGE_SIZE},offset=0"
    "&expand=requisitionList"
)

ADAPTER = OracleRecruiting()

labels = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?", fullmatch=True)
names = st.from_regex(r"[A-Za-z0-9_-]{1,20}", fullmatch=True)
languages = st.sampled_from(["en", "fr", "pt-BR", "zh-CN"])


@given(pod=labels, dc=st.one_of(st.just(""), labels.map(lambda d: f".{d}")), site=names, language=languages)
def test_a_career_site_url_is_a_listing_of_its_site(pod: str, dc: str, site: str, language: str) -> None:
    root = f"https://{pod}.fa{dc}.{DOMAIN}/hcmUI/CandidateExperience/{language}/sites/{site}"
    expected = AdapterMatch(tenant=root, page_kind="listing")
    assert ADAPTER.detect(root) == expected
    assert ADAPTER.detect(f"{root}/requisitions/") == expected
    assert ADAPTER.detect(f"{root}/jobs") == expected


def _recording(stand_in_api: StandInApi, routes: Mapping[str, bytes], sent: list[JsonRequest]) -> JsonFetcher:
    send = stand_in_api(routes)

    async def recorded(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        sent.append(request)
        return await send(request, policy)

    return recorded


def test_a_list_is_its_sites_first_page_of_requisitions_in_the_pages_language(stand_in_api: StandInApi) -> None:
    body = (FIXTURES / "oracle_recruiting" / "requisitions.json").read_bytes()
    sent: list[JsonRequest] = []
    page = f"{ROOT}/requisitions"

    result = asyncio.run(ADAPTER.fetch(page, FetchPolicy(), _recording(stand_in_api, {LIST_ENDPOINT: body}, sent)))

    manifest = result.bundle.manifest
    assert (manifest.method, manifest.block_class, manifest.url, manifest.final_url) == (
        "api",
        "ok",
        page,
        LIST_ENDPOINT,
    )
    assert result.bundle.body == body
    assert [(r.method, r.headers) for r in sent] == [("GET", (("Accept-Language", "en"),))]
    assert ADAPTER.serves(AdapterMatch(ROOT, "listing"), manifest.final_url) is True


def _requisitions(first: int, count: int, total: int) -> bytes:
    listed = [{"Id": str(i), "Title": f"Job {i}"} for i in range(first, first + count)]
    return json.dumps({"items": [{"TotalJobsCount": total, "requisitionList": listed}], "hasMore": False}).encode()


def test_a_list_is_paged_by_offset_until_the_total_the_first_item_states(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def answer(request: JsonRequest) -> bytes:
        offset = int(request.url.split("offset=")[1].split("&")[0])
        return _requisitions(offset, min(PAGE_SIZE, 250 - offset), total=250)

    result = asyncio.run(ADAPTER.fetch(ROOT, FetchPolicy(), scripted_api(answer, sent)))

    assert [r.url.split("offset=")[1].split("&")[0] for r in sent] == ["0", "100", "200"]
    assert all(f"limit={PAGE_SIZE}," in r.url for r in sent)
    (search,) = json.loads(result.bundle.body)["items"]
    assert [r["Id"] for r in search["requisitionList"]] == [str(i) for i in range(250)]
    assert search["TotalJobsCount"] == 250
    assert ADAPTER.serves(AdapterMatch(ROOT, "listing"), result.bundle.manifest.final_url) is True


VOCABULARY = Vocabulary.read(FIXTURES / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


def _candidates(match: AdapterMatch, fixture: str, preset: str) -> dict[tuple[str, str], JsonValue]:
    (document,) = (d for d in load_presets() if d.name == preset)
    schema = SchemaDef(id=SchemaId(uuid7()), origin="preset", status="active", **document.model_dump())
    extra = {"employment_type": "JobPosting.employmentType", "posted": "JobPosting.datePosted"}
    fields = {name: FieldSpec(type=FieldType.TEXT, description="d", schema_org=path) for name, path in extra.items()}
    schema = schema.model_copy(update={"fields": {**schema.fields, **fields}})
    body = (FIXTURES / "oracle_recruiting" / fixture).read_text(encoding="utf-8")
    result = AdapterCollector(ADAPTER, match, VOCABULARY).collect(ParsedPage(body), schema, CTX)
    return {(c.entity_id, c.field): c.raw for c in result.candidates}


def test_every_listed_requisition_carries_its_job_pages_url() -> None:
    candidates = _candidates(AdapterMatch(ROOT, "listing"), "requisitions.json", "job_listing")

    row = "adapter:oracle_recruiting:$['items'][0]['requisitionList'][{}]"
    assert candidates == {
        (row.format(0), "title"): "Synthetic Platform Engineer",
        (row.format(0), "url"): f"{ROOT}/job/100001",
        (row.format(0), "locations"): ["Northtown, Example Region, Exampleland"],
        (row.format(0), "posted"): "2026-09-30",
        (row.format(1), "title"): "Placeholder Analyst",
        (row.format(1), "url"): f"{ROOT}/job/100002",
        (row.format(1), "locations"): ["Eastport"],
        (row.format(1), "posted"): "2026-09-29",
    }
