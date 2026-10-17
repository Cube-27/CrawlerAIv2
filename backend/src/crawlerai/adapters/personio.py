"""Personio hosted career sites through the XML feed of the company (owner delegation 2026-10-17).

Endpoint, the public feed the platform documents for its job boards (Personio's "XML interface" for job postings,
verified against live answers of several companies, 2026-10-17), unauthenticated: `GET /xml` is `<workzag-jobs>` of
`<position>` elements, each with `id`, `name`, `office`, `additionalOffices/office`, `department`, `subcompany`,
`schedule`, `employmentType`, `createdAt` and `jobDescriptions/jobDescription` (`name`, `value` as HTML), whole and not
paged. The feed is read with `xml_reader` into JSON, the document the capture records. A company is the host
`{company}.jobs.personio.de` (or `.personio.com`): its list is `/`, a job `/job/{id}`. The feed has no endpoint for one
job, so a job's page is read from the page rungs.
"""

import re
from dataclasses import replace
from html import escape
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.answer import recorded, serving
from crawlerai.adapters.base import ALL, NOT_SERVED, AdapterMatch, Shape
from crawlerai.adapters.xml_reader import read_xml

DOMAINS: Final = frozenset({"jobs.personio.de", "jobs.personio.com"})

# A host name label (RFC 1123 §2.1), as `urlsplit` gives it: lowercase.
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", re.ASCII)
# RFC 9110 §12.5.1: the feed is XML (RFC 7303).
_ACCEPT: Final = (("Accept", "application/xml"),)

# A position as a schema.org JobPosting: `reader` wraps every element's values in arrays, so a member is
# `(name, ALL)`. The position's page is `/job/{id}` on the company's host (the prefix `shapes` puts before `id`); its
# `schedule` (full-time, part-time) is the employment type; its offices are the places as written; the hiring
# organization is its `subcompany`; its `description` is the one HTML text `_described` makes of the ad's sections.
_POSITIONS: Final = ("workzag-jobs", ALL, "position", ALL)
_EMPLOYER: Final = Shape(type="Organization", properties={"name": ("subcompany", ALL)}, anchor=("subcompany", ALL))
_POSITION: Final = Shape(
    type="JobPosting",
    at=_POSITIONS,
    properties={
        "title": ("name", ALL),
        "identifier": ("id", ALL),
        "url": ("id", ALL),
        "datePosted": ("createdAt", ALL),
        "employmentType": ("schedule", ALL),
        "jobLocation": ("office", ALL),
        "description": ("description", ALL),
    },
    also={"jobLocation": (("additionalOffices", ALL, "office", ALL),)},
    nodes={"hiringOrganization": (_EMPLOYER,)},
)


class Personio:
    name: Final = "personio"

    def detect(self, url: str) -> AdapterMatch | None:
        parts = urlsplit(url)
        host = (parts.hostname or "").split(".", 1)
        if parts.scheme.lower() not in {"http", "https"} or len(host) != 2 or host[1] not in DOMAINS:
            return None
        if not _LABEL.fullmatch(host[0]) or parts.query or parts.path.strip("/"):
            return None
        return AdapterMatch(tenant=parts.hostname or "", page_kind="listing")

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return endpoint == _feed(match.tenant)

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        match = self.detect(url)
        if match is None:
            raise ValueError("not a career site URL this adapter detects")
        result = await send(JsonRequest(url=_feed(match.tenant), page_url=url, headers=_ACCEPT, raw=True), policy)
        if result.block_class != "ok":
            return result
        try:
            answer = read_xml(result.bundle.body)
        except ValueError:  # the platform's own page for a company it does not know
            return as_error(result, NOT_SERVED)
        return serving(recorded(result, _described(answer)), _rows)

    def shapes(self, match: AdapterMatch, _answer: JsonValue, /) -> tuple[Shape, ...]:
        listed = replace(_POSITION, prefixes={"url": f"https://{match.tenant}/job/"})
        return (Shape(type="ItemList", nodes={"itemListElement": (listed,)}),)


def _feed(host: str) -> str:
    return f"https://{host}/xml"


def _members(value: JsonValue, name: str) -> list[dict[str, JsonValue]]:
    """The object elements named `name` under `value`, an object of `xml_reader` (its member `name` is an array)."""
    found = value.get(name) if isinstance(value, dict) else None
    return [e for e in (found if isinstance(found, list) else []) if isinstance(e, dict)]


def _positions(answer: JsonValue) -> list[dict[str, JsonValue]]:
    return [p for feed in _members(answer, "workzag-jobs") for p in _members(feed, "position")]


def _rows(answer: JsonValue) -> int:
    return len(_positions(answer))


def _described(answer: JsonValue) -> JsonValue:
    """`answer` with each position's `description`: the ad is its `jobDescription` sections in order, each a heading
    (`name`) and an HTML body (`value`), so it is one HTML text of them, not one candidate per section."""
    for position in _positions(answer):
        sections = [s for wrapper in _members(position, "jobDescriptions") for s in _members(wrapper, "jobDescription")]
        html = "\n".join(text for section in sections if (text := _section(section)))
        position["description"] = [html or None]
    return answer


def _section(section: dict[str, JsonValue]) -> str:
    heading, body = (_first(section.get(member)) for member in ("name", "value"))
    return "".join((f"<h2>{escape(heading)}</h2>" if heading else "", body))


def _first(values: JsonValue) -> str:
    return values[0] if isinstance(values, list) and values and isinstance(values[0], str) else ""
