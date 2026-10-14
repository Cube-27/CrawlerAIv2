"""URL rules of discovery requests (SPEC-10 §4.1, §4.4, §4.5): include and exclude globs, and a crawl's page-kind
rules, `fnmatch`-style over the canonical URL. Patterns come from requests; this module names no host (INV-03).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from crawlerai.db.models import PageKind


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


def _any_match(url: str, patterns: tuple[str, ...]) -> bool:
    # `fnmatchcase`: a URL path is case-sensitive (RFC 3986 §6.2.2.1), and `fnmatch` folds case on Windows.
    return any(fnmatchcase(url, pattern) for pattern in patterns)
