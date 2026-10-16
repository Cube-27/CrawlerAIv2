"""The location normalizer (SPEC-04 §4.4, ARCHITECTURE §9): a location publishes what the page states. Text stays
text, a `PostalAddress`'s parts stay as written, a country code only when the page states a valid ISO 3166-1 alpha-2
code, and `remote_flag` only from `TELECOMMUTE` or a `type:remote` phrase.

Place names are made up; country codes are ISO 3166-1 codes (the standard)."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import location
from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
SPEC = FieldSpec(type=FieldType.LOCATION)


def norm(raw: JsonValue, ctx: Context = CTX) -> NormalizeResult:
    return location.normalize(raw, SPEC, ctx)


def value(
    text: str | None,
    locality: str | None = None,
    region: str | None = None,
    country: str | None = None,
    *,
    remote: bool = False,
) -> dict[str, JsonValue]:
    return {"text": text, "locality": locality, "region": region, "country": country, "remote_flag": remote}


# Words that name no remote work in any language: made-up place names.
_words = st.text(st.sampled_from("abcdefghijklmnopqrstuvwxyzÅÖé"), min_size=1, max_size=8).filter(
    lambda w: w.casefold() not in {"remote"}
)
_places = st.lists(_words, min_size=1, max_size=4).map(", ".join)
_codes = st.sampled_from(sorted(location.iso_3166_alpha2()))


@given(_places, st.sampled_from(["", " ", "\t"]))
def test_text_publishes_as_written_with_no_place_inferred(place: str, padding: str) -> None:
    assert norm(f"{padding}{place}{padding}") == Ok(value(place))


@given(st.sampled_from(["Remote", "remote", "REMOTE", "(Remote)"]))
def test_a_remote_phrase_sets_the_flag_and_keeps_the_text(text: str) -> None:
    assert norm(text) == Ok(value(text, remote=True))


def test_remote_is_read_only_in_the_languages_of_the_page() -> None:
    ctx = CTX.model_copy(update={"html_lang": "xx"})

    assert norm("Remote", ctx) == Ok(value("Remote"))


@pytest.mark.parametrize(("raw", "reason"), [("", "empty"), ("  ", "empty"), ("—", "empty"), ("\ud800", "surrogate")])
def test_text_with_no_words_is_invalid(raw: str, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


# Structured (schema.org Place, PostalAddress, jobLocationType)


@given(_words, _words, _codes, st.booleans())
def test_a_postal_address_keeps_its_parts_and_a_stated_code(locality: str, region: str, code: str, lower: bool) -> None:
    written = code.lower() if lower else code
    address: dict[str, JsonValue] = {
        "@type": "PostalAddress",
        "addressLocality": f" {locality} ",
        "addressRegion": region,
        "addressCountry": written,
    }
    expected = Ok(value(f"{locality}, {region}, {written}", locality, region, code))

    assert norm(address) == expected
    assert norm({"@type": "Place", "address": address}) == expected
    assert norm({**address, "addressCountry": {"@type": "Country", "identifier": written}}) == expected


@given(st.sampled_from(["Northland", "NLD", {"@type": "Country", "name": "Northland"}]))
def test_a_country_stated_by_name_stays_in_the_text_and_gets_no_code(country: JsonValue) -> None:
    written = country["name"] if isinstance(country, dict) else country
    result = norm({"addressLocality": "Alderton", "addressCountry": country})

    assert result == Ok(value(f"Alderton, {written}", "Alderton"))


@given(st.sampled_from(["ZZ", "XK", "QM", "AA", "zz"]))
def test_two_letters_that_are_no_iso_3166_1_code_are_invalid(code: str) -> None:
    assert norm({"addressLocality": "Alderton", "addressCountry": code}) == Invalid("unknown_country")


def test_the_user_assigned_ranges_are_no_codes() -> None:
    codes = location.iso_3166_alpha2()

    assert {"DE", "US", "JP"} <= codes
    assert not codes & {"AA", "QM", "QZ", "XA", "XK", "XZ", "ZZ"}
    assert all(len(code) == 2 and code.isascii() and code.isupper() for code in codes)


def test_a_place_with_only_a_name_is_its_text() -> None:
    assert norm({"@type": "Place", "name": "Brookfield"}) == Ok(value("Brookfield"))
    assert norm({"@type": "Place", "address": "Brookfield, Westshire"}) == Ok(value("Brookfield, Westshire"))


@given(
    st.sampled_from(
        [
            "TELECOMMUTE",
            "https://schema.org/TELECOMMUTE",
            ["TELECOMMUTE"],
            ["ONSITE", "schema:TELECOMMUTE"],
            {"@id": "schema:TELECOMMUTE"},
            [{"@id": "https://schema.org/TELECOMMUTE"}],
        ]
    )
)
def test_telecommute_is_remote(job_location_type: JsonValue) -> None:
    assert norm({"jobLocationType": job_location_type}) == Ok(value(None, remote=True))
    assert norm({"jobLocationType": job_location_type, "addressCountry": "DE"}) == Ok(
        value("DE", None, None, "DE", remote=True)
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({}, "no_match"),
        ({"@type": "Place"}, "no_match"),
        ({"jobLocationType": "ONSITE"}, "no_match"),
        ({"jobLocationType": ["ONSITE"]}, "no_match"),
        ({"jobLocationType": {"@id": "ONSITE"}}, "no_match"),
        ({"jobLocationType": {"name": "TELECOMMUTE"}}, "no_match"),
        ({"jobLocationType": [[]]}, "no_match"),
        ({"jobLocationType": 7}, "no_match"),
        (7, "not_a_location"),
        (None, "not_a_location"),
        (["Alderton"], "not_a_location"),
        ({"@type": "Place", "address": 7}, "not_a_location"),
    ],
)
def test_a_value_with_no_place_and_no_remote_is_invalid(raw: JsonValue, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


# Equality (SPEC-04 §4.5)


@given(_places)
def test_text_compares_by_words(place: str) -> None:
    assert location.equal(value(place), value(place.upper().replace(", ", " ")), SPEC)


def test_parts_count_where_both_values_state_them() -> None:
    structured = value("Alderton, Upper Fen, DE", "Alderton", "Upper Fen", "DE")

    assert location.equal(structured, value("Alderton, upper fen, DE", "ALDERTON", None, "DE"), SPEC)
    assert not location.equal(structured, value("Alderton, Upper Fen, FR", "Alderton", "Upper Fen", "FR"), SPEC)
    assert not location.equal(structured, value("Alderton, Upper Fen, DE"), SPEC)
    assert not location.equal(value("Alderton"), value("Brookfield"), SPEC)
    assert not location.equal(value("Alderton"), value("Alderton", remote=True), SPEC)


# Dispatch


def test_the_dispatcher_sends_location_here() -> None:
    assert normalize("Alderton", SPEC, CTX) == Ok(value("Alderton"))


def test_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        location.normalize("Alderton", spec, CTX)
