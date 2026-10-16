"""What names the site a page belongs to, as opposed to the thing the page is about (SPEC-05 §4.5): the Open Graph
`og:site_name` ("the name of the overall site"), each separator run of it, and the label of the page host's
registrable domain (Public Suffix List, "Formal Algorithm": the public suffix plus one label).

Names compare folded (`fold`): letters and digits only, after NFKC and Unicode default case folding, so that case,
spacing and punctuation do not tell two writings of one name apart. A title separator is one punctuation or symbol
character (Unicode general categories P* and S*) standing alone between white space, as in "Item | Site" or
"Item - Site"; a hyphen or colon written against a word is part of the text.
"""

import ipaddress
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

from crawlerai.acquire.public_suffix import default_suffixes

_SEPARATOR = re.compile(r"\s+[^\w\s]\s+")


@dataclass(frozen=True, slots=True)
class SiteNames:
    """The folded names of the site: `stated` from the page's site-name values, `host` from its URL."""

    stated: frozenset[str]
    host: str | None

    @classmethod
    def of(cls, site_names: Iterable[str], page_url: str | None) -> "SiteNames":
        return cls(frozenset(run for name in site_names for run in _runs(name) if run), _host_label(page_url))

    def names(self, text: str) -> bool:
        """Whether `text` as a whole names the site: a stated name or a run of one, or the host's label."""
        folded = fold(text)
        return bool(folded) and (folded in self.stated or folded == self.host)

    def strip(self, title: str) -> str:
        """`title` without its trailing separator segments that name the site: a name `names` accepts, or a segment
        that starts with the host's label ("Example Store" on `shop.example.test`). The first segment always stays."""
        separators = list(_SEPARATOR.finditer(title))
        end = len(title)
        while separators and self._names_segment(title[separators[-1].end() : end]):
            end = separators.pop().start()
        return title[:end]

    def _names_segment(self, segment: str) -> bool:
        return self.names(segment) or (self.host is not None and fold(segment).startswith(self.host))


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def _runs(name: str) -> Iterator[str]:
    """Every run of consecutive separator segments of `name`, folded: the whole name and each part of it."""
    parts = _SEPARATOR.split(name)
    for start in range(len(parts)):
        for end in range(start + 1, len(parts) + 1):
            yield fold("".join(parts[start:end]))


def _host_label(page_url: str | None) -> str | None:
    """The folded first label of the host's registrable domain; an IP address host has none."""
    host = urlsplit(page_url).hostname if page_url else None
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        domain = default_suffixes().registrable_domain(host)
        return (fold(domain.split(".")[0]) or None) if domain is not None else None
    return None
