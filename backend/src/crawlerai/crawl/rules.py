"""URL rules of discovery requests (SPEC-10 §4.1, §4.4, §4.5, §4.6): include and exclude globs, a crawl's page-kind
rules, and the URL globs `extract` expands, `fnmatch`-style over the canonical URL. Patterns come from requests; this
module names no host (INV-03).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Annotated, Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from crawlerai.crawl.canonical import canonicalize
from crawlerai.db.models import PageKind

# The characters `fnmatch` gives a meaning (Python `fnmatch` docs: `*`, `?`, `[seq]`).
_PATTERN_CHARACTERS: Final = frozenset("*?[")
# The most globs an `include` or `exclude` list takes (D-0835). Every URL a map or crawl reads is matched against each,
# on the event loop: about 0.8 µs a match, so the two lists over a map's 50k sitemap URLs (`sitemaps.MAX_URLS`) take
# at most about 1.6 s.
MAX_PATTERNS: Final = 20
# An `include` or `exclude` list of a request.
Patterns = Annotated[list[str], Field(max_length=MAX_PATTERNS)]


class PageKindRule(BaseModel):
    """A crawl's rule (§4.5): a URL `pattern` matches is extracted as a `page_kind` page."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str
    page_kind: PageKind


def page_kind_for(url: str, rules: Sequence[PageKindRule]) -> PageKind | None:
    """The page kind of the first of `rules` whose pattern matches `url`, in canonical form; `None` when none does:
    the URL is then crawled for its links only (ARCHITECTURE §13.2)."""
    return next((rule.page_kind for rule in rules if fnmatchcase(url, rule.pattern)), None)


@dataclass(frozen=True)
class Scope:
    """The URLs a request keeps: any that `exclude` matches is dropped; otherwise, with `include`, those it matches,
    on any host; without it, those on the start URL's exact `host` (D-0037: a subdomain needs an `include`)."""

    host: str
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()

    def admits(self, url: str) -> bool:
        """Whether `url`, in canonical form (`crawl.canonical`), is in scope."""
        if _any_match(url, self.exclude):
            return False
        if self.include:
            return _any_match(url, self.include)
        return urlsplit(url).hostname == self.host


def on_site(url: str, host: str) -> bool:
    """Whether `url` is on `host` or one of its subdomains."""
    # RFC 1034 §3.1: a domain name's subdomains are the names that end with its labels, so with "." + the name.
    found = urlsplit(url).hostname
    return found is not None and (found == host or found.endswith(f".{host}"))


def located(start: str, capture: tuple[str, str] | None) -> str:
    """Where the start page of a map or crawl is, in canonical form, from its capture's (method, final URL): the URL
    the site's redirects of `start` ended at, which the request's scope follows (RFC 9110 §15.4: a redirect names the
    resource's location; D-0991), when it is on the start URL's site: its host, a subdomain of it, or a domain it is
    a subdomain of (`www.` and back). Otherwise `start` itself (D-0672: never a site the caller did not name), as
    without a capture, or for an API recipe's (method `api`), whose final URL is its endpoint, not the page."""
    final = None if capture is None or capture[0] == "api" else canonicalize(capture[1])
    start_host = urlsplit(start).hostname or ""
    final_host = "" if final is None else urlsplit(final).hostname or ""
    if final is None or not (on_site(final, start_host) or on_site(start, final_host)):
        return start
    return final


def _any_match(url: str, patterns: tuple[str, ...]) -> bool:
    # `fnmatchcase`: a URL path is case-sensitive (RFC 3986 §6.2.2.1), and `fnmatch` folds case on Windows.
    return any(fnmatchcase(url, pattern) for pattern in patterns)


def is_glob(url: str) -> bool:
    """Whether a requested URL is a glob to expand (§4.6): one with a `*`. `?` and `[` alone leave it a URL, since a
    query starts with `?` (RFC 3986 §3.4) and an IPv6 host sits in `[]` (§3.2.2); in a glob, they match as in
    `fnmatch`."""
    return "*" in url


@dataclass(frozen=True)
class UrlGlob:
    """A glob of `extract` (§4.6) on its origin: `origin` is its scheme and authority in canonical form
    (`https://host/`), and `pattern` the glob with that origin, to match canonical URLs as a map's `include` does."""

    origin: str
    pattern: str


def url_glob(pattern: str) -> UrlGlob | None:
    """`pattern` on its origin; `None` for a glob that names no http(s) host, or whose scheme or authority (RFC 3986
    §3) has a pattern character: a glob is expanded on one host."""
    scheme, separator, rest = pattern.partition("://")
    authority, slash, path = rest.partition("/")
    if not separator or not slash or _PATTERN_CHARACTERS.intersection(scheme + authority):
        return None
    origin = canonicalize(f"{scheme}://{authority}/")
    return None if origin is None else UrlGlob(origin=origin, pattern=origin + path)
