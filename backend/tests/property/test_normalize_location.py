"""The location normalizer (SPEC-04 §4.4, ARCHITECTURE §9): a location publishes what the page states. Text stays
text, a `PostalAddress`'s parts stay as written, a country code only when the page states a valid ISO 3166-1 alpha-2
code, and `remote_flag` only from `TELECOMMUTE` or a `type:remote` phrase.

Place names are made up; country codes are ISO 3166-1 codes (the standard)."""

from datetime import UTC, datetime

import pytest
from pydantic import JsonValue

from crawlerai.normalize import location
from crawlerai.normalize.base import Context, Invalid, NormalizeResult, Ok
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
    return {
        "text": text,
        "locality": locality,
        "region": region,
        "country": country,
        "remote_flag": True if remote else None,
    }


def test_text_publishes_as_written_with_whitespace_collapsed_and_no_place_inferred() -> None:
    assert norm("  Lake \n Town ") == Ok(value("Lake Town"))
    # Owner, 2026-10-16 (D-0946 class 11): the location publishes as written; no "or" split, no region parsing.
    assert norm("North Region or  Lakeside, Remote") == Ok(value("North Region or Lakeside, Remote", remote=True))


@pytest.mark.parametrize(("raw", "reason"), [("", "empty"), ("—", "empty"), ("\ud800", "surrogate")])
def test_text_with_no_words_is_invalid(raw: str, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


def test_a_postal_address_keeps_its_parts_and_a_stated_code() -> None:
    address: dict[str, JsonValue] = {
        "@type": "PostalAddress",
        "addressLocality": " Alderton ",
        "addressRegion": "Upper Fen",
        "addressCountry": "de",
    }
    expected = Ok(value("Alderton, Upper Fen, de", "Alderton", "Upper Fen", "DE"))

    assert norm(address) == expected
    assert norm({"@type": "Place", "address": address}) == expected
    assert norm({**address, "addressCountry": {"@type": "Country", "identifier": "de"}}) == expected


@pytest.mark.parametrize("code", ["ZZ", "XK", "AA", "EU", "UK", "AC"])
def test_two_letters_that_are_no_iso_3166_1_code_are_invalid(code: str) -> None:
    assert norm({"addressLocality": "Alderton", "addressCountry": code}) == Invalid("unknown_country")


def test_remote_flag_is_set_by_telecommute_and_null_otherwise() -> None:
    assert norm({"addressLocality": "Alderton", "jobLocationType": "ON_SITE"}) == Ok(value("Alderton", "Alderton"))
    types: list[JsonValue] = ["TELECOMMUTE", ["ONSITE", "schema:TELECOMMUTE"], {"@id": "schema:TELECOMMUTE"}]
    for job_location_type in types:
        assert norm({"jobLocationType": job_location_type}) == Ok(value(None, remote=True))


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({}, "no_match"),
        ({"jobLocationType": "ONSITE"}, "no_match"),
        ({"jobLocationType": {"name": "TELECOMMUTE"}}, "no_match"),
        (7, "not_a_location"),
        (None, "not_a_location"),
        (["Alderton"], "not_a_location"),
    ],
)
def test_a_value_with_no_place_and_no_remote_is_invalid(raw: JsonValue, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


def test_remote_is_read_as_a_clause_of_its_own_in_the_languages_of_the_page() -> None:
    assert norm("Lakeside; Remote") == Ok(value("Lakeside; Remote", remote=True))
    assert norm("'Remote'") == Ok(value("'Remote'", remote=True))
    for text in ("Not remote", "Remote-friendly office", "Remote's office, Lakeside"):
        assert norm(text) == Ok(value(text))
    assert norm("Remote", CTX.model_copy(update={"html_lang": "xx"})) == Ok(value("Remote"))
    assert norm({"addressLocality": "Remote", "addressRegion": "Lakeside"}) == Ok(
        value("Remote, Lakeside", "Remote", "Lakeside", remote=True)
    )


def test_equality_counts_parts_only_where_both_values_state_them() -> None:
    structured = value("Alderton, Upper Fen, DE", "Alderton", "Upper Fen", "DE")

    assert location.equal(value("Alderton"), value("ALDERTON"), SPEC)
    assert location.equal(structured, value("Alderton, upper fen, DE", "ALDERTON", None, "DE"), SPEC)
    assert not location.equal(structured, value("Alderton, Upper Fen, FR", "Alderton", "Upper Fen", "FR"), SPEC)
    assert not location.equal(value("Alderton"), value("Brookfield"), SPEC)
    assert not location.equal(value("Alderton"), value("Alderton", remote=True), SPEC)
