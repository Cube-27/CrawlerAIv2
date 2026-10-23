"""The browser context's locality (acquisition spec, "Patchright's documented browser setup"): the request's locale
(`FetchPolicy.locale_hint`) sets the context's `locale` (and so the `Accept-Language` the browser sends), and the
country the render goes out from sets the `timezone_id`, so the zone a page reads agrees with the address it sees.
Without a declared egress country, the locale's region sets the zone, as a visitor of that locale has it.

The locale is read by BCP 47's structure alone (RFC 5646 §2.1: a language subtag, an optional script, an optional
region). The zone is the IANA tz database's own for a country (`zone1970.tab`, whose first country code on a line names
the zone's principal country): a country that is the principal country of one zone gets it, a country principal to none
gets the one zone it shares when there is just one. A country with several zones, or no country and a locale with no
region, sets no zone: the browser keeps the machine's, as no guess is made.
"""

from collections import defaultdict
from functools import cache
from importlib.resources import files
from typing import TypedDict

__all__ = ["Locality", "language_headers", "locality"]


class Locality(TypedDict, total=False):
    """The browser context options the locale and the egress country set (Playwright's `new_context` options)."""

    locale: str
    timezone_id: str


def locality(hint: str | None, country: str | None = None) -> Locality:
    """The context options of the request's locale `hint` (none for no hint or one that is not a BCP 47 tag) and of
    `country`, the ISO 3166-1 alpha-2 country the render goes out from (None: undeclared)."""
    parsed = None if hint is None else _parsed(hint)
    found: Locality = {}
    if parsed is not None:
        found["locale"] = "-".join(part for part in parsed if part)
    place = country or (None if parsed is None else parsed[2])  # the egress country, else the locale's region
    zone = None if place is None else _zone(place)
    if zone is not None:
        found["timezone_id"] = zone
    return found


def language_headers(hint: str | None) -> dict[str, str]:
    """The `Accept-Language` (RFC 9110 §12.5.4) the browser rung sends for the request's locale `hint`, its context's
    `locale` alone, for the HTTP and JSON rungs to send as well; none without a locale (the browser's own, which the
    impersonation's headers carry, `acquire.impersonate`)."""
    locale = locality(hint).get("locale")
    return {} if locale is None else {"Accept-Language": locale}


def _parsed(hint: str) -> tuple[str, str | None, str | None] | None:
    """The language, script and region subtags of a BCP 47 tag (RFC 5646 §2.1), in their canonical case (§2.1.1)."""
    subtags = hint.strip().replace("_", "-").split("-")
    language = subtags.pop(0)
    if not (2 <= len(language) <= 8 and language.isascii() and language.isalpha()):
        return None
    script = subtags.pop(0).title() if subtags and len(subtags[0]) == 4 and subtags[0].isalpha() else None
    region = None
    if (
        subtags
        and subtags[0].isascii()
        and ((len(subtags[0]) == 2 and subtags[0].isalpha()) or (len(subtags[0]) == 3 and subtags[0].isdigit()))
    ):
        region = subtags[0].upper()
    return language.lower(), script, region


def _zone(region: str) -> str | None:
    principal, shared = _zones()
    zones = principal.get(region) or shared.get(region, [])
    return zones[0] if len(zones) == 1 else None


@cache
def _zones() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """The tz database's zones by their principal country, and by every country that uses them (`zone1970.tab`: the
    country codes, coordinates, zone name and comment of each zone, tab-separated, `#` lines comments)."""
    principal: dict[str, list[str]] = defaultdict(list)
    shared: dict[str, list[str]] = defaultdict(list)
    table = files("tzdata.zoneinfo").joinpath("zone1970.tab").read_text(encoding="utf-8")
    for line in table.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        codes, _, zone, *_ = line.split("\t")
        countries = codes.split(",")
        principal[countries[0]].append(zone)
        for country in countries:
            shared[country].append(zone)
    return dict(principal), dict(shared)
