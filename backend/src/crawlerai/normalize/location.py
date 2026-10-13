"""Location normalizer (SPEC-04 §4.4, ARCHITECTURE §9): `{locality, region, country, remote_flag}`.

`country` is an ISO 3166-1 alpha-2 code, `region` a first-level division, `locality` a city; each is `None` when the
input does not state it. Accepted input:
- A string: names of places matched by token sequence against GeoNames cities, first-level divisions and countries
  (the `Gazetteer`), plus CLDR country names in the page's languages. The value is the one place every name fits.
- A schema.org `PostalAddress` (`addressLocality`, `addressRegion`, `addressCountry`), or a `Place` holding one under
  `address` or naming itself in `name`. With a country, the locality and region are taken as given; without one, they
  are read as text. A `jobLocationType` key beside them sets `remote_flag` when it is `TELECOMMUTE`.

Declines: no name of a place is `Invalid("no_match")`; names that no one place fits are `Invalid("inconsistent")`;
several places that fit, such as one city name in two countries with no country given, are `Ambiguous`. `remote_flag`
comes only from `TELECOMMUTE` or a `type:remote` phrase, never from a missing location.

`equal` is a stub until SPEC-04 PR 9 implements §4.5.
"""

import io
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from babel import Locale, UnknownLocaleError
from pydantic import JsonValue

from crawlerai.core.engine_version import backend_dir, data_dir
from crawlerai.normalize import vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate
from crawlerai.schemas.types import FieldSpec, FieldType

# GeoNames export files (https://download.geonames.org/export/dump/readme.txt), pinned in `backend/data/manifest.json`.
GEONAMES_DIR = "geonames"
COUNTRY_INFO = "countryInfo.txt"
ADMIN1 = "admin1CodesASCII.txt"
CITIES = "cities15000.zip"
_CITIES_MEMBER = "cities15000.txt"

# schema.org `jobLocationType`: "TELECOMMUTE for telecommute jobs"; JSON-LD may write it as a schema.org IRI.
_TELECOMMUTE = frozenset({"TELECOMMUTE", "https://schema.org/TELECOMMUTE", "http://schema.org/TELECOMMUTE"})


class GazetteerMissing(RuntimeError):
    """The GeoNames files are not in the data directory: a deployment error, not bad input."""


@dataclass(frozen=True, slots=True, order=True)
class Place:
    """A place at one of three levels: a country, a first-level division in it, or a city in that division."""

    country: str
    region: str | None = None
    locality: str | None = None

    def covers(self, other: "Place") -> bool:
        """Whether `other` lies in this place: same country, and the same region and city wherever this one names
        them."""
        return (
            self.country == other.country
            and self.region in (None, other.region)
            and self.locality in (None, other.locality)
        )


@dataclass(frozen=True, slots=True)
class Gazetteer:
    """Places by the token form of their names (`vocab.tokens`), and country codes by their ISO 3166-1 codes."""

    names: Mapping[vocab.Tokens, frozenset[Place]]
    codes: Mapping[str, str]  # alpha-2 and alpha-3, uppercase → alpha-2

    @classmethod
    def read(cls, directory: Path) -> "Gazetteer":
        """The gazetteer from the GeoNames files in `directory`."""
        try:
            country_info = (directory / COUNTRY_INFO).read_text(encoding="utf-8")
            admin1 = (directory / ADMIN1).read_text(encoding="utf-8")
            with zipfile.ZipFile(directory / CITIES) as archive, archive.open(_CITIES_MEMBER) as member:
                return cls.parse(country_info, admin1, io.TextIOWrapper(member, encoding="utf-8"))
        except FileNotFoundError as e:
            raise GazetteerMissing(f"{e.filename}: missing; run `crawlerai data fetch`") from None

    @classmethod
    def parse(cls, country_info: str, admin1: str, cities: Iterable[str]) -> "Gazetteer":
        """The gazetteer from the text of the three GeoNames files (tab-separated; `#` starts a comment line)."""
        names: dict[vocab.Tokens, set[Place]] = defaultdict(set)
        codes: dict[str, str] = {}
        for row in _rows(country_info.splitlines()):
            alpha2, alpha3, name = row[0], row[1], row[4]
            codes[alpha2] = codes[alpha3] = alpha2
            names[vocab.tokens(name)].add(Place(alpha2))
        regions: dict[tuple[str, str], str] = {}
        for row in _rows(admin1.splitlines()):
            country, _, code = row[0].partition(".")
            regions[country, code] = row[1]
            for name in (row[1], row[2]):
                names[vocab.tokens(name)].add(Place(country, row[1]))
        for row in _rows(cities):
            name, ascii_name, country, admin1_code = row[1], row[2], row[8], row[10]
            place = Place(country, regions.get((country, admin1_code)), name)
            for written in (name, ascii_name):
                names[vocab.tokens(written)].add(place)
        names.pop((), None)  # a name with no letters cannot be matched
        return cls({key: frozenset(places) for key, places in names.items()}, codes)


def _rows(lines: Iterable[str]) -> Iterable[list[str]]:
    for line in lines:
        if line.strip() and not line.startswith("#"):
            yield line.rstrip("\r\n").split("\t")


@cache
def default_gazetteer() -> Gazetteer:
    """The gazetteer from `backend/data/geonames/` of the source tree, read once."""
    backend = backend_dir(Path(__file__))
    if backend is None:
        raise GazetteerMissing("no backend source tree: GeoNames files are read from backend/data/geonames/")
    return Gazetteer.read(data_dir(backend) / GEONAMES_DIR)


def normalize(raw: Raw, spec: FieldSpec, ctx: Context, *, gazetteer: Gazetteer | None = None) -> NormalizeResult:
    """Normalize a location (SPEC-04 §4.4) against `gazetteer`, by default the GeoNames snapshot."""
    if spec.type is not FieldType.LOCATION:
        raise TypeError(f"the location normalizer does not handle type {spec.type}")
    if isinstance(raw, str):
        return _text(raw, gazetteer, ctx)
    if isinstance(raw, dict):
        return _structured(raw, gazetteer, ctx)
    return Invalid("not_a_location")


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (country, casefolded locality, region when both have one).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b


def _value(place: Place | None, remote: bool) -> dict[str, JsonValue]:
    return {
        "locality": place.locality if place else None,
        "region": place.region if place else None,
        "country": place.country if place else None,
        "remote_flag": remote,
    }


def _text(text: str, gazetteer: Gazetteer | None, ctx: Context) -> NormalizeResult:
    if has_surrogate(text):
        return Invalid("surrogate")
    words = vocab.tokens(text)
    if not words:
        return Invalid("empty")
    # Read only now, so input that declines on its own never needs the GeoNames files.
    gazetteer = gazetteer or default_gazetteer()
    remote = _says_remote(words, ctx)
    spans = _spans(words, gazetteer, _country_names(ctx, gazetteer))
    if not spans:
        return Ok(_value(None, remote)) if remote else Invalid("no_match")
    # A place is read from the text when every name in it fits that place: the place lies in it, or it lies in the
    # place ("Harwick, Eastvale": the city in that region). A name that is a country and a region both counts as
    # either. Of the places that fit, the most specific stand; a city settles its region and country.
    fitting = {p for span in spans for p in span if all(any(p.covers(q) or q.covers(p) for q in s) for s in spans)}
    places = {p for p in fitting if not any(p != q and p.covers(q) for q in fitting)}
    if not places:
        return Invalid("inconsistent")
    # SPEC-04 §4.4: a city name in exactly one country is that city. Where the name is in several of its regions and
    # the text names none, the region is unknown, not guessed.
    by_city: dict[tuple[str, str | None], set[str | None]] = defaultdict(set)
    for p in places:
        by_city[p.country, p.locality].add(p.region)
    merged = sorted(
        Place(country, next(iter(regions)) if len(regions) == 1 else None, locality)
        for (country, locality), regions in by_city.items()
    )
    if len(merged) > 1:
        return Ambiguous("several_places", tuple(_value(p, remote) for p in merged))
    return Ok(_value(merged[0], remote))


def _spans(words: vocab.Tokens, gazetteer: Gazetteer, countries: Mapping[vocab.Tokens, str]) -> list[frozenset[Place]]:
    """The places each name in `words` may be: names are contiguous runs of words, and a name that lies inside a
    longer one is not read (the longest match, as `vocab.Entries.find`)."""
    longest = max(map(len, gazetteer.names), default=0)
    found: list[tuple[int, int, frozenset[Place]]] = []
    for start in range(len(words)):
        for end in range(start + 1, min(len(words), start + longest) + 1):
            run = words[start:end]
            places = gazetteer.names.get(run, frozenset())
            if run in countries:
                places |= {Place(countries[run])}
            if places:
                found.append((start, end, places))
    return [
        places
        for start, end, places in found
        if not any(s <= start and end <= e and e - s > end - start for s, e, _ in found)
    ]


def _country_names(ctx: Context, gazetteer: Gazetteer) -> Mapping[vocab.Tokens, str]:
    """CLDR territory names (via Babel) in the page's languages, for the countries GeoNames lists; a name two
    territories share is dropped rather than read as either."""
    known = frozenset(gazetteer.codes.values())
    names: dict[vocab.Tokens, set[str]] = defaultdict(set)
    for language in sorted(vocab.context_languages(ctx)):
        for code, name in _territory_names(language).items():
            if code in known:
                names[vocab.tokens(name)].add(code)
    return {key: next(iter(codes)) for key, codes in names.items() if len(codes) == 1 and key}


@cache
def _territory_names(language: str) -> Mapping[str, str]:
    try:
        return dict(Locale.parse(language).territories)
    except (ValueError, UnknownLocaleError):
        return {}


def _says_remote(words: vocab.Tokens, ctx: Context) -> bool:
    by_language = vocab.type_vocabulary("remote") or {}
    # As the enum normalizer: the page's languages choose the phrases; a page that states none is read in every one.
    languages = vocab.context_languages(ctx) or by_language.keys()
    return any(by_language[language].find(words) for language in languages if language in by_language)


def _structured(raw: Mapping[str, JsonValue], gazetteer: Gazetteer | None, ctx: Context) -> NormalizeResult:
    # schema.org: `Place.address` is a PostalAddress (or text); `JobPosting.jobLocationType` is beside the location.
    remote = raw.get("jobLocationType") in _TELECOMMUTE
    address = raw.get("address", raw)
    if isinstance(address, str):
        address = {"name": address}
    if not isinstance(address, dict):
        return Invalid("not_a_location")
    locality, region = _part(address.get("addressLocality")), _part(address.get("addressRegion"))
    country_given = address.get("addressCountry")
    if country_given is not None:
        country = _country(country_given, gazetteer or default_gazetteer(), ctx)
        if country is None:
            return Invalid("unknown_country")
        return Ok(_value(Place(country, region, locality), remote))
    text = ", ".join(p for p in (locality, region) if p) or _part(raw.get("name")) or _part(address.get("name"))
    if text:
        result = _text(text, gazetteer, ctx)
        return _with_remote(result, remote) if remote else result
    return Ok(_value(None, remote)) if remote else Invalid("no_match")


def _with_remote(result: NormalizeResult, remote: bool) -> NormalizeResult:
    if isinstance(result, Ok) and isinstance(result.value, dict):
        return Ok({**result.value, "remote_flag": remote})
    return result


def _part(given: JsonValue) -> str | None:
    if not isinstance(given, str):
        return None
    return unicodedata.normalize("NFC", given).strip() or None


def _country(given: JsonValue, gazetteer: Gazetteer, ctx: Context) -> str | None:
    """`addressCountry` as an ISO 3166-1 alpha-2 code: schema.org allows the code (alpha-2 recommended) or a `Country`
    with a `name`; a name is read through GeoNames and CLDR names, and must be one country exactly."""
    if isinstance(given, dict):
        given = given.get("name")
    name = _part(given)
    if name is None:
        return None
    if code := gazetteer.codes.get(name.upper()):
        return code
    words = vocab.tokens(name)
    countries = {p.country for p in gazetteer.names.get(words, frozenset()) if p.region is None}
    if cldr := _country_names(ctx, gazetteer).get(words):
        countries.add(cldr)
    return next(iter(countries)) if len(countries) == 1 else None
