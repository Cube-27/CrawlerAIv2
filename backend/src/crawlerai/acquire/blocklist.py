"""The browser rung's request blocking (acquisition spec, "HTTP and browser rungs"): what a render never loads,
because the page's DOM and data calls, which are what is read, never need it.

- By resource type (Fetch Standard §2.2.5 destinations, as Playwright names them): `image`, `font` and `media`, the
  page's pixels and sound; `ping`, a Beacon (W3C Beacon §3) or hyperlink auditing request (HTML Standard §4.6.5),
  which sends and never brings anything back to the page.
- By category: a request to a server the EasyList project lists as an advertising server (EasyList) or a tracking
  server (EasyPrivacy), pinned in `backend/data/manifest.json` and fetched by `crawlerai data fetch` (C4). Only the
  lists' server lines are read: `||host^` blocks the host and its subdomains wherever the request comes from; its
  `$third-party` option limits it to a request from a document on another site (HTML Standard §7.1.1, registrable
  domains), and resource-type options to those types. Every other filter (paths, wildcards, other options) is left
  out. Without the files only the resource-type rules apply.

Never blocked: the main frame's own navigation, and a vendor resource of the categories `adapters.kept_resources`
lists (`kept_resource`): an anti-bot challenge, fraud-prevention, fingerprinting or bot-detection vendor's (a page
whose bot defence cannot run is refused), or a tag manager's container (it can inject the page's structured data; the
endpoints it loads are blocked as any other).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from crawlerai.acquire.public_suffix import default_suffixes
from crawlerai.adapters.kept_resources import kept_resource
from crawlerai.core.engine_version import engine_data_dir

log = logging.getLogger(__name__)

__all__ = ["Blocklist", "blocked_request", "default_blocklist"]

LIST_FILES: Final = tuple(
    Path("easylist") / name
    for name in (
        "easylist_adservers.txt",
        "easyprivacy_trackingservers_general.txt",
        "easyprivacy_trackingservers_thirdparty.txt",
        "easyprivacy_trackingservers_international.txt",
    )
)
# Fetch Standard §2.2.5 destinations by Playwright's names (module docstring).
_BLOCKED_TYPES: Final = frozenset({"image", "font", "media", "ping"})
# Adblock Plus filter options (its "How to write filters" reference) a server line may carry: `third-party`, and the
# resource types it is limited to, by Playwright's names for them. A line with any other option is not read.
_THIRD_PARTY: Final = "third-party"
_TYPE_OPTIONS: Final[dict[str, frozenset[str]]] = {
    "script": frozenset({"script"}),
    "xmlhttprequest": frozenset({"xhr", "fetch"}),
    "image": frozenset({"image"}),
    "subdocument": frozenset({"document"}),
    "ping": frozenset({"ping"}),
    "stylesheet": frozenset({"stylesheet"}),
    "media": frozenset({"media"}),
    "font": frozenset({"font"}),
    "websocket": frozenset({"websocket"}),
    "other": frozenset({"other"}),
}


@dataclass(frozen=True, slots=True)
class _Rule:
    third_party: bool  # only a request from a document on another site
    types: frozenset[str] | None  # only these resource types; None: any


@dataclass(frozen=True, slots=True)
class Blocklist:
    """The listed servers, lowercase, each with its rules."""

    servers: Mapping[str, tuple[_Rule, ...]]

    @classmethod
    def parse(cls, text: str) -> "Blocklist":
        """The server lines of an Adblock Plus filter list (module docstring); every other line is skipped."""
        servers: dict[str, list[_Rule]] = {}
        for line in text.splitlines():
            if not line.startswith("||"):
                continue
            server, _, rest = line[2:].partition("^")
            rule = _rule(rest)
            if server and rule is not None and all(c.isalnum() or c in ".-" for c in server):
                servers.setdefault(server.lower(), []).append(rule)
        return cls({server: tuple(rules) for server, rules in servers.items()})

    def lists(self, host: str, resource_type: str, document_host: str | None) -> bool:
        """Whether a request of `resource_type` to `host` from a document on `document_host` goes to a listed server:
        the host or one of its parent domains is listed (the `||` anchor) by a rule that applies to it; a third-party
        rule applies when the hosts' sites differ (a request from an unknown document is not third-party)."""
        names = host.lower().rstrip(".").split(".")
        rules = [rule for i in range(len(names) - 1) for rule in self.servers.get(".".join(names[i:]), ())]
        if not rules:
            return False
        third = document_host is not None and _site(host) != _site(document_host)
        return any(
            (third or not rule.third_party) and (rule.types is None or resource_type in rule.types) for rule in rules
        )


def _rule(rest: str) -> _Rule | None:
    """The rule of a server line's text after `^`: none, or `$` and its options; None for a line not read."""
    if not rest:
        return _Rule(third_party=False, types=None)
    if not rest.startswith("$"):
        return None
    third_party, types = False, set[str]()
    for option in rest[1:].split(","):
        if option == _THIRD_PARTY:
            third_party = True
        elif option in _TYPE_OPTIONS:
            types |= _TYPE_OPTIONS[option]
        else:
            return None
    return _Rule(third_party, frozenset(types) or None)


def _site(host: str) -> str:
    return default_suffixes().site(host)


@cache
def default_blocklist() -> Blocklist:
    """The lists in the engine directory's `data/`, read once; empty when they have not been fetched."""
    data = engine_data_dir()
    paths = [] if data is None else [data / name for name in LIST_FILES]
    texts = [path.read_text(encoding="utf-8") for path in paths if path.is_file()]
    if len(texts) < len(LIST_FILES):
        log.warning("advertising and tracking server lists missing: the browser blocks by resource type only")
    return Blocklist.parse("\n".join(texts))


def blocked_request(
    url: str, resource_type: str, document_url: str | None, *, navigation: bool, blocklist: Blocklist
) -> bool:
    """Whether the browser aborts a request (module docstring): `document_url` is the URL of the document that made
    it, when known; `navigation` says it is the main frame's own navigation."""
    if navigation or kept_resource(url):
        return False
    if resource_type in _BLOCKED_TYPES:
        return True
    host = urlsplit(url).hostname
    document_host = None if document_url is None else urlsplit(document_url).hostname
    return host is not None and blocklist.lists(host, resource_type, document_host)
