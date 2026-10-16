"""Greenhouse hosted job boards through the Greenhouse Job Board API (SPEC-02 §4.9).

Endpoints, verified against the vendor's Job Board API documentation (docs.greenhouse.io/job-board.html,
2026-10-13): `GET /v1/boards/{board_token}/jobs?content=true` lists a board's jobs with their descriptions;
`GET /v1/boards/{board_token}/jobs/{job_id}` retrieves one job. The board token is the token in the hosted job
board's URL.

Only the hosted boards whose API host the documentation names are detected; a board on another regional host is
left to the generic rungs rather than sent to an API that may not hold it.
"""

import re
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qs, quote, urlsplit

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Shape
from crawlerai.db.models import PageKind

API: Final = "https://boards-api.greenhouse.io/v1/boards"
# The hosted job board hosts. A board is `/{board_token}`, a job `/{board_token}/jobs/{job_id}`; the embedded board
# is `/embed/job_board?for={board_token}`, an embedded job `/embed/job_app?for={board_token}&token={job_id}`.
BOARD_HOSTS: Final = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})

# A board token is a `PATH_SEGMENT`; a job id is the API's integer id, in ASCII digits.
_TOKEN = PATH_SEGMENT
_JOB_ID = re.compile(r"\d+", re.ASCII)

# A job object as a schema.org JobPosting (Job Board API documentation, job object): property -> the member names
# leading to its value. `content` is the description as HTML-escaped HTML; `first_published` and `company_name` are in
# the retrieve-job response only, so a listing has no value for them. The hiring organization is named by the job
# object's own `company_name`, so its node is a view of the job object anchored at that member.
_ORGANIZATION: Final = Shape(type="Organization", properties={"name": ("company_name",)}, anchor=("company_name",))
_JOB: Final = Shape(
    type="JobPosting",
    properties={
        "title": ("title",),
        "url": ("absolute_url",),
        "description": ("content",),
        "jobLocation": ("location", "name"),
        "datePosted": ("first_published",),
        "dateModified": ("updated_at",),
    },
    nodes={"hiringOrganization": (_ORGANIZATION,)},
)
# The retrieve-job response is one job object; the list-jobs response lists them in its `jobs` array (schema.org
# ItemList, `itemListElement`).
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (_JOB,),
    "listing": (Shape(type="ItemList", nodes={"itemListElement": (replace(_JOB, at=("jobs", ALL)),)}),),
}


class Greenhouse:
    name: Final = "greenhouse"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname not in BOARD_HOSTS:
            return None
        segments = parts.path.strip("/").split("/")
        if segments[0] == "embed":
            return _embedded(segments[1:], parse_qs(parts.query))
        return _hosted(segments)

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # The board's own endpoints, as `fetch` asks them: `{API}/{board_token}/jobs...`.
        return endpoint.startswith(f"{API}/{quote(match.tenant, safe='')}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        endpoint = f"{API}/{quote(match.tenant, safe='')}/jobs"
        endpoint += "?content=true" if match.item is None else f"/{match.item}"
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, page_kind: PageKind) -> tuple[Shape, ...]:
        return _SHAPES[page_kind]


def _hosted(segments: list[str]) -> AdapterMatch | None:
    match segments:
        case [token] if _TOKEN.fullmatch(token):
            return AdapterMatch(tenant=token, page_kind="listing")
        case [token, "jobs", job_id] if _TOKEN.fullmatch(token) and _JOB_ID.fullmatch(job_id):
            return AdapterMatch(tenant=token, page_kind="detail", item=job_id)
        case _:
            return None


def _embedded(segments: list[str], query: dict[str, list[str]]) -> AdapterMatch | None:
    match segments, query.get("for"), query.get("token"):
        case ["job_board"], [token], _ if _TOKEN.fullmatch(token):
            return AdapterMatch(tenant=token, page_kind="listing")
        case ["job_app"], [token], [job_id] if _TOKEN.fullmatch(token) and _JOB_ID.fullmatch(job_id):
            return AdapterMatch(tenant=token, page_kind="detail", item=job_id)
        case _:
            return None
