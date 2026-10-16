"""Lever hosted job sites through the Lever Postings API (SPEC-02 §4.9).

Endpoints, verified against the vendor's Postings API documentation (github.com/lever/postings-api, README,
2026-10-13): `GET /v0/postings/{site}?mode=json` lists a site's published postings as a JSON array;
`GET /v0/postings/{site}/{posting_id}` retrieves one posting. The global and EU instances each have their own job
site host and API host. The site name is the first path segment of the job site's URL.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qs, quote, urlsplit

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Shape
from crawlerai.db.models import PageKind

# Job site host -> the Postings API base of the same instance. A site is `/{site}`, a posting `/{site}/{posting_id}`.
JOB_SITE_APIS: Final[Mapping[str, str]] = {
    "jobs.lever.co": "https://api.lever.co/v0/postings",
    "jobs.eu.lever.co": "https://api.eu.lever.co/v0/postings",
}

# The list endpoint's documented filter and grouping parameters. A job site URL carrying one shows a subset of the
# postings, or groups them, which the unfiltered list does not reproduce; such a page is left to the generic rungs.
_LIST_FILTERS: Final = frozenset({"location", "commitment", "team", "department", "level", "group"})

# A posting object as a schema.org JobPosting (Postings API documentation, JSON fields): property -> the member names
# leading to its value. `description` is the opening and body as HTML. The documentation names no posting date and no
# company name, so those properties have no value here.
_POSTING: Final = Shape(
    type="JobPosting",
    properties={
        "title": ("text",),
        "url": ("hostedUrl",),
        "description": ("description",),
        "jobLocation": ("categories", "location"),
    },
)
# The retrieve response is one posting; the list response is an array of postings (schema.org ItemList,
# `itemListElement`).
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (_POSTING,),
    "listing": (Shape(type="ItemList", nodes={"itemListElement": (replace(_POSTING, at=(ALL,)),)}),),
}


class Lever:
    name: Final = "lever"

    def detect(self, url: str) -> AdapterMatch | None:
        found = _detect(url)
        return None if found is None else found[1]

    def serves(self, endpoint: str) -> bool:
        return any(endpoint.startswith(f"{api}/") for api in JOB_SITE_APIS.values())

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        found = _detect(url)
        if found is None:
            raise ValueError("not a job site URL this adapter detects")
        api, match = found
        endpoint = f"{api}/{quote(match.tenant, safe='')}"
        endpoint += "?mode=json" if match.item is None else f"/{quote(match.item, safe='')}"
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, page_kind: PageKind) -> tuple[Shape, ...]:
        return _SHAPES[page_kind]


def _detect(url: str) -> tuple[str, AdapterMatch] | None:
    """The API base of the job site's instance and the page's match."""
    parts = urlsplit(url)
    api = JOB_SITE_APIS.get(parts.hostname or "")
    if parts.scheme.lower() not in {"http", "https"} or api is None:
        return None
    match parts.path.strip("/").split("/"):
        case [site] if PATH_SEGMENT.fullmatch(site) and not _LIST_FILTERS & parse_qs(parts.query).keys():
            return api, AdapterMatch(tenant=site, page_kind="listing")
        case [site, posting] if PATH_SEGMENT.fullmatch(site) and PATH_SEGMENT.fullmatch(posting):
            return api, AdapterMatch(tenant=site, page_kind="detail", item=posting)
        case _:
            return None
