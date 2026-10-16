"""The number normalizer (SPEC-04 §4.4): a decimal number as the page states it, such as a rating value, from a JSON
number or the one number a text holds, read by the CLDR number symbols of the page's locales. The value is the
decimal in fixed-point notation with its digits as written. A text with no number, two numbers or a sign that may be
a dash declines (C7)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import number
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
EN = CTX.model_copy(update={"html_lang": "en-US"})
DE = CTX.model_copy(update={"html_lang": "de-DE"})
NUMBER = FieldSpec(type=FieldType.NUMBER)

_decimals = st.decimals(min_value=0, max_value=10**6, places=2, allow_nan=False, allow_infinity=False)
# Words around a number that hold no digit and no sign, so the text holds exactly the one number.
_before = st.sampled_from(["", "Rated ", "Score: ", "\u00a0"])
_after = st.sampled_from(["", " stars", " points", "."])


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_a_json_integer_is_its_decimal(n: int) -> None:
    assert number.normalize(n, NUMBER, CTX) == Ok(str(n))


@pytest.mark.parametrize(("raw", "value"), [(4.5, "4.5"), (0.1, "0.1"), (-2.25, "-2.25"), (1e-7, "0.0000001")])
def test_a_json_float_is_the_decimal_it_writes(raw: float, value: str) -> None:
    assert number.normalize(raw, NUMBER, CTX) == Ok(value)


@given(_decimals, _before, _after)
def test_the_one_number_in_an_english_text_is_its_value(value: Decimal, before: str, after: str) -> None:
    assert number.normalize(f"{before}{value:f}{after}", NUMBER, EN) == Ok(f"{value:f}")


def test_a_text_number_keeps_its_digits_as_written() -> None:
    assert number.normalize("4.50", NUMBER, EN) == Ok("4.50")


def test_the_page_locale_reads_the_decimal_symbol() -> None:
    assert number.normalize("4,5", NUMBER, DE) == Ok("4.5")


def test_a_number_the_locales_read_differently_is_ambiguous() -> None:
    assert number.normalize("1,250", NUMBER, CTX) == Ambiguous("decimal_separator", ("1.250", "1250"))


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("", "empty"),
        ("  ", "empty"),
        ("no rating", "no_number"),
        ("4.5 out of 5", "several_numbers"),
        ("- 4.5", "sign"),
        (True, "not_a_number"),
        (None, "not_a_number"),
        ({"ratingValue": 4}, "not_a_number"),
        ("\ud800 4", "surrogate"),
    ],
)
def test_what_states_no_single_number_declines(raw: JsonValue, reason: str) -> None:
    assert number.normalize(raw, NUMBER, EN) == Invalid(reason)


@given(_decimals)
def test_a_value_normalizes_to_itself(value: Decimal) -> None:
    first = number.normalize(f"{value:f}", NUMBER, EN)
    assert isinstance(first, Ok)
    assert number.normalize(first.value, NUMBER, EN) == first


def test_equal_compares_decimals_not_digits() -> None:
    assert equal("4.5", "4.50", NUMBER)
    assert not equal("4.5", "4.6", NUMBER)


def test_the_dispatcher_routes_the_number_type() -> None:
    assert normalize(3, NUMBER, CTX) == Ok("3")


@given(_decimals.filter(lambda d: d > 0))
def test_a_minus_sign_written_against_the_number_negates_it(value: Decimal) -> None:
    assert number.normalize(f"-{value:f}", NUMBER, EN) == Ok(f"-{value:f}")
    assert number.normalize(f"\u2212{value:f}", NUMBER, EN) == Ok(f"-{value:f}")
