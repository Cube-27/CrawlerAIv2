"""Oracle Recruiting Cloud career sites through the Fusion HCM REST resources their own pages call (owner, 2026-10-16).

Endpoints, from the platform's documentation (REST API for Oracle Fusion Cloud HCM, "Recruiting Candidate Experience
Job Requisitions" and "Recruiting Candidate Experience Job Requisition Details", docs.oracle.com, 2026-10-16) and
verified against live answers of several tenants, unauthenticated:
- `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions?finder=findReqs;siteNumber={site},limit=...` answers a
  site's first page of requisitions: `{"items": [{"requisitionList": [{"Id", "Title", "PostedDate",
  "PrimaryLocation", ...}]}]}`;
- `GET /hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?finder=ById;siteNumber={site},Id="{id}"`
  answers one requisition: `{"items": [{"Id", "Title", "ExternalDescriptionStr", "ExternalPostedStartDate",
  "JobSchedule", "PrimaryLocation", "secondaryLocations", "LegalEmployer", ...}]}`.

A career site is `https://{pod}.fa[.{data center}].oraclecloud.com/hcmUI/CandidateExperience/{language}/sites/{site}`,
its list that URL or `.../requisitions`, a job page `.../job/{id}` (or the list's preview, `.../requisitions/preview/
{id}`). The resources are on the page's own host. The match's tenant is the site's URL, under which a requisition's
page is `/job/{Id}`.
"""

import json
import re
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import quote, urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.base import ALL, NOT_SERVED, AdapterMatch, Shape

DOMAIN: Final = "oraclecloud.com"
RESOURCES: Final = "/hcmRestApi/resources/latest"
# The size of the first page the career site's own list asks for.
PAGE_SIZE: Final = 25

# A Fusion pod's host: `{pod}.fa.oraclecloud.com` or `{pod}.fa.{data center}.oraclecloud.com`, labels per RFC 1123 §2.1
# as `urlsplit` gives them (lowercase).
_HOST: Final = re.compile(
    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.fa(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)?\.oraclecloud\.com"
)
# The language of a site's path: a BCP 47 language subtag and an optional region (RFC 5646 §2.1).
_LANGUAGE: Final = re.compile(r"[a-z]{2,3}(?:-[A-Za-z]{2})?", re.ASCII)
# A site number or code and a requisition id go into a REST finder (`finder=Name;arg=value,arg=value`), so they hold
# none of its delimiters: letters, digits, `_` and `-` only.
_NAME: Final = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)


@dataclass(frozen=True)
class _Page:
    host: str
    language: str
    site: str
    match: AdapterMatch


# A requisition as a schema.org JobPosting: its page is `/job/{Id}` under the site's URL (the match's tenant, prefixed
# in `shapes`); `PrimaryLocation` is the primary location, the one a list row shows, and `secondaryLocations` the
# others the job page adds, each as written.
_LISTED: Final = Shape(
    type="JobPosting",
    at=("items", ALL, "requisitionList", ALL),
    properties={
        "title": ("Title",),
        "url": ("Id",),
        "datePosted": ("PostedDate",),
        "jobLocation": ("PrimaryLocation",),
    },
)
# `ExternalDescriptionStr` is the description as HTML; the page shows the responsibilities and qualifications the
# answer keeps apart after it. The hiring organization is the requisition's own `LegalEmployer`, so its node is a view
# of the requisition anchored at that member.
_EMPLOYER: Final = Shape(type="Organization", properties={"name": ("LegalEmployer",)}, anchor=("LegalEmployer",))
_REQUISITION: Final = Shape(
    type="JobPosting",
    at=("items", ALL),
    properties={
        "title": ("Title",),
        "url": ("Id",),
        "description": ("ExternalDescriptionStr",),
        "datePosted": ("ExternalPostedStartDate",),
        "employmentType": ("JobSchedule",),
        "jobLocation": ("PrimaryLocation",),
    },
    also={"jobLocation": (("secondaryLocations", ALL, "Name"),)},
    nodes={"hiringOrganization": (_EMPLOYER,)},
)


class OracleRecruiting:
    name: Final = "oracle_recruiting"

    def detect(self, url: str) -> AdapterMatch | None:
        page = _page(url)
        return None if page is None else page.match

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        # The site's own resources, as `fetch` asks them: the finder names the site first.
        site = _page(match.tenant)
        return site is not None and any(
            endpoint.startswith(f"https://{site.host}{RESOURCES}/{resource}?{_finder(finder, site.site)},")
            for resource, finder in (
                ("recruitingCEJobRequisitions", "findReqs"),
                ("recruitingCEJobRequisitionDetails", "ById"),
            )
        )

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        page = _page(url)
        if page is None:
            raise ValueError("not a career site URL this adapter detects")
        base = f"https://{page.host}{RESOURCES}"
        if page.match.item is None:
            query = f"{_finder('findReqs', page.site)},limit={PAGE_SIZE},offset=0"
            endpoint = f"{base}/recruitingCEJobRequisitions?{query}"
        else:
            item = quote(json.dumps(page.match.item))  # the finder's string argument, double-quoted
            endpoint = f"{base}/recruitingCEJobRequisitionDetails?{_finder('ById', page.site)},Id={item}&expand=all"
        # RFC 9110 §12.5.4: the answer in the language of the page.
        request = JsonRequest(url=endpoint, page_url=url, headers=(("Accept-Language", page.language),))
        return _verdict(await send(request, policy))

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        prefix = {"url": f"{match.tenant}/job/"}
        if match.page_kind == "detail":
            return (replace(_REQUISITION, prefixes=prefix),)
        listed = replace(_LISTED, prefixes=prefix)
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _finder(name: str, site: str) -> str:
    return f"onlyData=true&finder={name};siteNumber={site}"


def _page(url: str) -> _Page | None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme.lower() not in {"http", "https"} or not _HOST.fullmatch(host):
        return None
    match parts.path.strip("/").split("/"):
        case ["hcmUI", "CandidateExperience", language, "sites", site, *rest] if _LANGUAGE.fullmatch(
            language
        ) and _NAME.fullmatch(site):
            root = f"https://{host}/hcmUI/CandidateExperience/{language}/sites/{site}"
            match = _match(root, rest, parts.query)
            return None if match is None else _Page(host, language, site, match)
        case _:
            return None


def _match(root: str, rest: list[str], query: str) -> AdapterMatch | None:
    """The site's list or the job page of a requisition, by the path segments after the site's URL."""
    match rest:
        # A list URL with a query shows a search or a filter of the list, which its first page does not reproduce.
        case [] | ["requisitions"] if not query:
            return AdapterMatch(tenant=root, page_kind="listing")
        case ["job", item] | ["requisitions", "preview", item] if _NAME.fullmatch(item):
            return AdapterMatch(tenant=root, page_kind="detail", item=item)
        case _:
            return None


def _verdict(result: FetchResult) -> FetchResult:
    """`result`, or `NOT_SERVED` when the platform answered without an item: a requisition the site does not hold."""
    if result.block_class != "ok":
        return result
    # `fetch_json` checked that an `ok` body is JSON (RFC 8259).
    answer = json.loads(result.bundle.body)
    items = answer.get("items") if isinstance(answer, dict) else None
    return result if isinstance(items, list) and items else as_error(result, NOT_SERVED)
