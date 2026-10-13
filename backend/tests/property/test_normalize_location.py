"""The location normalizer (SPEC-04 §4.4, ARCHITECTURE §9) over a small synthetic gazetteer in the GeoNames file
formats: country names and codes, regions and cities by token sequence; homonyms in several countries with no country
given decline as `Ambiguous`; no match is `Invalid`; `remote_flag` only from `TELECOMMUTE` or a `type:remote` phrase.

Country codes are ISO 3166-1 codes (the standard); every country, region and city name is made up."""

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import location
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
SPEC = FieldSpec(type=FieldType.LOCATION)

# countryInfo.txt: ISO, ISO3, ISO-Numeric, fips, Country, ...; comment lines start with `#`.
COUNTRY_INFO = """# ISO	ISO3	ISO-Numeric	fips	Country	Capital
AA	AAA	900	AA	Northland	Alderton
QM	QMM	901	QM	Southmark	Brookfield
QN	QNN	902	QN	Eastvale	Corran
"""
# admin1CodesASCII.txt: <country>.<code>, name, ascii name, geonameid.
ADMIN1 = """AA.01	Upper Fen	Upper Fen	1
AA.02	Lower Fen	Lower Fen	2
QM.01	Westshire	Westshire	3
QM.02	Eastvale	Eastvale	4
QN.01	Corran Province	Corran Province	5
"""


def _city(geonameid: int, name: str, ascii_name: str, country: str, admin1: str) -> str:
    # cities15000.txt: geonameid, name, asciiname, alternatenames, lat, lon, feature class, feature code, country
    # code, cc2, admin1 code, ...
    return "\t".join([str(geonameid), name, ascii_name, "", "0", "0", "P", "PPL", country, "", admin1, "", "", ""])


CITIES = [
    _city(10, "Alderton", "Alderton", "AA", "01"),
    _city(11, "Brookfield", "Brookfield", "QM", "01"),
    # Homonyms: one name in two countries, and twice in one country.
    _city(12, "Harwick", "Harwick", "AA", "01"),
    _city(13, "Harwick", "Harwick", "QM", "02"),
    _city(14, "Dunmore", "Dunmore", "QM", "01"),
    _city(15, "Dunmore", "Dunmore", "QM", "02"),
    # A city whose name holds a country's name; a city with a non-ASCII name.
    _city(16, "Southmark Bay", "Southmark Bay", "QM", "01"),
    _city(17, "Sankt Övel", "Sankt Ovel", "AA", "02"),
    _city(18, "Corran", "Corran", "QN", "01"),
]

GAZETTEER = location.Gazetteer.parse(COUNTRY_INFO, ADMIN1, CITIES)


def norm(raw: JsonValue, ctx: Context = CTX) -> NormalizeResult:
    return location.normalize(raw, SPEC, ctx, gazetteer=GAZETTEER)


def value(
    locality: str | None, region: str | None, country: str | None, *, remote: bool = False
) -> dict[str, JsonValue]:
    return {"locality": locality, "region": region, "country": country, "remote_flag": remote}


_separators = st.sampled_from([", ", " , ", " - ", " / ", "; ", " "])
_whitespace = st.text(alphabet=st.characters(categories=["Zs", "Cc"]).filter(str.isspace), max_size=8)

# (locality, region, country code, country name) of cities with one place per name.
_UNIQUE = [
    ("Alderton", "Upper Fen", "AA", "Northland"),
    ("Brookfield", "Westshire", "QM", "Southmark"),
    ("Sankt Övel", "Lower Fen", "AA", "Northland"),
]


# Text


@given(st.sampled_from(_UNIQUE), _separators, st.booleans(), st.booleans())
def test_a_rendered_location_normalizes_to_itself(
    place: tuple[str, str, str, str], sep: str, with_region: bool, with_country: bool
) -> None:
    locality, region, code, country = place
    parts = [locality, *([region] if with_region else []), *([country] if with_country else [])]

    assert norm(sep.join(parts)) == Ok(value(locality, region, code))


@given(st.sampled_from(["Harwick", "harwick", "HARWICK", " Harwick "]))
def test_a_city_in_several_countries_with_no_country_is_ambiguous(text: str) -> None:
    assert norm(text) == Ambiguous(
        "several_places", (value("Harwick", "Upper Fen", "AA"), value("Harwick", "Eastvale", "QM"))
    )


@given(_separators)
def test_a_country_settles_a_homonym(sep: str) -> None:
    assert norm(f"Harwick{sep}Southmark") == Ok(value("Harwick", "Eastvale", "QM"))
    assert norm(f"Harwick{sep}Northland") == Ok(value("Harwick", "Upper Fen", "AA"))


def test_a_city_named_twice_in_one_country_keeps_the_country_and_drops_the_region() -> None:
    assert norm("Dunmore") == Ok(value("Dunmore", None, "QM"))


def test_a_region_settles_a_homonym_within_a_country() -> None:
    assert norm("Dunmore, Eastvale") == Ok(value("Dunmore", "Eastvale", "QM"))


def test_a_name_that_is_both_a_country_and_a_region_alone_is_ambiguous() -> None:
    assert norm("Eastvale") == Ambiguous("several_places", (value(None, "Eastvale", "QM"), value(None, None, "QN")))


def test_a_city_settles_a_name_that_is_both_a_country_and_a_region() -> None:
    assert norm("Harwick, Eastvale") == Ok(value("Harwick", "Eastvale", "QM"))


def test_the_longest_match_wins_over_a_name_inside_it() -> None:
    assert norm("Southmark Bay") == Ok(value("Southmark Bay", "Westshire", "QM"))


def test_the_ascii_name_matches_too() -> None:
    assert norm("Sankt Ovel") == Ok(value("Sankt Övel", "Lower Fen", "AA"))


def test_a_country_alone_is_the_country() -> None:
    assert norm("Northland") == Ok(value(None, None, "AA"))


def test_a_region_alone_is_the_region_and_its_country() -> None:
    assert norm("Westshire") == Ok(value(None, "Westshire", "QM"))


def test_a_city_and_a_country_that_disagree_decline() -> None:
    assert norm("Alderton, Southmark") == Invalid("inconsistent")


def test_two_countries_decline() -> None:
    # Every place named in the text must fit the value; two countries cannot both hold.
    assert norm("Northland or Southmark") == Invalid("inconsistent")


@given(st.sampled_from(["AA", "QM", "aa", "Platform team", "Lorem ipsum"]))
def test_text_with_no_name_of_a_place_is_invalid(text: str) -> None:
    # A two-letter code is not read in text: country codes collide with region codes and with words (ISO 3166-2 and
    # ISO 3166-1 share the alphabet), so only names match.
    assert norm(text) == Invalid("no_match")


@given(_whitespace)
def test_empty_or_whitespace_text_is_invalid(text: str) -> None:
    assert norm(text) == Invalid("empty")


def test_a_lone_surrogate_is_invalid() -> None:
    assert norm("Alderton \ud800") == Invalid("surrogate")


def test_a_country_name_in_the_page_language_matches_through_cldr() -> None:
    # CLDR territory names (Babel) in the page's language; "Deutschland" is CLDR's German name for DE. DE is not
    # in this gazetteer, so a matching country must also be one GeoNames lists.
    ctx = CTX.model_copy(update={"html_lang": "de"})
    gazetteer = location.Gazetteer.parse(COUNTRY_INFO + "DE\tDEU\t276\tGM\tGermany\tBerlin\n", ADMIN1, CITIES)

    assert location.normalize("Deutschland", SPEC, ctx, gazetteer=gazetteer) == Ok(value(None, None, "DE"))
    assert norm("Deutschland", ctx) == Invalid("no_match")


# Remote


@given(st.sampled_from(["Remote", "remote", "REMOTE", "(Remote)"]))
def test_a_remote_phrase_alone_is_remote_with_no_place(text: str) -> None:
    assert norm(text) == Ok(value(None, None, None, remote=True))


def test_a_remote_phrase_with_a_place_keeps_both() -> None:
    assert norm("Remote, Northland") == Ok(value(None, None, "AA", remote=True))


def test_remote_is_read_only_in_the_languages_of_the_page() -> None:
    ctx = CTX.model_copy(update={"html_lang": "xx"})

    assert norm("Remote", ctx) == Invalid("no_match")


# Structured (schema.org Place, PostalAddress, jobLocationType)


@given(st.sampled_from(["AA", "aa", "AAA", "Northland", {"@type": "Country", "name": "Northland"}]))
def test_a_postal_address_takes_its_parts_as_given_and_the_country_as_a_code(country: JsonValue) -> None:
    address: dict[str, JsonValue] = {
        "@type": "PostalAddress",
        "addressLocality": " Somewhere ",
        "addressRegion": "Hill",
        "addressCountry": country,
    }

    assert norm(address) == Ok(value("Somewhere", "Hill", "AA"))
    assert norm({"@type": "Place", "address": address}) == Ok(value("Somewhere", "Hill", "AA"))


def test_an_unknown_country_is_invalid() -> None:
    assert norm({"addressLocality": "Alderton", "addressCountry": "Nowhere"}) == Invalid("unknown_country")


def test_an_address_without_a_country_is_read_as_text() -> None:
    assert norm({"addressLocality": "Harwick", "addressRegion": "Eastvale"}) == Ok(value("Harwick", "Eastvale", "QM"))
    assert norm({"addressLocality": "Harwick"}) == Ambiguous(
        "several_places", (value("Harwick", "Upper Fen", "AA"), value("Harwick", "Eastvale", "QM"))
    )


def test_a_place_with_only_a_name_is_read_as_text() -> None:
    assert norm({"@type": "Place", "name": "Brookfield"}) == Ok(value("Brookfield", "Westshire", "QM"))


@given(st.sampled_from(["TELECOMMUTE", "https://schema.org/TELECOMMUTE"]))
def test_telecommute_is_remote(job_location_type: str) -> None:
    assert norm({"jobLocationType": job_location_type}) == Ok(value(None, None, None, remote=True))
    assert norm({"jobLocationType": job_location_type, "addressCountry": "QM"}) == Ok(
        value(None, None, "QM", remote=True)
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({}, "no_match"),
        ({"@type": "Place"}, "no_match"),
        ({"jobLocationType": "ONSITE"}, "no_match"),
        (7, "not_a_location"),
        (None, "not_a_location"),
        (["Alderton"], "not_a_location"),
        ({"@type": "Place", "address": 7}, "not_a_location"),
    ],
)
def test_a_value_with_no_place_and_no_remote_is_invalid(raw: JsonValue, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


# Purity, dispatch and the data files


@given(st.sampled_from(["Harwick", "Alderton, Northland", "Remote", "nothing here"]))
def test_normalize_is_a_pure_function(text: str) -> None:
    assert norm(text) == norm(text)


def test_the_dispatcher_sends_location_here(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(location, "default_gazetteer", lambda: GAZETTEER)

    assert normalize("Alderton", SPEC, CTX) == Ok(value("Alderton", "Upper Fen", "AA"))


def test_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        location.normalize("Alderton", spec, CTX, gazetteer=GAZETTEER)


def test_the_gazetteer_reads_the_geonames_files(tmp_path: Path) -> None:
    (tmp_path / "countryInfo.txt").write_text(COUNTRY_INFO, encoding="utf-8")
    (tmp_path / "admin1CodesASCII.txt").write_text(ADMIN1, encoding="utf-8")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("cities15000.txt", "\n".join(CITIES) + "\n")
    (tmp_path / "cities15000.zip").write_bytes(archive.getvalue())

    assert location.Gazetteer.read(tmp_path) == GAZETTEER


def test_a_missing_gazetteer_names_the_command_that_fetches_it(tmp_path: Path) -> None:
    with pytest.raises(location.GazetteerMissing, match="crawlerai data fetch"):
        location.Gazetteer.read(tmp_path)
