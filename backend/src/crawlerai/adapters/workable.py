"""Workable hosted job boards through the widget API of the account (owner delegation 2026-10-17).

Endpoint, the public JSON the platform's own embeddable jobs widget loads (verified against live answers of several
accounts, 2026-10-17), unauthenticated: `GET /api/v1/widget/accounts/{account}?details=true` lists an account's
published jobs with their descriptions, `{"name", "jobs": [{"title", "shortcode", "employment_type", "published_on",
"url", "description", "locations", ...}]}`. The list is not paged. The account is the first path segment of the hosted
board's URL, `/{account}`; a job's own page takes the page rungs.
"""

from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Shape

BOARD_HOST: Final = "apply.workable.com"
API: Final = f"https://{BOARD_HOST}/api/v1/widget/accounts"

# A job as a schema.org JobPosting; its places are the job's `locations`, each a Place whose address states the parts
# the widget gives separately.
_PLACE: Final = Shape(
    type="Place",
    at=("locations", ALL),
    nodes={
        "address": (
            Shape(
                type="PostalAddress",
                anchor=("country",),
                properties={"addressLocality": ("city",), "addressRegion": ("region",), "addressCountry": ("country",)},
            ),
        )
    },
)
_JOB: Final = Shape(
    type="JobPosting",
    at=("jobs", ALL),
    properties={
        "title": ("title",),
        "url": ("url",),
        "description": ("description",),
        "datePosted": ("published_on",),
        "employmentType": ("employment_type",),
        "identifier": ("shortcode",),
    },
    nodes={"jobLocation": (_PLACE,)},
)
_SHAPES: Final = (Shape(type="ItemList", nodes={"itemListElement": (_JOB,)}),)


class Workable:
    name: Final = "workable"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or parts.hostname != BOARD_HOST or parts.query:
            return None
        match parts.path.strip("/").split("/"):
            case [account] if PATH_SEGMENT.fullmatch(account):
                return AdapterMatch(tenant=account, page_kind="listing")
            case _:
                return None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint.startswith(f"{API}/{quote(match.tenant, safe='')}?")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a job board URL this adapter detects")
        endpoint = f"{API}/{quote(match.tenant, safe='')}?details=true"
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, _match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES
