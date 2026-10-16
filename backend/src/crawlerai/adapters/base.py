"""The adapter protocol (SPEC-02 §4.9, SPEC-15 §4.4, ARCHITECTURE §7.1, C6): a multi-tenant platform's documented public
API in place of its pages.

An adapter recognizes the platform's page URLs, fetches the JSON its API serves for them, and states how that JSON
holds schema.org nodes (`Shape`), from the platform's API documentation, the platform's standard (C2). Hostnames
appear only in this package (C3). Nothing here interprets values: the adapter collector reads the nodes as
`source_kind='adapter'` candidates with the schema.org path rules every structured collector uses (SPEC-05 §4.5).
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import PageKind

# A tenant or item identifier taken from a page URL is one path segment of RFC 3986 §2.3 unreserved characters, other
# than a dot-segment (`.`, `..`, RFC 3986 §5.2.4), which would move the API path it is put into.
PATH_SEGMENT: Final = re.compile(r"(?!\.+$)[A-Za-z0-9._~-]+")

# A member name step that takes every item of an array (RFC 9535 §2.5.1.2, the wildcard selector).
ALL: Final = "*"

# The reasons an adapter's answer did not serve the page (the error of its `error` outcome; SPEC-15 §4.2): the answer
# lacks the platform's own signal, so the host is not the platform; or the platform answered, but not for this page.
NOT_PLATFORM: Final = "not_platform"
NOT_SERVED: Final = "not_served"

Members = tuple[str, ...]  # member names from a JSON object to a value; `ALL` takes every item of an array
# A value the platform states in a documented form other than schema.org's, read from a node's JSON object: the
# schema.org value and the members it comes from, or None when the object states none.
Stated = Callable[[Mapping[str, JsonValue]], tuple[JsonValue, Members] | None]


@dataclass(frozen=True)
class Shape:
    """A schema.org node the API's JSON holds (SPEC-15 §4.4): its type; `at`, the members from the enclosing node's
    object (the document, for a root) to this node's object; `properties`, the members from that object to each
    schema.org property's values; `nodes`, the shapes of the nodes each property's values are; `stated`, values the
    platform states in a form of its own; and `anchor`, the members that name a node sharing its enclosing node's
    object (`at=()`), so that it is an entity of its own."""

    type: str
    at: Members = ()
    properties: Mapping[str, Members] = field(default_factory=dict)
    nodes: Mapping[str, tuple["Shape", ...]] = field(default_factory=dict)
    stated: Mapping[str, Stated] = field(default_factory=dict)
    anchor: Members = ()


@dataclass(frozen=True)
class AdapterMatch:
    tenant: str  # the platform's identifier for the tenant (a board token, a site name, a shop's host)
    page_kind: PageKind
    # The platform's identifier for the page's item (a posting, a product), or for the list a listing shows when the
    # platform names its lists (a collection); None for a list the tenant alone names.
    item: str | None = None


class Adapter(Protocol):
    @property
    def name(self) -> str: ...

    def detect(self, url: str) -> AdapterMatch | None:
        """The tenant and page kind of a platform page URL, or None for any other URL."""
        ...

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        """Whether `endpoint`, a capture's final URL, is one of the API endpoints this adapter fetches for the page it
        detected as `match`."""
        ...

    async def fetch(self, url: str, policy: FetchPolicy, send: JsonFetcher) -> FetchResult:
        """The API's JSON for the page at `url` (method `api`), recorded under `url`, requested with `send`. An answer
        that does not serve the page is an `error` outcome with reason `NOT_PLATFORM` or `NOT_SERVED`."""
        ...

    def shapes(self, page_kind: PageKind, answer: JsonValue, /) -> tuple[Shape, ...]:
        """The root nodes of `answer`, the API's JSON for a page of `page_kind`."""
        ...
