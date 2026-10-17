"""SmartRecruiters hosted career sites through the Posting API (owner delegation 2026-10-17).

Endpoints, from the vendor's public Posting API documentation (developers.smartrecruiters.com, "Posting API",
verified against live answers of several companies, 2026-10-17), unauthenticated: `GET /v1/companies/{company}/postings`
lists a company's postings in pages, `{"offset", "limit", "totalFound", "content": [{"id", "name", "refNumber",
"releasedDate", "typeOfEmployment", "location", "company", ...}]}` (`limit` at most 100); `GET .../postings/{id}`
answers one posting with its ad, `{..., "postingUrl", "jobAd": {"sections": {"jobDescription": {"text"}, ...}}}`.
The company identifier is case-sensitive. A company's site is `/{company}` on the platform's hosted career hosts, a
posting `/{company}/{id}[-{slug}]`, `id` its digits.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import replace
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, NOT_SERVED, PATH_SEGMENT, AdapterMatch, Shape
from crawlerai.adapters.paging import fetch_pages

API: Final = "https://api.smartrecruiters.com/v1/companies"
# The platform's hosted career hosts; a posting's page is on the first.
SITE_HOST: Final = "jobs.smartrecruiters.com"
SITE_HOSTS: Final = frozenset({SITE_HOST, "careers.smartrecruiters.com"})
# The most postings the API answers per page.
PAGE_SIZE: Final = 100

# A posting id is the ASCII digits the page's path starts with, before an optional `-{slug}`.
_POSTING: Final = re.compile(r"(\d+)(?:-.*)?", re.ASCII)

# A posting as a schema.org JobPosting: a listed posting's page is `/{company}/{id}` on the career host (the prefix
# `shapes` puts before `id`); the posting's own answer gives `postingUrl`. `jobDescription` is the posting's own text
# as HTML. The hiring organization is the posting's `company`.
_EMPLOYER: Final = Shape(type="Organization", at=("company",), properties={"name": ("name",)})
_COMMON: Final = {
    "title": ("name",),
    "datePosted": ("releasedDate",),
    "employmentType": ("typeOfEmployment", "label"),
    "jobLocation": ("location", "fullLocation"),
    "identifier": ("id",),
}
_LISTED: Final = Shape(
    type="JobPosting",
    at=("content", ALL),
    properties={**_COMMON, "url": ("id",)},
    nodes={"hiringOrganization": (_EMPLOYER,)},
)
_DETAIL: Final = Shape(
    type="JobPosting",
    properties={
        **_COMMON,
        "url": ("postingUrl",),
        "description": ("jobAd", "sections", "jobDescription", "text"),
    },
    nodes={"hiringOrganization": (_EMPLOYER,)},
)


class SmartRecruiters:
    name: Final = "smartrecruiters"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname not in SITE_HOSTS:
            return None
        match parts.path.strip("/").split("/"), parts.query:
            case [company], "" if PATH_SEGMENT.fullmatch(company):
                return AdapterMatch(tenant=company, page_kind="listing")
            case [company, posting], _ if PATH_SEGMENT.fullmatch(company) and (found := _POSTING.fullmatch(posting)):
                return AdapterMatch(tenant=company, page_kind="detail", item=found.group(1))
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{_postings(match.tenant)}?") or endpoint.startswith(f"{_postings(match.tenant)}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career site URL this adapter detects")
        base = _postings(match.tenant)
        if match.item is not None:
            return await send(JsonRequest(url=f"{base}/{match.item}", page_url=url), policy)
        result = await fetch_pages(
            _page_request(base, url, 0),
            policy,
            send,
            next_page=lambda answers: _next_page(base, url, answers),
            merge=_merge,
            rows=_rows,
        )
        return _verdict(result)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        if match.page_kind == "detail":
            return (_DETAIL,)
        listed = replace(_LISTED, prefixes={"url": f"https://{SITE_HOST}/{match.tenant}/"})
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _postings(company: str) -> str:
    return f"{API}/{quote(company, safe='')}/postings"


def _page_request(base: str, url: str, offset: int) -> JsonRequest:
    return JsonRequest(url=f"{base}?limit={PAGE_SIZE}&offset={offset}", page_url=url)


def _content(answer: JsonValue) -> list[JsonValue]:
    content = answer.get("content") if isinstance(answer, dict) else None
    return content if isinstance(content, list) else []


def _rows(answer: JsonValue) -> int:
    return len(_content(answer))


def _next_page(base: str, url: str, answers: Sequence[JsonValue]) -> JsonRequest | None:
    """The page after `answers`, until the offset reaches the `totalFound` every page states."""
    offset = sum(_rows(answer) for answer in answers)
    total = answers[-1].get("totalFound") if isinstance(answers[-1], dict) else None
    if _rows(answers[-1]) == 0 or not isinstance(total, int) or offset >= total:
        return None
    return _page_request(base, url, offset)


def _merge(answers: Sequence[JsonValue]) -> JsonValue:
    first = answers[0]
    return {**(first if isinstance(first, dict) else {}), "content": [p for a in answers for p in _content(a)]}


def _verdict(result: FetchResult) -> FetchResult:
    """`result`, or `NOT_SERVED` when the API answered without a posting: a company it holds none for (it answers
    200 with an empty list for an unknown company)."""
    if result.block_class != "ok":
        return result
    return result if _rows(json.loads(result.bundle.body)) else as_error(result, NOT_SERVED)
