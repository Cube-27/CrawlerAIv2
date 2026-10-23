"""Lever hosted job sites through the Lever Postings API (acquisition spec).

Endpoints, verified against the vendor's Postings API documentation (github.com/lever/postings-api, README,
2026-10-13): `GET /v0/postings/{site}?mode=json` lists a site's published postings as a JSON array;
`GET /v0/postings/{site}/{posting_id}` retrieves one posting. The global and EU instances each have their own job
site host and API host. The site name is the first path segment of the job site's URL.
"""

from collections.abc import Mapping
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, PATH_SEGMENT, AdapterMatch, Section, Shape, apply_action
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
# leading to its value. The description is the posting's text as its hosted page shows it, which the API splits over
# members (README, "Response"): `description`, the opening and body as HTML; then each of `lists`, an extra list
# (requirements, benefits) whose `text` names it and whose `content` is its list items as HTML; then `additional`, the
# optional closing content as HTML. On a posting's page, `applyUrl`, its application form, is the `target` of its
# schema.org ApplyAction (D-1493). `createdAt` is the posting's creation time, a timestamp in milliseconds since the
# Unix epoch (Lever Data API documentation, hire.lever.co/developer/documentation, "Postings"): its `datePosted`. The
# documentation names no company name, so that property has no value here.
_POSTING: Final = Shape(
    type="JobPosting",
    properties={
        "title": ("text",),
        "url": ("hostedUrl",),
        "jobLocation": ("categories", "location"),
        "datePosted": ("createdAt",),
    },
    epoch_ms=frozenset({"datePosted"}),
    sections={
        "description": (
            Section(body=("description",)),
            Section(at=("lists", ALL), heading=("text",), body=("content",)),
            Section(body=("additional",)),
        )
    },
)
# The retrieve response is one posting; the list response is an array of postings (schema.org ItemList,
# `itemListElement`).
_SHAPES: Final[dict[PageKind, tuple[Shape, ...]]] = {
    "detail": (replace(_POSTING, nodes={"potentialAction": (apply_action("applyUrl"),)}),),
    "listing": (Shape(type="ItemList", nodes={"itemListElement": (replace(_POSTING, at=(ALL,)),)}),),
}


class Lever:
    name: Final = "lever"

    def detect(self, url: str) -> AdapterMatch | None:
        found = _detect(url)
        return None if found is None else found[1]

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # The site's own endpoints, as `fetch` asks them: `{api}/{site}?mode=json` and `{api}/{site}/{posting_id}`.
        site = quote(match.tenant, safe="")
        return any(endpoint.startswith((f"{api}/{site}?", f"{api}/{site}/")) for api in JOB_SITE_APIS.values())

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        found = _detect(url)
        if found is None:
            raise ValueError("not a job site URL this adapter detects")
        api, match = found
        endpoint = f"{api}/{quote(match.tenant, safe='')}"
        endpoint += "?mode=json" if match.item is None else f"/{quote(match.item, safe='')}"
        return await send(JsonRequest(url=endpoint, page_url=url), policy)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES[match.page_kind]


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
