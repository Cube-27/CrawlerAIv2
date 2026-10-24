"""BambooHR hosted career sites through the careers API of the company (owner delegation 2026-10-17).

Endpoints, the public JSON the platform's own career sites load (verified against live answers of several companies,
2026-10-17), unauthenticated: `GET /careers/list` lists a company's open jobs without their descriptions, `{"meta":
{"totalCount"}, "result": [{"id", "jobOpeningName", "departmentLabel", "employmentStatusLabel", "location": {"city",
"state"}, "isRemote"}]}`, not paged; `GET /careers/{id}/detail` answers one job, `{"result": {"jobOpening":
{"jobOpeningName", "description", "datePosted", "employmentStatusLabel", "compensation", "location",
"jobOpeningShareUrl"}}}`. A company is the host `{company}.bamboohr.com`: its list is `/careers`, a job `/careers/{id}`.
A company without a careers site answers a redirect to the platform's own site, which is not JSON: not served.
"""

import re
from dataclasses import replace
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from snowcrawl.acquire.api import JsonFetcher, JsonRequest
from snowcrawl.acquire.outcome import as_error
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.adapters.answer import serving
from snowcrawl.adapters.base import ALL, NOT_SERVED, AdapterMatch, Shape

DOMAIN: Final = "bamboohr.com"

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)
# A job id is the ASCII digits of the job's path.
_ID: Final = re.compile(r"\d+", re.ASCII)

# A job as a schema.org JobPosting: its place is a Place of the city and state the API gives in `location` (the detail
# adds the postal code and country), or, where a company states it in the applicant tracking system's own form, of
# `atsLocation` (city, state, country); each is a node only when it states its city (`location`) or country. A
# listed job's page is `/careers/{id}` on the company's host (the prefix `shapes` puts before `id`); the detail answer
# gives `jobOpeningShareUrl`.
_PLACE: Final = Shape(
    type="Place",
    at=("location",),
    anchor=("city",),
    nodes={
        "address": (
            Shape(
                type="PostalAddress",
                properties={
                    "addressLocality": ("city",),
                    "addressRegion": ("state",),
                    "postalCode": ("postalCode",),
                    "addressCountry": ("addressCountry",),
                },
            ),
        )
    },
)
_ATS_PLACE: Final = Shape(
    type="Place",
    at=("atsLocation",),
    anchor=("country",),
    nodes={
        "address": (
            Shape(
                type="PostalAddress",
                properties={"addressLocality": ("city",), "addressRegion": ("state",), "addressCountry": ("country",)},
            ),
        )
    },
)
_PLACES: Final = (_PLACE, _ATS_PLACE)
_COMMON: Final = {"title": ("jobOpeningName",), "employmentType": ("employmentStatusLabel",)}
_LISTED: Final = Shape(
    type="JobPosting",
    at=("result", ALL),
    properties={**_COMMON, "identifier": ("id",), "url": ("id",)},
    nodes={"jobLocation": _PLACES},
)
# `compensation` is the text the company shows for the pay, `null` when it shows none.
_DETAIL: Final = Shape(
    type="JobPosting",
    at=("result", "jobOpening"),
    properties={
        **_COMMON,
        "url": ("jobOpeningShareUrl",),
        "description": ("description",),
        "datePosted": ("datePosted",),
        "baseSalary": ("compensation",),
    },
    nodes={"jobLocation": _PLACES},
)


class BambooHR:
    name: Final = "bamboohr"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        host = (parts.hostname or "").split(".")
        if parts.scheme.lower() not in {"http", "https"} or len(host) != 3 or ".".join(host[1:]) != DOMAIN:
            return None
        if not _LABEL.fullmatch(host[0]):
            return None
        match parts.path.strip("/").split("/"), parts.query:
            case ["careers"], "":
                return AdapterMatch(tenant=host[0], page_kind="listing")
            case ["careers", job], _ if _ID.fullmatch(job):
                return AdapterMatch(tenant=host[0], page_kind="detail", item=job)
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{_careers(match.tenant)}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career site URL this adapter detects")
        endpoint = f"{_careers(match.tenant)}/" + ("list" if match.item is None else f"{match.item}/detail")
        result = await send(JsonRequest(url=endpoint, page_url=url), policy)
        if result.attempts[-1].error == "decode_error":  # a redirect to the platform's site: no careers site
            return as_error(result, NOT_SERVED)
        return result if match.item is not None else serving(result, _rows)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        if match.page_kind == "detail":
            return (_DETAIL,)
        listed = replace(_LISTED, prefixes={"url": f"{_careers(match.tenant)}/"})
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _careers(company: str) -> str:
    return f"https://{company}.{DOMAIN}/careers"


def _rows(answer: JsonValue) -> int:
    result = answer.get("result") if isinstance(answer, dict) else None
    return len(result) if isinstance(result, list) else 0
