"""ADP Workforce Now career centers through the recruitment API of the company (owner delegation 2026-10-17).

Endpoints, the public JSON the platform's own career center loads (verified against live answers, 2026-10-17),
unauthenticated: `GET /mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?cid=&ccId=` lists a
company's open requisitions whole, `{"jobRequisitions": [{"itemID", "requisitionTitle", "postDate",
"clientRequisitionID", "requisitionLocations": [{"nameCode": {"shortName"}}], "payGradeRange", "customFieldGroup"}]}`;
`GET .../job-requisitions/{itemID}?cid=&ccId=` answers one with its `requisitionDescription`. A career center is the
page `/mascsr/default/mdf/recruitment/recruitment.html?cid={cid}&ccId={ccId}` on the platform's host, with `jobId` for
a requisition: the `ExternalJobID` the requisition's `customFieldGroup.stringFields` states, found in the list. The
adapter records each requisition with that id as its `externalJobID` member, so a requisition's page is its center's
page with `jobId`. The API's own `lang` and `locale` follow the page's `lang`.
"""

import json
import re
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.answer import recorded, serving
from crawlerai.adapters.base import ALL, NOT_SERVED, AdapterMatch, Shape

HOST: Final = "workforcenow.adp.com"
API: Final = f"https://{HOST}/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
PAGE_PATH: Final = "/mascsr/default/mdf/recruitment/recruitment.html"

# The identifiers the page's query names: a company id (a UUID, RFC 9562 §4), a career center id (`YYYYMMDD_NNNNNN`),
# a language tag (`en_US`) and the ASCII word characters of a requisition's external id.
_CID: Final = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", re.ASCII)
_CC_ID: Final = re.compile(r"\d{8}_\d{6}", re.ASCII)
_LANG: Final = re.compile(r"[a-z]{2,3}(?:_[A-Za-z0-9]{2,4})?", re.ASCII)
_JOB_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}", re.ASCII)
_EXTERNAL_ID: Final = "ExternalJobID"
_SEP: Final = "|"  # the tenant is `cid|ccId|lang`; neither identifier holds it

# A requisition as a schema.org JobPosting: `clientRequisitionID` is the company's own number for it; its places are
# `requisitionLocations` as written; `payGradeRange` is the pay (rates with their currency), stated when the company
# shows one. The list gives no description and no page of its own for a requisition.
_PAY: Final = Shape(
    type="MonetaryAmount",
    at=("payGradeRange",),
    anchor=("minimumRate", "amountValue"),
    properties={
        "currency": ("minimumRate", "currencyCode"),
        "minValue": ("minimumRate", "amountValue"),
        "maxValue": ("maximumRate", "amountValue"),
    },
)
_COMMON: Final = {
    "title": ("requisitionTitle",),
    "datePosted": ("postDate",),
    "identifier": ("clientRequisitionID",),
    "jobLocation": ("requisitionLocations", ALL, "nameCode", "shortName"),
    "url": ("externalJobID",),
}
_LISTED: Final = Shape(
    type="JobPosting", at=("jobRequisitions", ALL), properties=_COMMON, nodes={"baseSalary": (_PAY,)}
)
_DETAIL: Final = Shape(
    type="JobPosting",
    properties={**_COMMON, "description": ("requisitionDescription",)},
    nodes={"baseSalary": (_PAY,)},
)


class ADP:
    name: Final = "adp"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname != HOST or parts.path != PAGE_PATH:
            return None
        query = {name: values[-1] for name, values in parse_qs(parts.query).items()}
        cid, cc_id, lang = query.get("cid", ""), query.get("ccId", ""), query.get("lang", "")
        if not (_CID.fullmatch(cid) and _CC_ID.fullmatch(cc_id)) or (lang and not _LANG.fullmatch(lang)):
            return None
        tenant = _SEP.join((cid, cc_id, lang))
        job = query.get("jobId")
        if job is None:
            return AdapterMatch(tenant=tenant, page_kind="listing")
        return AdapterMatch(tenant=tenant, page_kind="detail", item=job) if _JOB_ID.fullmatch(job) else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(API) and endpoint.endswith(f"?{_query(match.tenant)}")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career center URL this adapter detects")
        query = _query(match.tenant)
        result = await send(JsonRequest(url=f"{API}?{query}", page_url=url), policy)
        listed = serving(result, _rows)
        if listed.block_class != "ok":
            return listed
        answer = json.loads(listed.bundle.body)
        if match.item is None:
            return recorded(listed, _with_job_ids(answer))
        found = _item_id(answer, match.item)
        if found is None:
            return as_error(listed, NOT_SERVED)
        detail = await send(JsonRequest(url=f"{API}/{quote(found, safe='')}?{query}", page_url=url), policy)
        return _described(detail, listed)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        cid, cc_id, lang = match.tenant.split(_SEP)
        page = urlencode({"cid": cid, "ccId": cc_id, **({"lang": lang} if lang else {})})
        prefixes = {"url": f"https://{HOST}{PAGE_PATH}?{page}&jobId="}
        if match.page_kind == "detail":
            return (replace(_DETAIL, prefixes=prefixes),)
        listed = replace(_LISTED, prefixes=prefixes)
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _query(tenant: str) -> str:
    cid, cc_id, lang = tenant.split(_SEP)
    return urlencode({"cid": cid, "ccId": cc_id, **({"lang": lang, "locale": lang} if lang else {})})


def _described(detail: FetchResult, listed: FetchResult) -> FetchResult:
    """The requisition's answer, recorded with its `externalJobID`, and with the list's attempts and time too."""
    if detail.block_class != "ok":
        return detail
    answer = json.loads(detail.bundle.body)
    if isinstance(answer, dict):
        answer["externalJobID"] = _first_text(_external_ids(answer))
    return recorded(detail, answer).model_copy(
        update={
            "attempts": (*listed.attempts, *detail.attempts),
            "duration_ms": listed.duration_ms + detail.duration_ms,
        }
    )


def _with_job_ids(answer: JsonValue) -> JsonValue:
    """`answer` with each requisition's `externalJobID`: the id its `customFieldGroup` states, None for none."""
    for requisition in _requisitions(answer):
        if isinstance(requisition, dict):
            requisition["externalJobID"] = _first_text(_external_ids(requisition))
    return answer


def _first_text(values: list[JsonValue]) -> str | None:
    return next((v for v in values if isinstance(v, str) and v), None)


def _requisitions(answer: JsonValue) -> list[JsonValue]:
    found = answer.get("jobRequisitions") if isinstance(answer, dict) else None
    return found if isinstance(found, list) else []


def _rows(answer: JsonValue) -> int:
    return len(_requisitions(answer))


def _item_id(answer: JsonValue, job: str) -> str | None:
    """The `itemID` of the requisition whose external id (or own `itemID`) is `job`; None for none."""
    for requisition in _requisitions(answer):
        if not isinstance(requisition, dict) or not isinstance(item := requisition.get("itemID"), str):
            continue
        if job == item or job in _external_ids(requisition):
            return item
    return None


def _external_ids(requisition: dict[str, JsonValue]) -> list[JsonValue]:
    group = requisition.get("customFieldGroup")
    fields = group.get("stringFields") if isinstance(group, dict) else None
    named = [f for f in (fields if isinstance(fields, list) else []) if isinstance(f, dict)]
    return [f.get("stringValue") for f in named if _code(f) == _EXTERNAL_ID]


def _code(field: dict[str, JsonValue]) -> JsonValue:
    name = field.get("nameCode")
    return name.get("codeValue") if isinstance(name, dict) else None
