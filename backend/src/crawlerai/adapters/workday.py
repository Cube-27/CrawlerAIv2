"""Workday career sites through the JSON endpoints their own pages call (owner, 2026-10-16).

Workday publishes no documentation for these endpoints. They are the requests a Workday career site's page sends to
render its job list and its job pages, verified against live answers of several tenants (2026-10-16), unauthenticated:
- `POST /wday/cxs/{tenant}/{site}/jobs` with `FIRST_PAGE` answers the site's first page of postings,
  `{"total", "jobPostings": [{"title", "externalPath", "locationsText", "postedOn", ...}]}`;
- `GET /wday/cxs/{tenant}/{site}/job/{location}/{slug}` answers one posting,
  `{"jobPostingInfo": {"title", "jobDescription", "location", "additionalLocations", "startDate", "timeType",
  "externalUrl", ...}, "hiringOrganization": {"name", ...}}`.

A career site is `https://{tenant}.{data center}.myworkdayjobs.com/[{locale}/]{site}`, or on the shared host
`https://{data center}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}`; a job page is the site's URL followed
by `/job/{location}/{slug}`, the posting's `externalPath`. The endpoints are on the page's own host. The match's tenant
is the site's root, its URL without the locale, which is what a posting's `externalUrl` starts with.
"""

import json
import re
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, AdapterMatch, Shape
from crawlerai.storage.capture_bundle import HeaderList

JOBS_DOMAIN: Final = "myworkdayjobs.com"
SITES_DOMAIN: Final = "myworkdaysite.com"

# The body the career site's own list page sends for its first page: no facet, no search text, 20 postings.
FIRST_PAGE: Final[dict[str, JsonValue]] = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)
# The locale a career site's path may start with: a language and a region subtag (BCP 47, RFC 5646 §2.1), the form
# Workday writes them in.
_LOCALE: Final = re.compile(r"[a-z]{2}-[A-Z]{2}", re.ASCII)
# A path segment of RFC 3986 unreserved characters and percent-encoded octets (§2.1, §2.3), other than a dot-segment
# (§5.2.4), which would move the endpoint's path; it goes into the endpoint as it is written.
_SEGMENT: Final = re.compile(r"(?!\.+$)(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+", re.ASCII)


@dataclass(frozen=True)
class _Page:
    api: str  # the site's endpoint base, `/wday/cxs/{tenant}/{site}` on the page's host
    locale: str | None
    match: AdapterMatch


# A listed posting as a schema.org JobPosting: `externalPath` is the job page's path under the site's root (the match's
# tenant, prefixed in `shapes`); `locationsText` is the location as the list writes it.
_LISTED: Final = Shape(
    type="JobPosting",
    at=("jobPostings", ALL),
    properties={"title": ("title",), "url": ("externalPath",), "jobLocation": ("locationsText",)},
)
_LISTING: Final = Shape(type="ItemList", nodes={"itemListElement": (_LISTED,)})
# A posting's answer as a schema.org JobPosting: `startDate` is the date the posting was published, the `datePosted`
# the job page's own JSON-LD states; `location` is the primary location and `additionalLocations` the others, each as
# written; the hiring organization is the answer's `hiringOrganization`.
_INFO: Final = ("jobPostingInfo",)
_JOB: Final = Shape(
    type="JobPosting",
    properties={
        "title": (*_INFO, "title"),
        "description": (*_INFO, "jobDescription"),
        "url": (*_INFO, "externalUrl"),
        "datePosted": (*_INFO, "startDate"),
        "employmentType": (*_INFO, "timeType"),
        "jobLocation": (*_INFO, "location"),
    },
    also={"jobLocation": ((*_INFO, "additionalLocations", ALL),)},
    nodes={
        "hiringOrganization": (Shape(type="Organization", at=("hiringOrganization",), properties={"name": ("name",)}),)
    },
)


class Workday:
    name: Final = "workday"

    def detect(self, url: str) -> AdapterMatch | None:
        page = _page(url)
        return None if page is None else page.match

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # The site's own endpoints, as `fetch` asks them: `{api}/jobs` and `{api}/job/...`.
        site = _page(match.tenant)
        return site is not None and endpoint.startswith(f"{site.api}/")

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        page = _page(url)
        if page is None:
            raise ValueError("not a career site URL this adapter detects")
        # RFC 9110 §12.5.4: the answer in the language of the page's locale, as the page asks it.
        language: HeaderList = () if page.locale is None else (("Accept-Language", page.locale),)
        if page.match.item is not None:
            request = JsonRequest(url=f"{page.api}/{page.match.item}", page_url=url, headers=language)
        else:
            request = JsonRequest(
                url=f"{page.api}/jobs",
                page_url=url,
                method="POST",
                headers=(("Content-Type", "application/json"), *language),
                body=json.dumps(FIRST_PAGE),
            )
        return await send(request, policy)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        if match.page_kind == "detail":
            return (_JOB,)
        listed = replace(_LISTED, prefixes={"url": match.tenant})
        return (replace(_LISTING, nodes={"itemListElement": (listed,)}),)


def _page(url: str) -> _Page | None:
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or parts.hostname is None:
        return None
    segments = parts.path.strip("/").split("/")
    locale = segments[0] if _LOCALE.fullmatch(segments[0]) else None
    site = _site(parts.hostname, segments[1:] if locale else segments)
    if site is None:
        return None
    tenant, base, rest = site
    origin = f"https://{parts.hostname}"
    match rest:
        # A list URL with a query shows a filter or a search of the list, which the first page does not reproduce.
        case [] if not parts.query:
            item = None
        case ["job", place, slug] if _SEGMENT.fullmatch(place) and _SEGMENT.fullmatch(slug):
            item = f"job/{place}/{slug}"
        case _:
            return None
    match = AdapterMatch(tenant=origin + base, page_kind="listing" if item is None else "detail", item=item)
    return _Page(api=f"{origin}/wday/cxs/{tenant}/{base.rsplit('/', 1)[1]}", locale=locale, match=match)


def _site(host: str, segments: list[str]) -> tuple[str, str, list[str]] | None:
    """The tenant, the site's path on `host` and the path segments after it."""
    match host.split("."), segments:
        case [tenant, dc, *domain], [site, *rest] if (
            ".".join(domain) == JOBS_DOMAIN and _labels(tenant, dc) and _SEGMENT.fullmatch(site)
        ):
            return tenant, f"/{site}", rest
        case [dc, *domain], ["recruiting", tenant, site, *rest] if (
            ".".join(domain) == SITES_DOMAIN and _labels(dc) and _SEGMENT.fullmatch(tenant) and _SEGMENT.fullmatch(site)
        ):
            return tenant, f"/recruiting/{tenant}/{site}", rest
        case _:
            return None


def _labels(*labels: str) -> bool:
    return all(_LABEL.fullmatch(label) for label in labels)
