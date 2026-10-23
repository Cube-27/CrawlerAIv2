"""Workday career sites through the JSON endpoints their own pages call (owner, 2026-10-16).

Workday publishes no documentation for these endpoints. They are the requests a Workday career site's page sends to
render its job list and its job pages, verified against live answers of several tenants (2026-10-16), unauthenticated:
- `POST /wday/cxs/{tenant}/{site}/jobs` with `FIRST_PAGE` answers the site's first page of postings,
  `{"total", "jobPostings": [{"title", "externalPath", "locationsText", "postedOn", ...}]}`;
- `GET /wday/cxs/{tenant}/{site}/job/{location}/{slug}` answers one posting,
  `{"jobPostingInfo": {"title", "jobDescription", "location", "additionalLocations", "startDate", "timeType",
  "externalUrl", ...}, "hiringOrganization": {"name", ...}}`.
The list pages by `limit` (at most 20: a larger one is refused) and `offset`; only the first page states `total`, and
the last page is the first with fewer than `limit` postings.

A career site is `https://{tenant}.{data center}.myworkdayjobs.com/[{locale}/]{site}`, or on the shared host
`https://{data center}.myworkdaysite.com/[{locale}/]recruiting/{tenant}/{site}`; a job page is the site's URL followed
by `/job/{location}/{slug}`, the posting's `externalPath`. The endpoints are on the page's own host. The match's tenant
is the site's root, its URL without the locale, which is what a posting's `externalUrl` starts with; a listing's rows
are the links the page renders, under the root led by the page's own locale.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import SplitResult, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, AdapterMatch, PageRefs, Shape
from crawlerai.adapters.paging import fetch_pages
from crawlerai.db.models import PageKind
from crawlerai.storage.capture_bundle import HeaderList

JOBS_DOMAIN: Final = "myworkdayjobs.com"
SITES_DOMAIN: Final = "myworkdaysite.com"

# The most postings the endpoint answers per page; the body the career site's own list page sends for its first page:
# no facet, no search text.
PAGE_SIZE: Final = 20
FIRST_PAGE: Final[dict[str, JsonValue]] = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": 0, "searchText": ""}

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)
# The locale a career site's path may start with: a language and a region subtag (BCP 47, RFC 5646 §2.1), the form
# Workday writes them in.
_LOCALE: Final = re.compile(r"[a-z]{2}-[A-Z]{2}", re.ASCII)
# A path segment of RFC 3986 unreserved characters and percent-encoded octets, other than a dot-segment,
# which would move the endpoint's path; it goes into the endpoint as it is written.
_SEGMENT: Final = re.compile(r"(?!\.+$)(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})+", re.ASCII)


@dataclass(frozen=True)
class _Page:
    api: str  # the site's endpoint base, `/wday/cxs/{tenant}/{site}` on the page's host
    locale: str | None
    match: AdapterMatch


# The schema.org type of the items the platform serves.
_POSTING: Final = "JobPosting"
# A listed posting as a schema.org JobPosting: `externalPath` is the job page's path under the site's root (the match's
# tenant under the page's locale, prefixed in `shapes`); `locationsText` is the location as the list writes it.
_LISTED: Final = Shape(
    type=_POSTING,
    at=("jobPostings", ALL),
    properties={"title": ("title",), "url": ("externalPath",), "jobLocation": ("locationsText",)},
)
_LISTING: Final = Shape(type="ItemList", nodes={"itemListElement": (_LISTED,)})
# A posting's answer as a schema.org JobPosting: `startDate` is the date the posting was published, the `datePosted`
# the job page's own JSON-LD states; `location` is the primary location and `additionalLocations` the others, each as
# written; the hiring organization is the answer's `hiringOrganization`.
_INFO: Final = ("jobPostingInfo",)
_JOB: Final = Shape(
    type=_POSTING,
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
            return await send(JsonRequest(url=f"{page.api}/{page.match.item}", page_url=url, headers=language), policy)
        return await fetch_pages(
            _list_request(page, url, language, 0),
            policy,
            send,
            next_page=lambda answers: _next_page(page, url, language, answers),
            merge=_merge,
            rows=_rows,
        )

    def referred(self, refs: PageRefs, kind: PageKind | None, types: tuple[str, ...], /) -> str | None:
        """The Workday page a page on the tenant's own host stands for. Only structure decides (HTML Standard §4.6
        links, RFC 6596 canonical, Open Graph `og:url`, RFC 9110 §15.4 redirects, which end in the final URL): a URL
        the page names as itself that this adapter detects (of the kind asked), else, for a listing of job postings
        (`types` names schema.org JobPosting), the one career site every Workday link of the page belongs to: a
        listing links to its jobs and its site, so links to two sites do not say. A link is not the page's identity
        (HTML Standard §4.6: it leads elsewhere), so a listing read for other items (a store's footer linking to its
        careers site) is not referred by its links."""
        for url in refs.own:
            if (match := self.detect(url)) is not None and kind in (None, match.page_kind):
                return url
        if kind != "listing" or _POSTING not in types:
            return None
        linked = [site for link in refs.links if (site := _linked_site(link)) is not None]
        if len({root for root, _ in linked}) != 1:
            return None
        root, locale = linked[0]
        # The locale the links agree on keeps the list in the page's language (RFC 9110 §12.5.4, `fetch`); links that
        # differ in it leave the site's root, in its default language.
        locales = {locale for _, locale in linked}
        return _localized(root, locale) if len(locales) == 1 and locale is not None else root

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        if match.page_kind == "detail":
            return (_JOB,)
        listed = replace(_LISTED, prefixes={"url": _under(match)})
        return (replace(_LISTING, nodes={"itemListElement": (listed,)}),)


def _list_request(page: _Page, url: str, language: HeaderList, offset: int) -> JsonRequest:
    body = {**FIRST_PAGE, "offset": offset}
    return JsonRequest(
        url=f"{page.api}/jobs",
        page_url=url,
        method="POST",
        headers=(("Content-Type", "application/json"), *language),
        body=json.dumps(body),
    )


def _postings(answer: JsonValue) -> list[JsonValue]:
    postings = answer.get("jobPostings") if isinstance(answer, dict) else None
    return postings if isinstance(postings, list) else []


def _rows(answer: JsonValue) -> int:
    return len(_postings(answer))


def _next_page(page: _Page, url: str, language: HeaderList, answers: Sequence[JsonValue]) -> JsonRequest | None:
    """The page after `answers`, unless the last one was short (the list's end) or the first page's `total`, which
    only it states, is reached."""
    offset = sum(_rows(answer) for answer in answers)
    total = answers[0].get("total") if isinstance(answers[0], dict) else None
    if _rows(answers[-1]) < PAGE_SIZE or (isinstance(total, int) and offset >= total):
        return None
    return _list_request(page, url, language, offset)


def _merge(answers: Sequence[JsonValue]) -> JsonValue:
    first = answers[0]
    return {**(first if isinstance(first, dict) else {}), "jobPostings": [p for a in answers for p in _postings(a)]}


def _page(url: str) -> _Page | None:
    located = _located(url)
    if located is None:
        return None
    parts, locale, (tenant, base, rest) = located
    origin = f"https://{parts.hostname}"
    match rest:
        # A list URL with a query shows a filter or a search of the list, which the first page does not reproduce.
        case [] if not parts.query:
            item = None
        case ["job", place, slug] if _SEGMENT.fullmatch(place) and _SEGMENT.fullmatch(slug):
            item = f"job/{place}/{slug}"
        case _:
            return None
    match = AdapterMatch(
        tenant=origin + base, page_kind="listing" if item is None else "detail", item=item, locale=locale
    )
    return _Page(api=f"{origin}/wday/cxs/{tenant}/{base.rsplit('/', 1)[1]}", locale=locale, match=match)


def _located(url: str) -> tuple[SplitResult, str | None, tuple[str, str, list[str]]] | None:
    """The URL's parts, its locale and the career site it is under (`_site`), whatever the path after the site."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or parts.hostname is None:
        return None
    segments = parts.path.strip("/").split("/")
    locale = segments[0] if _LOCALE.fullmatch(segments[0]) else None
    site = _site(parts.hostname, segments[1:] if locale else segments)
    return None if site is None else (parts, locale, site)


def _linked_site(url: str) -> tuple[str, str | None] | None:
    """The root URL of the career site `url` is under, and the locale `url` states: a link to the site's list with a
    tracking query, its sign-in or one of its pages names the site as a job link does."""
    located = _located(url)
    return None if located is None else (f"https://{located[0].hostname}{located[2][1]}", located[1])


def _under(match: AdapterMatch) -> str:
    """The URL a listing's job links start with: the site's root, led by the page's locale when its path has one."""
    return match.tenant if match.locale is None else _localized(match.tenant, match.locale)


def _localized(root: str, locale: str) -> str:
    """The site's root URL with its path led by `locale`, as the career site writes it."""
    parts = urlsplit(root)
    return f"{parts.scheme}://{parts.netloc}/{locale}{parts.path}"


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
