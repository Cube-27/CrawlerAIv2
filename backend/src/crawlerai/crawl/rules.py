"""URL rules of discovery requests (SPEC-10 §4.1, §4.4): include and exclude globs, `fnmatch`-style over the
canonical URL. Patterns come from requests; this module names no host (INV-03).
"""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import urlsplit


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
