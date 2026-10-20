"""Recruitee hosted career sites through the offers API of the company (owner delegation 2026-10-17).

Endpoints, the public JSON the platform's own career sites load (verified against live answers of several companies,
2026-10-17), unauthenticated: `GET /api/offers/` lists a company's published offers in full, `{"offers": [{"title",
"slug", "guid", "description", "location", "employment_type_code", "published_at", "careers_url", "salary", ...}]}`;
`GET /api/offers/{slug}` answers one offer, `{"offer": {...}}`. The list is not paged. A company is the host
`{company}.recruitee.com`: its list is `/` or `/o`, an offer `/o/{slug}`.
"""

import re
from dataclasses import replace
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Section, Shape
from crawlerai.db.models import PageKind

DOMAIN: Final = "recruitee.com"

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)

# An offer as a schema.org JobPosting. `salary` states its amounts only when the company shows them, so the node is
# there only when `min` is; `period` is the unit the amounts are for. The hiring organization is the offer's own
# `company_name`, so its node is a view of the offer anchored at that member. Its description is the offer's
# `description` and then its `requirements`, both HTML, as the offer's page shows them.
_SALARY: Final = Shape(
    type="MonetaryAmount",
    at=("salary",),
    anchor=("min",),
    properties={"currency": ("currency",), "minValue": ("min",), "maxValue": ("max",), "unitText": ("period",)},
)
_EMPLOYER: Final = Shape(type="Organization", properties={"name": ("company_name",)}, anchor=("company_name",))
_OFFER: Final = Shape(
    type="JobPosting",
    properties={
        "title": ("title",),
        "url": ("careers_url",),
        "datePosted": ("published_at",),
        "employmentType": ("employment_type_code",),
        "jobLocation": ("location",),
        "identifier": ("guid",),
    },
    sections={"description": (Section(body=("description",)), Section(body=("requirements",)))},
    nodes={"baseSalary": (_SALARY,), "hiringOrganization": (_EMPLOYER,)},
)
# The offers answer is one offer under `offer`; the list answer lists them under `offers` (schema.org ItemList).
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (replace(_OFFER, at=("offer",)),),
    "listing": (Shape(type="ItemList", nodes={"itemListElement": (replace(_OFFER, at=("offers", ALL)),)}),),
}


class Recruitee:
    name: Final = "recruitee"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        host = (parts.hostname or "").split(".")
        if parts.scheme.lower() not in {"http", "https"} or len(host) != 3 or ".".join(host[1:]) != DOMAIN:
            return None
        if not _LABEL.fullmatch(host[0]):
            return None
        match parts.path.strip("/").split("/"), parts.query:
            case (([""] | ["o"]), ""):
                return AdapterMatch(tenant=host[0], page_kind="listing")
            case ["o", slug], _ if PATH_SEGMENT.fullmatch(slug):
                return AdapterMatch(tenant=host[0], page_kind="detail", item=slug)
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{_api(match.tenant)}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career site URL this adapter detects")
        endpoint = f"{_api(match.tenant)}/" + ("" if match.item is None else quote(match.item, safe=""))
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES[match.page_kind]


def _api(company: str) -> str:
    return f"https://{company}.{DOMAIN}/api/offers"
