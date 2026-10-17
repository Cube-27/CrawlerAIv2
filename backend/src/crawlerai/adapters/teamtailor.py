"""Teamtailor hosted career sites through the jobs feed of the company (owner delegation 2026-10-17).

Endpoint, the public feed the platform's own career sites publish (verified against live answers of several
companies, 2026-10-17), unauthenticated: `GET /jobs.json` is a JSON Feed (specification version 1.1) of the open
jobs, `{"items": [{"id", "title", "url", "date_published", "content_html", "_jobposting"}]}`, whole and not paged;
`_jobposting` is the job as a schema.org JobPosting (a JSON Feed extension member), with its identifier, hiring
organization and places. A company is the host `{company}.teamtailor.com`: its list is `/jobs`. The feed has no
endpoint for one job, so a job's page is read from the page rungs.
"""

import re
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.answer import serving
from crawlerai.adapters.base import ALL, AdapterMatch, Shape

DOMAIN: Final = "teamtailor.com"

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)

# A job as a schema.org JobPosting: the feed item's own members for its page and text, `_jobposting` for the rest.
_PLACE: Final = Shape(
    type="Place",
    at=("_jobposting", "jobLocation", ALL),
    nodes={
        "address": (
            Shape(
                type="PostalAddress",
                at=("address",),
                properties={
                    "streetAddress": ("streetAddress",),
                    "addressLocality": ("addressLocality",),
                    "addressRegion": ("addressRegion",),
                    "postalCode": ("postalCode",),
                    "addressCountry": ("addressCountry",),
                },
            ),
        )
    },
)
_EMPLOYER: Final = Shape(
    type="Organization", at=("_jobposting", "hiringOrganization"), properties={"name": ("name",)}, anchor=("name",)
)
_JOB: Final = Shape(
    type="JobPosting",
    at=("items", ALL),
    properties={
        "title": ("title",),
        "url": ("url",),
        "description": ("content_html",),
        "datePosted": ("date_published",),
        "identifier": ("_jobposting", "identifier", "value"),
    },
    nodes={"jobLocation": (_PLACE,), "hiringOrganization": (_EMPLOYER,)},
)
_SHAPES: Final = (Shape(type="ItemList", nodes={"itemListElement": (_JOB,)}),)


class Teamtailor:
    name: Final = "teamtailor"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        host = (parts.hostname or "").split(".")
        if parts.scheme.lower() not in {"http", "https"} or len(host) != 3 or ".".join(host[1:]) != DOMAIN:
            return None
        if not _LABEL.fullmatch(host[0]) or parts.query or parts.path.strip("/") not in {"", "jobs"}:
            return None
        return AdapterMatch(tenant=host[0], page_kind="listing")

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint == _feed(match.tenant)

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career site URL this adapter detects")
        return serving(await send(JsonRequest(url=_feed(match.tenant), page_url=url), policy), _rows)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        return _SHAPES


def _feed(company: str) -> str:
    return f"https://{company}.{DOMAIN}/jobs.json"


def _rows(answer: JsonValue) -> int:
    items = answer.get("items") if isinstance(answer, dict) else None
    return len(items) if isinstance(items, list) else 0
