"""Rippling hosted job boards through the board API of the company (owner delegation 2026-10-17).

Endpoints, the public JSON the platform's own job boards load (verified against live answers of several boards,
2026-10-17), unauthenticated: `GET /platform/api/ats/v1/board/{board}/jobs` lists a board's jobs without their
descriptions, `[{"uuid", "name", "department", "url", "workLocation"}]`, not paged; `GET .../jobs/{uuid}` answers one
job with its description and pay, `{"uuid", "name", "description": {"company", "role"}, "employmentType",
"createdOn", "workLocations", "payRangeDetails", "companyName", ...}`. A board is `/{board}/jobs` (or `/{board}`) on
the hosted boards' host, a job `/{board}/jobs/{uuid}`.
"""

import re
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Shape
from crawlerai.db.models import PageKind

BOARD_HOST: Final = "ats.rippling.com"
API: Final = "https://api.rippling.com/platform/api/ats/v1/board"

# A job id is a UUID (RFC 9562 §4), in hexadecimal digits and hyphens.
_UUID: Final = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", re.ASCII)

# A listed job as a schema.org JobPosting: `url` is the job's page.
_LISTED: Final = Shape(
    type="JobPosting",
    at=(ALL,),
    properties={
        "title": ("name",),
        "url": ("url",),
        "jobLocation": ("workLocation", "label"),
        "identifier": ("uuid",),
    },
)
# A job's answer: `description.role` is the description of the role as HTML; `workLocations` are the places as written;
# `employmentType.id` is the human-readable employment type (`label` is the platform's internal code for it); a pay
# range with no `rangeStart` states no amount. The hiring organization is the job's own `companyName`.
_PAY: Final = Shape(
    type="MonetaryAmount",
    at=("payRangeDetails", ALL),
    anchor=("rangeStart",),
    properties={
        "currency": ("currency",),
        "minValue": ("rangeStart",),
        "maxValue": ("rangeEnd",),
        "unitText": ("frequency",),
    },
)
_EMPLOYER: Final = Shape(type="Organization", properties={"name": ("companyName",)}, anchor=("companyName",))
_JOB: Final = Shape(
    type="JobPosting",
    properties={
        "title": ("name",),
        "url": ("url",),
        "description": ("description", "role"),
        "datePosted": ("createdOn",),
        "employmentType": ("employmentType", "id"),
        "jobLocation": ("workLocations", ALL),
        "identifier": ("uuid",),
    },
    nodes={"baseSalary": (_PAY,), "hiringOrganization": (_EMPLOYER,)},
)
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (_JOB,),
    "listing": (Shape(type="ItemList", nodes={"itemListElement": (_LISTED,)}),),
}


class Rippling:
    name: Final = "rippling"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname != BOARD_HOST:
            return None
        match parts.path.strip("/").split("/"), parts.query:
            case (([board] | [board, "jobs"]), "") if PATH_SEGMENT.fullmatch(board):
                return AdapterMatch(tenant=board, page_kind="listing")
            case [board, "jobs", job], _ if PATH_SEGMENT.fullmatch(board) and _UUID.fullmatch(job):
                return AdapterMatch(tenant=board, page_kind="detail", item=job)
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{API}/{quote(match.tenant, safe='')}/jobs")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        endpoint = f"{API}/{quote(match.tenant, safe='')}/jobs"
        if match.item is not None:
            endpoint += f"/{match.item}"
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES[match.page_kind]
