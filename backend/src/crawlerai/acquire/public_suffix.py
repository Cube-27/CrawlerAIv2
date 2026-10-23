"""Public suffixes for cookie domains (RFC 6265 §5.3 step 5): a cookie whose `Domain` is a public suffix is ignored,
unless that suffix is the setting host itself, so no site sets a cookie for every site under a shared suffix.

The suffixes come from the Public Suffix List (`backend/data/publicsuffix/`, pinned in `backend/data/manifest.json`,
fetched by `crawlerai data fetch`; C4), matched by the list's own "Formal Algorithm". Without the file the list is
empty, and only the list's implicit `*` rule (a single label) applies.
"""

import ipaddress
import logging
from dataclasses import dataclass
from functools import cache
from http.cookiejar import Cookie, DefaultCookiePolicy
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from urllib.request import Request

from crawlerai.core.engine_version import engine_data_dir

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

    def registrable_domain(self, host: str) -> str | None:
        """The list's "registrable domain" of `host`: its public suffix plus one more label (an exception rule's name
        is one), or `None` when `host` is itself a public suffix. The first match from the left is the longest."""
        labels = host.strip(".").lower().split(".")
        for i in range(len(labels)):
            name = ".".join(labels[i:])
            if _ascii(name) in self.exceptions:  # an exception rule names a registrable domain itself
                return name
            if self.is_public_suffix(name):
                return ".".join(labels[i - 1 :]) if i else None
        return None

    def site(self, host: str) -> str:
        """The site of `host` (HTML Standard §7.1.1 "obtain a site", less the scheme): its registrable domain, or the
        host itself where it has none (an IP address, a public suffix). An IP address (RFC 3986 §3.2.2 IP-literal or
        IPv4address) is never split into labels: `192.0.2.1` and `198.0.2.1` are two sites."""
        name = host.strip(".").lower()
        try:
            ipaddress.ip_address(name.strip("[]"))
        except ValueError:
            return self.registrable_domain(name) or name
        return name


def _ascii(name: str) -> str:
    """A domain as the cookie header carries it: IDNA A-labels (RFC 5890 §2.3.2.1), lowercase."""
    return name.lower() if name.isascii() else name.encode("idna").decode("ascii").lower()


class SuffixCookiePolicy(DefaultCookiePolicy):
    """The standard policy, which also ignores a cookie whose `Domain` is a public suffix other than the setting
    host, and keeps one whose `Domain` is the setting host and a public suffix for that host alone (RFC 6265 §5.3
    step 5)."""

    def __init__(self, suffixes: PublicSuffixes) -> None:
        super().__init__(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain)
        self._suffixes = suffixes

    def set_ok_domain(self, cookie: Cookie, request: Request) -> bool:
        if not cookie.domain_specified:
            return super().set_ok_domain(cookie, request)
        try:
            domain = _ascii(cookie.domain.strip(".").lower())
        except UnicodeError:
            return False  # no IDNA name (RFC 5890 §2.3.2.1), so it names no host
        host = urlsplit(request.get_full_url()).hostname or ""
        if self._suffixes.is_public_suffix(domain):
            if domain != host:
                return False
            # Host-only, as `http.cookiejar` keeps a cookie without a Domain: under the effective host name (RFC 2965
            # §1: a name without a dot gets `.local`), which `DomainStrictNonDomain` matches exactly.
            cookie.domain = host if "." in host else f"{host}.local"
            cookie.domain_specified = cookie.domain_initial_dot = False
        return super().set_ok_domain(cookie, request)


def site_of(url: str) -> str:
    """The site of `url`'s host (`site` above), by the default list."""
    return default_suffixes().site(urlsplit(url).hostname or "")


@cache
def default_suffixes() -> PublicSuffixes:
    """The list in the engine directory's `data/`, read once; empty when it has not been fetched."""
    data = engine_data_dir()
    path = None if data is None else data / SUFFIX_FILE
    if path is None or not path.is_file():
        log.warning("no public suffix list: only single-label Domain= cookies are refused")
        return PublicSuffixes.parse("")
    return PublicSuffixes.parse(path.read_text(encoding="utf-8"))
