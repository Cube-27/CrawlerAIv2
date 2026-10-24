"""UKG Pro (UltiPro) Recruiting job boards through the board's search API and job pages (owner delegation 2026-10-17).

Endpoints, what the platform's own job boards load (verified against live answers, 2026-10-17), unauthenticated:
`POST /{company}/JobBoard/{board}/JobBoardView/LoadSearchResults` with `{"opportunitySearch": {"Top", "Skip",
"QueryString", "OrderBy", "Filters"}, "matchCriteria": {...}}` lists the open opportunities in pages, `{"opportunities":
[{"Id", "Title", "RequisitionNumber", "Locations", "PostedDate", "BriefDescription"}], "totalCount"}`;
`GET .../OpportunityDetail?opportunityId={Id}` is the opportunity's page, which embeds the opportunity as the JSON
object argument of `new US.Opportunity.CandidateOpportunityDetail({...})` (read with `json.JSONDecoder.raw_decode`,
RFC 8259; the recorded capture is that object). A board is `/{company}/JobBoard/{board}` (a UUID) on
`recruiting.ultipro.com` or `recruiting2.ultipro.com`; its match tenant is `{host}/{company}/{board}`, so the API and
page URLs follow from it. The host's robots.txt disallows `*/JobBoardView`, so by default the list request is refused
and the page rungs serve; a job page is allowed.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qsl, urlsplit

from pydantic import JsonValue

from snowcrawl.acquire.api import JsonFetcher, JsonRequest
from snowcrawl.acquire.outcome import as_error
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.adapters.answer import recorded, serving
from snowcrawl.adapters.base import ALL, NOT_SERVED, PATH_SEGMENT, AdapterMatch, Shape
from snowcrawl.adapters.paging import fetch_pages

HOSTS: Final = frozenset({"recruiting.ultipro.com", "recruiting2.ultipro.com"})
# The most opportunities one search request asks for.
PAGE_SIZE: Final = 50

# A board and an opportunity are identified by UUIDs (RFC 9562 §4).
_UUID: Final = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", re.ASCII)
# The board page's own query: a search text and its order; a listing with the text empty is the whole list.
_LIST_QUERY: Final = frozenset({"q", "o"})
_JSON: Final = (("Content-Type", "application/json; charset=utf-8"),)
_HTML: Final = (("Accept", "text/html"),)
_EMBEDDED: Final = "CandidateOpportunityDetail("
_MATCH_CRITERIA: Final = {
    "PreferredJobs": [],
    "Educations": [],
    "LicenseAndCertifications": [],
    "Skills": [],
    "hasNoLicenses": False,
    "SkippedSkills": [],
}

# An opportunity as a schema.org JobPosting: its page is `OpportunityDetail?opportunityId={Id}` on the board (the
# prefix `shapes` puts before `Id`); `RequisitionNumber` is the company's number for it; its places are the
# `LocalizedName`s of its `Locations`. A list gives `BriefDescription`, the page `Description`; the page states pay
# as annual or hourly amounts with a currency, or as a pay range, when the company shows them. `PostedDate` is the
# requisition's; the page also lists the boards it is posted on (`JobBoardMemberships`, each with its `JobBoardId` and
# `ExternalPostedDate`), and the date the board shows is its own membership's (`_posted_on_board`).
_COMMON: Final = {
    "title": ("Title",),
    "datePosted": ("PostedDate",),
    "identifier": ("RequisitionNumber",),
    "jobLocation": ("Locations", ALL, "LocalizedName"),
}
_LISTED: Final = Shape(
    type="JobPosting",
    at=("opportunities", ALL),
    properties={**_COMMON, "description": ("BriefDescription",), "url": ("Id",)},
)
_ANNUAL: Final = Shape(
    type="MonetaryAmount",
    anchor=("CompensationAnnualMinimum",),
    properties={
        "currency": ("CompensationCurrencyCode",),
        "minValue": ("CompensationAnnualMinimum",),
        "maxValue": ("CompensationAnnualMaximum",),
    },
)
_HOURLY: Final = Shape(
    type="MonetaryAmount",
    anchor=("CompensationHourlyMinimum",),
    properties={
        "currency": ("CompensationCurrencyCode",),
        "minValue": ("CompensationHourlyMinimum",),
        "maxValue": ("CompensationHourlyMaximum",),
    },
)
_RANGE: Final = Shape(
    type="MonetaryAmount",
    at=("PayRange",),
    anchor=("PayRangeMinimum",),
    properties={"minValue": ("PayRangeMinimum",), "maxValue": ("PayRangeMaximum",)},
)
_MEMBERSHIPS: Final = "JobBoardMemberships"
_DETAIL: Final = Shape(
    type="JobPosting",
    properties={**_COMMON, "description": ("Description",)},
    nodes={"baseSalary": (_ANNUAL, _HOURLY, _RANGE)},
)


class UltiPro:
    name: Final = "ukg"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname not in HOSTS:
            return None
        path = parts.path.strip("/").split("/")
        if (
            len(path) < 3
            or path[1] != "JobBoard"
            or not PATH_SEGMENT.fullmatch(path[0])
            or not _UUID.fullmatch(path[2])
        ):
            return None
        tenant = f"{parts.hostname}/{path[0]}/{path[2]}"
        query = parse_qsl(parts.query, keep_blank_values=True)
        match path[3:]:
            case [] if all(k in _LIST_QUERY and (k != "q" or not v) for k, v in query):
                return AdapterMatch(tenant=tenant, page_kind="listing")
            case ["OpportunityDetail"] if len(query) == 1 and _is_opportunity(*query[0]):
                return AdapterMatch(tenant=tenant, page_kind="detail", item=query[0][1])
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint == _search(match.tenant) or endpoint.startswith(f"{_board(match.tenant)}/OpportunityDetail?")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        if match.item is not None:
            page = _detail_url(match.tenant, match.item)
            result = await send(JsonRequest(url=page, page_url=url, headers=_HTML, raw=True), policy)
            return _embedded(result)
        result = await fetch_pages(
            _page_request(match.tenant, url, 0),
            policy,
            send,
            next_page=lambda answers: _next_page(match.tenant, url, answers),
            merge=_merge,
            rows=_rows,
        )
        return serving(result, _rows)

    def shapes(self, match: AdapterMatch, answer: JsonValue, /) -> tuple[Shape, ...]:
        if match.page_kind == "detail":
            return (_posted_on_board(match.tenant, answer),)
        listed = replace(_LISTED, prefixes={"url": f"{_board(match.tenant)}/OpportunityDetail?opportunityId="})
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _posted_on_board(tenant: str, answer: JsonValue) -> Shape:
    """The detail shape, its `datePosted` the `ExternalPostedDate` of the membership of the board the page is on (its
    `JobBoardId`, the board's UUID, RFC 9562 §4: compared case-insensitively) when the opportunity states one, else
    the requisition's `PostedDate`."""
    board = tenant.split("/")[2].lower()
    memberships = answer.get(_MEMBERSHIPS) if isinstance(answer, dict) else None
    for i, membership in enumerate(memberships if isinstance(memberships, list) else []):
        if not isinstance(membership, dict) or str(membership.get("JobBoardId", "")).lower() != board:
            continue
        if isinstance(membership.get("ExternalPostedDate"), str):
            dated = {**_DETAIL.properties, "datePosted": (_MEMBERSHIPS, i, "ExternalPostedDate")}
            return replace(_DETAIL, properties=dated)
    return _DETAIL


def _is_opportunity(name: str, value: str) -> bool:
    return name == "opportunityId" and _UUID.fullmatch(value) is not None


def _board(tenant: str) -> str:
    host, company, board = tenant.split("/")
    return f"https://{host}/{company}/JobBoard/{board}"


def _search(tenant: str) -> str:
    return f"{_board(tenant)}/JobBoardView/LoadSearchResults"


def _detail_url(tenant: str, opportunity: str) -> str:
    return f"{_board(tenant)}/OpportunityDetail?opportunityId={opportunity}"


def _page_request(tenant: str, url: str, skip: int) -> JsonRequest:
    search = {
        "opportunitySearch": {
            "Top": PAGE_SIZE,
            "Skip": skip,
            "QueryString": "",
            "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}],
            "Filters": [],
        },
        "matchCriteria": _MATCH_CRITERIA,
    }
    return JsonRequest(url=_search(tenant), page_url=url, method="POST", headers=_JSON, body=json.dumps(search))


def _opportunities(answer: JsonValue) -> list[JsonValue]:
    found = answer.get("opportunities") if isinstance(answer, dict) else None
    return found if isinstance(found, list) else []


def _rows(answer: JsonValue) -> int:
    return len(_opportunities(answer))


def _next_page(tenant: str, url: str, answers: Sequence[JsonValue]) -> JsonRequest | None:
    """The page after `answers`, until the skip reaches the `totalCount` every page states."""
    skip = sum(_rows(answer) for answer in answers)
    total = answers[-1].get("totalCount") if isinstance(answers[-1], dict) else None
    if _rows(answers[-1]) == 0 or not isinstance(total, int) or skip >= total:
        return None
    return _page_request(tenant, url, skip)


def _merge(answers: Sequence[JsonValue]) -> JsonValue:
    first = answers[0]
    return {
        **(first if isinstance(first, dict) else {}),
        "opportunities": [o for a in answers for o in _opportunities(a)],
    }


def _embedded(result: FetchResult) -> FetchResult:
    """`result`, its capture the opportunity the page embeds; `NOT_SERVED` when the page embeds none."""
    if result.block_class != "ok":
        return result
    text = result.bundle.body.decode("utf-8", errors="replace")
    start = text.find(_EMBEDDED)
    if start < 0:
        return as_error(result, NOT_SERVED)
    try:
        found, _ = json.JSONDecoder().raw_decode(text, start + len(_EMBEDDED))
    except ValueError:
        return as_error(result, NOT_SERVED)
    return recorded(result, found) if isinstance(found, dict) else as_error(result, NOT_SERVED)
