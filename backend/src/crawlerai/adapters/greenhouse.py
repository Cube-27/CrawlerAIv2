"""Greenhouse hosted job boards through the Greenhouse Job Board API (SPEC-02 §4.9).

Endpoints, verified against the vendor's Job Board API documentation (docs.greenhouse.io/job-board.html,
2026-10-13): `GET /v1/boards/{board_token}/jobs?content=true` lists a board's jobs with their descriptions;
`GET /v1/boards/{board_token}/jobs/{job_id}` retrieves one job. The board token is the token in the hosted job
board's URL.

Only the hosted boards whose API host the documentation names are detected; a board on another regional host is
left to the generic rungs rather than sent to an API that may not hold it.
"""

import re
from collections.abc import Mapping
from typing import Final
from urllib.parse import parse_qs, quote, urlsplit

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch
from crawlerai.db.models import PageKind

API: Final = "https://boards-api.greenhouse.io/v1/boards"
# The hosted job board hosts. A board is `/{board_token}`, a job `/{board_token}/jobs/{job_id}`; the embedded board
# is `/embed/job_board?for={board_token}`, an embedded job `/embed/job_app?for={board_token}&token={job_id}`.
BOARD_HOSTS: Final = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})

# A board token is one path segment of RFC 3986 §2.3 unreserved characters, other than a dot-segment (`.`, `..`,
# RFC 3986 §5.2.4), which would move the API path; a job id is the API's integer id.
_TOKEN = re.compile(r"(?!\.+$)[A-Za-z0-9._~-]+")
_JOB_ID = re.compile(r"[0-9]+")

# schema.org JobPosting property -> the member names leading to its value in a job object (Job Board API
# documentation, job object). `content` is the description as HTML-escaped HTML; `first_published` and `company_name`
# are in the retrieve-job response only, so a listing has no value for them.
_JOB_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "JobPosting.title": ("title",),
    "JobPosting.url": ("absolute_url",),
    "JobPosting.description": ("content",),
    "JobPosting.jobLocation": ("location", "name"),
    "JobPosting.datePosted": ("first_published",),
    "JobPosting.dateModified": ("updated_at",),
    "JobPosting.hiringOrganization.name": ("company_name",),
}
# JSONPath (RFC 9535) bracket notation, the form of its Normalized Paths (§2.7): the list-jobs response holds the
# jobs in its `jobs` array.
_ROOT: Final[dict[PageKind, str]] = {"detail": "$", "listing": "$['jobs'][*]"}


class Greenhouse:
    name: Final = "greenhouse"

    def __init__(self, fetch: JsonFetcher) -> None:
        self._fetch = fetch

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname not in BOARD_HOSTS:
            return None
        segments = parts.path.strip("/").split("/")
        if segments[0] == "embed":
            return _embedded(segments[1:], parse_qs(parts.query))
        return _hosted(segments)

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        endpoint = f"{API}/{quote(match.tenant, safe='')}/jobs"
        endpoint += "?content=true" if match.item is None else f"/{match.item}"
        return await self._fetch(JsonRequest(url=endpoint, page_url=url), policy)

    def map(self, schema_org: Mapping[str, str], page_kind: PageKind) -> dict[str, str]:
        # The member names are plain ASCII, so they need no escaping inside single quotes (RFC 9535 §2.3.1.1).
        root = _ROOT[page_kind]
        return {
            field: root + "".join(f"['{name}']" for name in _JOB_FIELDS[path])
            for field, path in schema_org.items()
            if path in _JOB_FIELDS
        }


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
