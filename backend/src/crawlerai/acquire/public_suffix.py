"""Public suffixes for cookie domains (RFC 6265 §5.3 step 5): a cookie whose `Domain` is a public suffix is ignored,
unless that suffix is the setting host itself, so no site sets a cookie for every site under a shared suffix.

The suffixes come from the Public Suffix List (`backend/data/publicsuffix/`, pinned in `backend/data/manifest.json`,
fetched by `crawlerai data fetch`; C4), matched by the list's own "Formal Algorithm". Without the file the cookie policy is the standard library's, as before the list was used.
"""

import logging
from dataclasses import dataclass
from functools import cache
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from pathlib import Path
from typing import Final
from urllib.request import Request

from crawlerai.core.engine_version import data_dir, engine_dir

log = logging.getLogger(__name__)

SUFFIX_FILE: Final = Path("publicsuffix") / "public_suffix_list.dat"


@dataclass(frozen=True, slots=True)
class PublicSuffixes:
    """The list's rules, each as lowercase ASCII (IDNA A-labels): plain, wildcard (`*.` dropped) and exception (`!`
    dropped)."""

    rules: frozenset[str]
    wildcards: frozenset[str]
    exceptions: frozenset[str]

    @classmethod
    def parse(cls, text: str) -> "PublicSuffixes":
        """The rules of a list file: one per line, up to its first white space; `//` lines are comments."""
        rules: set[str] = set()
        wildcards: set[str] = set()
        exceptions: set[str] = set()
        for line in text.splitlines():
            words = line.split()
            if not words or words[0].startswith("//"):
                continue
            rule = words[0]
            if rule.startswith("!"):
                exceptions.add(_ascii(rule[1:]))
            elif rule.startswith("*."):
                wildcards.add(_ascii(rule[2:]))
            else:
                rules.add(_ascii(rule))
        return cls(frozenset(rules), frozenset(wildcards), frozenset(exceptions))

    def is_public_suffix(self, domain: str) -> bool:
        """Whether `domain` is itself a public suffix. An exception rule names a registrable domain; a single label
        is a suffix by the list's implicit `*` rule."""
        name = _ascii(domain.strip(".").lower())
        if not name or name in self.exceptions:
            return False
        parent = name.partition(".")[2]
        return name in self.rules or parent in self.wildcards or not parent


def _ascii(name: str) -> str:
    """A domain as the cookie header carries it: IDNA A-labels (RFC 5890 §2.3.2.1), lowercase."""
    return name.encode("idna").decode("ascii").lower() if not name.isascii() else name.lower()


class SuffixCookiePolicy(DefaultCookiePolicy):
    """The standard policy, which also ignores a cookie whose `Domain` is a public suffix other than the setting
    host (RFC 6265 §5.3 step 5)."""

    def __init__(self, suffixes: PublicSuffixes) -> None:
        super().__init__(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain)
        self._suffixes = suffixes

    def set_ok_domain(self, cookie: Cookie, request: Request) -> bool:
        if cookie.domain_specified:
            domain = cookie.domain.lstrip(".").lower()
            if self._suffixes.is_public_suffix(domain) and domain != (request.host or "").partition(":")[0].lower():
                return False
        return super().set_ok_domain(cookie, request)


def cookie_jar(suffixes: PublicSuffixes | None) -> CookieJar:
    """A jar for one fetch: domain cookies are checked against `suffixes` when there is a list."""
    if suffixes is None:
        return CookieJar(DefaultCookiePolicy(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain))
    return CookieJar(SuffixCookiePolicy(suffixes))


@cache
def default_suffixes() -> PublicSuffixes | None:
    """The list in the engine directory's `data/`, read once; None when it has not been fetched."""
    engine = engine_dir(Path(__file__))
    path = None if engine is None else data_dir(engine) / SUFFIX_FILE
    if path is None or not path.is_file():
        log.warning("no public suffix list: Domain= cookies are checked by the standard library's policy only")
        return None
    return PublicSuffixes.parse(path.read_text(encoding="utf-8"))
