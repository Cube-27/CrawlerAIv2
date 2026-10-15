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
"""

import io
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from babel import Locale, UnknownLocaleError
from pydantic import JsonValue

from crawlerai.core.engine_version import data_dir, engine_dir
from crawlerai.normalize import vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate
from crawlerai.schemas.types import FieldSpec, FieldType

# GeoNames export files (https://download.geonames.org/export/dump/readme.txt), pinned in `backend/data/manifest.json`.
GEONAMES_DIR = "geonames"
COUNTRY_INFO = "countryInfo.txt"
ADMIN1 = "admin1CodesASCII.txt"
CITIES = "cities15000.zip"
_CITIES_MEMBER = "cities15000.txt"

# schema.org `jobLocationType`: "TELECOMMUTE for telecommute jobs"; JSON-LD may write it as a schema.org IRI or a
# compact IRI (JSON-LD 1.1 §4.1.5).
_TELECOMMUTE = frozenset(
    {"TELECOMMUTE", "https://schema.org/TELECOMMUTE", "http://schema.org/TELECOMMUTE", "schema:TELECOMMUTE"}
)

# The keys of a normalized location (the module docstring).
_VALUE_KEYS = frozenset({"locality", "region", "country", "remote_flag"})


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
    longest: int  # the most words in one name
    _cldr: dict[frozenset[str], Mapping[vocab.Tokens, str]] = field(default_factory=dict, compare=False, repr=False)

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
            for written in {name, ascii_name}:
                names[vocab.tokens(written)].add(place)
        names.pop((), None)  # a name with no letters cannot be matched
        return cls({key: frozenset(places) for key, places in names.items()}, codes, max(map(len, names), default=0))

    def country_names(self, languages: frozenset[str]) -> Mapping[vocab.Tokens, str]:
        """CLDR territory names (via Babel) in `languages`, for the countries GeoNames lists; a name two territories
        share is dropped rather than read as either. Built once per language set."""
        if (cached := self._cldr.get(languages)) is not None:
            return cached
        known = frozenset(self.codes.values())
        names: dict[vocab.Tokens, set[str]] = defaultdict(set)
        for language in languages:
            for code, name in _territory_names(language).items():
                if code in known:
                    names[vocab.tokens(name)].add(code)
        result = {key: next(iter(codes)) for key, codes in names.items() if len(codes) == 1 and key}
        self._cldr[languages] = result
        return result


def _rows(lines: Iterable[str]) -> Iterable[list[str]]:
    for line in lines:
        if line.strip() and not line.startswith("#"):
            yield line.rstrip("\r\n").split("\t")


@cache
def default_gazetteer() -> Gazetteer:
    """The gazetteer from the engine directory's `data/geonames/`, read once."""
    engine = engine_dir(Path(__file__))
    if engine is None:
        raise GazetteerMissing("no engine directory: GeoNames files are read from its data/geonames/")
    return Gazetteer.read(data_dir(engine) / GEONAMES_DIR)


def normalize(raw: Raw, spec: FieldSpec, ctx: Context, *, gazetteer: Gazetteer | None = None) -> NormalizeResult:
    """Normalize a location (SPEC-04 §4.4) against `gazetteer`, by default the GeoNames snapshot."""
    if spec.type is not FieldType.LOCATION:
        raise TypeError(f"the location normalizer does not handle type {spec.type}")
    if isinstance(raw, str):
        return _text(raw, gazetteer, ctx)
    if isinstance(raw, dict):
        return _structured(raw, gazetteer, ctx)
    return Invalid("not_a_location")


def equal(a: JsonValue, b: JsonValue, _spec: FieldSpec) -> bool:
    """SPEC-04 §4.5: `country` equal and `locality` equal after Unicode case folding; `region` counts only when both
    values have one; `remote_flag` equal, since a remote job and an on-site one differ. Not transitive: a place
    without a region equals two places in different regions."""
    if a == b:
        return True
    if not (isinstance(a, dict) and isinstance(b, dict) and a.keys() == b.keys() == _VALUE_KEYS):
        return False
    a_region, b_region = a["region"], b["region"]
    return (
        a["country"] == b["country"]
        and a["remote_flag"] == b["remote_flag"]
        and _casefolded(a["locality"]) == _casefolded(b["locality"])
        and (a_region is None or b_region is None or a_region == b_region)
    )


def _casefolded(value: JsonValue) -> JsonValue:
    return value.casefold() if isinstance(value, str) else value


def _value(place: Place | None, remote: bool) -> dict[str, JsonValue]:
    return {
        "locality": place.locality if place else None,
        "region": place.region if place else None,
        "country": place.country if place else None,
        "remote_flag": remote,
    }


def _text(text: str, gazetteer: Gazetteer | None, ctx: Context, *, remote: bool = False) -> NormalizeResult:
    if has_surrogate(text):
        return Invalid("surrogate")
    words = vocab.tokens(text)
    if not words:
        return Invalid("empty")
    # Read only now, so input that declines on its own never needs the GeoNames files.
    gazetteer = gazetteer or default_gazetteer()
    remote = remote or _says_remote(words, ctx)
    spans = _spans(words, gazetteer, gazetteer.country_names(vocab.context_languages(ctx)))
    if not spans:
        return _nothing(remote)
    places = _most_specific_fitting(spans)
    if not places:
        return Invalid("inconsistent")
    merged = _merged_by_city(places)
    if len(merged) > 1:
        return Ambiguous("several_places", tuple(_value(p, remote) for p in merged))
    return Ok(_value(merged[0], remote))


def _most_specific_fitting(spans: list[frozenset[Place]]) -> set[Place]:
    """A place is read from the text when every name in it fits that place: the place lies in it, or it lies in the
    place ("Harwick, Eastvale": the city in that region). A name that is a country and a region both counts as
    either. Of the places that fit, the most specific stand; a city settles its region and country."""
    fitting = {p for span in spans for p in span if all(any(p.covers(q) or q.covers(p) for q in s) for s in spans)}
    return {p for p in fitting if not any(p != q and p.covers(q) for q in fitting)}


def _merged_by_city(places: set[Place]) -> list[Place]:
    """SPEC-04 §4.4: a city name in exactly one country is that city. Where the name is in several of its regions and
    the text names none, the region is unknown, not guessed."""
    by_city: dict[tuple[str, str | None], set[str | None]] = defaultdict(set)
    for p in places:
        by_city[p.country, p.locality].add(p.region)
    return sorted(
        Place(country, next(iter(regions)) if len(regions) == 1 else None, locality)
        for (country, locality), regions in by_city.items()
    )


def _spans(words: vocab.Tokens, gazetteer: Gazetteer, countries: Mapping[vocab.Tokens, str]) -> list[frozenset[Place]]:
    """The places each name in `words` may be: names are contiguous runs of words, and a name that lies inside a
    longer one is not read (the longest match, as `vocab.Entries.find`).

    Country codes are not read in text: ISO 3166-1 alpha-2 codes share their alphabet with the ISO 3166-2 subdivision
    codes that addresses also abbreviate to ("IL", "CA") and with short words, so a code alone names no one place."""
    found: list[tuple[int, int, frozenset[Place]]] = []
    for start in range(len(words)):
        for end in range(start + 1, min(len(words), start + gazetteer.longest) + 1):
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


@cache
def _territory_names(language: str) -> Mapping[str, str]:
    try:
        return dict(Locale.parse(language).territories)
    except (ValueError, UnknownLocaleError):
        return {}


def _telecommute(value: JsonValue) -> bool:
    """Whether a `jobLocationType` value is TELECOMMUTE. JSON-LD 1.1 lets a property hold an array of values (§4.3)
    or a node object naming its IRI in `@id` (§4.1); any one TELECOMMUTE value makes the job remote."""
    if isinstance(value, list):
        return any(_telecommute(item) for item in value)
    if isinstance(value, dict):
        value = value.get("@id")
    return isinstance(value, str) and value in _TELECOMMUTE


def _says_remote(words: vocab.Tokens, ctx: Context) -> bool:
    return bool(vocab.find_codes(vocab.type_vocabulary("remote") or {}, words, ctx))


def _nothing(remote: bool) -> NormalizeResult:
    """No place: a remote job with no location, or nothing at all (never remote by absence; SPEC-04 §4.4)."""
    return Ok(_value(None, remote)) if remote else Invalid("no_match")


def _structured(raw: Mapping[str, JsonValue], gazetteer: Gazetteer | None, ctx: Context) -> NormalizeResult:
    # schema.org: `Place.address` is a PostalAddress (or text); `JobPosting.jobLocationType` is beside the location.
    remote = _telecommute(raw.get("jobLocationType"))
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
        return _text(text, gazetteer, ctx, remote=remote)
    return _nothing(remote)


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
    if cldr := gazetteer.country_names(vocab.context_languages(ctx)).get(words):
        countries.add(cldr)
    return next(iter(countries)) if len(countries) == 1 else None
