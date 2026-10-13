"""The adapter protocol (SPEC-02 §4.9, ARCHITECTURE §7.1, C6): a multi-tenant platform's documented public API in
place of its pages.

An adapter recognizes the platform's page URLs, fetches the JSON its API serves for them, and maps schema fields to
JSONPaths (RFC 9535) in that JSON from the platform's API documentation, the platform's standard (C2). Hostnames
appear only in this package (C3). Nothing here interprets values: the collectors read the JSON as
`source_kind='adapter'` candidates (SPEC-05).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import PageKind


@dataclass(frozen=True)
class AdapterMatch:
    tenant: str  # the platform's identifier for the tenant (a board token, a site name)
    page_kind: PageKind
    item: str | None = None  # the platform's identifier for the posting on a detail page


class Adapter(Protocol):
    @property
    def name(self) -> str: ...

    def detect(self, url: str) -> AdapterMatch | None:
        """The tenant and page kind of a platform page URL, or None for any other URL."""
        ...

    async def fetch(self, url: str, policy: FetchPolicy) -> FetchResult:
        """The API's JSON for the page at `url` (method `api`), recorded under `url`."""
        ...

    def map(self, schema_org: Mapping[str, str], page_kind: PageKind) -> dict[str, str]:
        """JSONPaths into the fetched JSON for the fields whose schema.org path (`field -> path`, SPEC-04 §4.2) the
        platform documents a value for; other fields are left out."""
        ...
