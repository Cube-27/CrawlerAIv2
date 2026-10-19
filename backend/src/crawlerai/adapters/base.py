"""The adapter protocol (acquisition spec, adapters spec): a multi-tenant platform's documented public
API in place of its pages.

An adapter recognizes the platform's page URLs, fetches the JSON its API serves for them, and states how that JSON
holds schema.org nodes (`Shape`), from the platform's API documentation, the platform's standard (C2). Hostnames
appear only in this package (C3). Nothing here interprets values: the adapter collector reads the nodes as
`source_kind='adapter'` candidates with the schema.org path rules every structured collector uses (extraction spec).
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.db.models import PageKind

# A tenant or item identifier taken from a page URL is one path segment of RFC 3986 §2.3 unreserved characters, other
# than a dot-segment (`.`, `..`, RFC 3986 §5.2.4), which would move the API path it is put into.
PATH_SEGMENT: Final = re.compile(r"(?!\.+$)[A-Za-z0-9._~-]+")

# A member name step that takes every item of an array (RFC 9535 §2.5.1.2, the wildcard selector).
ALL: Final = "*"

# The reasons an adapter's answer did not serve the page (the error of its `error` outcome; adapters spec): the answer
# lacks the platform's own signal, so the host is not the platform; or the platform answered, but not for this page.
NOT_PLATFORM: Final = "not_platform"
NOT_SERVED: Final = "not_served"

Members = tuple[str, ...]  # member names from a JSON object to a value; `ALL` takes every item of an array


@dataclass(frozen=True)
class Shape:
    """A schema.org node the API's JSON holds (adapters spec): its type; `at`, the members from the enclosing node's
    object (the document, for a root) to this node's object; `properties`, the members from that object to each
    schema.org property's values; `also`, further members to values of a property in `properties`, read after its
    own in order (an API that keeps a primary value apart from the others: a primary location and the further ones);
    `prefixes`, text that goes before each string or integer value of a property, for an API that states the value
    relative to a root the page's URL names (a job's path under its career site, a job id under a board's job route);
    `nodes`, the shapes of the nodes each property's values are; `anchor`, the members that name a node sharing its
    enclosing node's object (`at=()`), so that it is an entity of its own; and `minor_units`, for an API whose
    documentation states an amount as an integer count of the currency's minor unit (cents), the number of decimal
    places of that unit: a constant the documentation states, or the members from the node's object to the value that
    states it. Only a property listed there is scaled, and only an integer amount (written as a number or in digits);
    any other value of it is dropped, since the documentation states no unit for it. `booleans` gives a property the
    API states as a JSON boolean the values its documentation means by `true` and by `false` (a variant's `available`:
    schema.org `InStock`, `OutOfStock`)."""

    type: str
    at: Members = ()
    properties: Mapping[str, Members] = field(default_factory=dict)
    also: Mapping[str, tuple[Members, ...]] = field(default_factory=dict)
    prefixes: Mapping[str, str] = field(default_factory=dict)
    nodes: Mapping[str, tuple["Shape", ...]] = field(default_factory=dict)
    anchor: Members = ()
    minor_units: Mapping[str, int | Members] = field(default_factory=dict)
    booleans: Mapping[str, tuple[str, str]] = field(default_factory=dict)


def apply_action(member: str) -> Shape:
    """The schema.org ApplyAction whose `target` is a posting's application form, the URL at `member` of the posting's
    object (an API's apply link): a `potentialAction` of the JobPosting, which `apply_url` ranks above its `url`
    (D-1493)."""
    return Shape(type="ApplyAction", anchor=(member,), properties={"target": (member,)})


@dataclass(frozen=True)
class AdapterMatch:
    tenant: str  # the platform's identifier for the tenant (a board token, a site name, a shop's host)
    page_kind: PageKind
    # The platform's identifier for the page's item (a posting, a product), or for the list a listing shows when the
    # platform names its lists (a collection); None for a list the tenant alone names.
    item: str | None = None
    # The host the platform serves the page on, for an adapter whose shapes name the page's items by the platform's
    # routes on that host (a hosted board's job pages); None when the shapes need none.
    host: str | None = None
    # The locale the page's path leads with (a Workday career site's `/en-US/`), for an adapter whose shapes name the
    # page's items by the links the page itself renders, which keep it; None when the path states none.
    locale: str | None = None


@dataclass(frozen=True)
class PageRefs:
    """What an HTML page states about itself and links to: `own`, the URLs that name the page itself, strongest first
    (its final URL, canonical link, `og:url`), and `links`, the absolute targets of its links."""

    own: tuple[str, ...]
    links: tuple[str, ...]


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

    def shapes(self, match: AdapterMatch, answer: JsonValue, /) -> tuple[Shape, ...]:
        """The root nodes of `answer`, the API's JSON for the page this adapter detected as `match`."""
        ...


@runtime_checkable
class Referring(Protocol):
    """An adapter whose platform serves sites on tenants' own hosts, which tell their platform page only by what the
    site's own page states (adapters spec)."""

    def referred(self, refs: PageRefs, kind: PageKind | None, /) -> str | None:
        """The platform page URL (one `detect` accepts) that the page with `refs` stands for, as the page kind `kind`
        (None: any); None when its references do not say, or say several."""
        ...
