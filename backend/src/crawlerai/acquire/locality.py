"""The browser context's locality: the request's locale
(`FetchPolicy.locale_hint`), else the one its exit declares (`ExitPlace`), sets the context's `locale` (and so the
`Accept-Language` the browser sends, which the HTTP and JSON rungs send too), and the place the render goes out from
sets the `timezone_id`, so the zone a page reads agrees with the address it sees: the exit's declared zone, else the
zone of its declared country. Without a declared egress country, the locale's region sets the zone, as a visitor of
that locale has it.

The locale is read by BCP 47's structure alone (RFC 5646 §2.1: a language subtag, an optional script, an optional
region). The zone is the IANA tz database's own for a country (`zone1970.tab`, whose first country code on a line names
the zone's principal country): a country that is the principal country of one zone gets it, a country principal to none
gets the one zone it shares when there is just one. A country with several zones and no declared zone, or no country
and a locale with no region, sets no zone: the browser keeps the machine's, as no guess is made (`check_places` says so
at startup).
"""

import logging
from collections import defaultdict
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from typing import TypedDict
from zoneinfo import available_timezones

from crawlerai.core.proxy import UNDECLARED, ExitPlace, ProxyPool

__all__ = ["Locality", "check_places", "exit_place", "language_headers", "locality"]

log = logging.getLogger(__name__)


class Locality(TypedDict, total=False):
    """The browser context options the locale and the egress country set (Playwright's `new_context` options)."""

    locale: str
    timezone_id: str


def locality(hint: str | None, place: ExitPlace = UNDECLARED) -> Locality:
    """The context options of the request's locale `hint` (none for no hint or one that is not a BCP 47 tag), else
    the locale `place` declares, and of `place`, the exit the render goes out from."""
    parsed = next((tag for tag in map(_parsed, (hint, place.locale)) if tag is not None), None)
    found: Locality = {}
    if parsed is not None:
        found["locale"] = "-".join(part for part in parsed if part)
    region = place.country or (None if parsed is None else parsed[2])  # the egress country, else the locale's region
    zone = place.timezone or (None if region is None else _zone(region))
    if zone is not None:
        found["timezone_id"] = zone
    return found


def language_headers(hint: str | None, place: ExitPlace = UNDECLARED) -> dict[str, str]:
    """The `Accept-Language` (RFC 9110 §12.5.4) the browser rung sends for the request's locale `hint` through an exit
    at `place`, its context's `locale` alone, for the HTTP and JSON rungs to send as well; none without a locale (the
    browser's own, which the impersonation's headers carry, `acquire.impersonate`)."""
    locale = locality(hint, place).get("locale")
    return {} if locale is None else {"Accept-Language": locale}


def exit_place(pool: str | None, pools: Mapping[str, ProxyPool] | None, direct: ExitPlace) -> ExitPlace:
    """The place a fetch through proxy pool `pool` goes out from: the pool's, `direct` without one; undeclared for a
    pool that isn't configured, which the fetch is refused for."""
    if pool is None:
        return direct
    configured = (pools or {}).get(pool)
    return UNDECLARED if configured is None else configured.place


def check_places(pools: Mapping[str, ProxyPool], direct: ExitPlace) -> None:
    """Refuse, at startup, a declared zone the tz database does not name or a locale that is no BCP 47 tag, of the
    `direct` egress or a pool; log once each whose country has several zones and that declares none: its renders keep
    the machine's zone."""
    places = {"the direct egress": direct} | {f"proxy pool {name!r}": pool.place for name, pool in pools.items()}
    for name, place in places.items():
        if place.timezone is not None and place.timezone not in available_timezones():
            raise ValueError(f"{name}: the timezone is not a zone of the IANA tz database")
        if place.locale is not None and not _well_formed(place.locale):
            raise ValueError(f"{name}: the locale is not a BCP 47 language tag")
        if place.timezone is None and place.country is not None and _zone(place.country) is None:
            log.warning(
                "%s: country %s has several time zones and none is declared; renders keep the machine's",
                name,
                place.country,
            )


def _well_formed(tag: str) -> bool:
    """A BCP 47 tag `_parsed` reads, every subtag of it one to eight ASCII letters or digits (RFC 5646 §2.1)."""
    subtags = tag.replace("_", "-").split("-")
    return _parsed(tag) is not None and all(
        1 <= len(part) <= 8 and part.isascii() and part.isalnum() for part in subtags
    )


def _parsed(hint: str | None) -> tuple[str, str | None, str | None] | None:
    """The language, script and region subtags of a BCP 47 tag (RFC 5646 §2.1), in their canonical case."""
    if hint is None:
        return None
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
