"""Ashby hosted job boards through the Ashby Job Postings API (owner delegation 2026-10-17).

Endpoint, from the vendor's public Job Postings API documentation (developers.ashbyhq.com, "Job Postings", verified
against live answers of several boards, 2026-10-17), unauthenticated: `GET /posting-api/job-board/{board}` lists a
board's listed postings with their descriptions, `{"jobs": [{"id", "title", "location", "secondaryLocations",
"employmentType", "publishedAt", "jobUrl", "descriptionHtml", "compensation", ...}]}`, and with
`includeCompensation=true` each posting's compensation. The API has no endpoint for one posting, so a posting's own
page takes the page rungs. The board is the first path segment of the hosted board's URL, `/{board}`.
"""

from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Shape

API: Final = "https://api.ashbyhq.com/posting-api/job-board"
BOARD_HOST: Final = "jobs.ashbyhq.com"

# A posting as a schema.org JobPosting: `location` is the primary location and `secondaryLocations` the others, each
# as written; `interval` of a compensation component is the period its amounts are for. A component with no `minValue`
# (equity, for one) states no amount, so its node is there only when the member is.
_SALARY: Final = Shape(
    type="MonetaryAmount",
    at=("compensation", "summaryComponents", ALL),
    anchor=("minValue",),
    properties={
        "currency": ("currencyCode",),
        "minValue": ("minValue",),
        "maxValue": ("maxValue",),
        "unitText": ("interval",),
    },
)
_POSTING: Final = Shape(
    type="JobPosting",
    at=("jobs", ALL),
    properties={
        "title": ("title",),
        "url": ("jobUrl",),
        "description": ("descriptionHtml",),
        "datePosted": ("publishedAt",),
        "employmentType": ("employmentType",),
        "jobLocation": ("location",),
        "identifier": ("id",),
    },
    also={"jobLocation": (("secondaryLocations", ALL, "location"),)},
    nodes={"baseSalary": (_SALARY,)},
)
_SHAPES: Final = (Shape(type="ItemList", nodes={"itemListElement": (_POSTING,)}),)


class Ashby:
    name: Final = "ashby"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname != BOARD_HOST or parts.query:
            return None
        match parts.path.strip("/").split("/"):
            case [board] if PATH_SEGMENT.fullmatch(board):
                return AdapterMatch(tenant=board, page_kind="listing")
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{API}/{quote(match.tenant, safe='')}?")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        return await send(
            JsonRequest(url=f"{API}/{quote(match.tenant, safe='')}?includeCompensation=true", page_url=url), policy
        )

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES
