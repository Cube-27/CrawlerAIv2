"""The count normalizer (SPEC-04 §4.4, D-0782): a non-negative whole number, such as a stock quantity, from a JSON
number, a schema.org `QuantitativeValue` (`inventoryLevel`), or the one number a text holds, read by the CLDR number
symbols of the page's locales. A fraction, a negative number, a range, a unit other than "one" and two numbers decline
(C7)."""

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import count
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
EN = CTX.model_copy(update={"html_lang": "en-US"})
DE = CTX.model_copy(update={"html_lang": "de-DE"})
COUNT = FieldSpec(type=FieldType.COUNT)

_counts = st.integers(min_value=0, max_value=10**12)
# Words around a number that hold no digit, so the text holds exactly the one number.
_words = st.sampled_from(["", "In stock (", "Only ", "Qty: ", "\u00a0"])
_after = st.sampled_from(["", " available)", " left", " in stock", "."])


@given(_counts)
def test_a_json_whole_number_is_its_count(n: int) -> None:
    assert count.normalize(n, COUNT, CTX) == Ok(n)


@given(_counts)
def test_a_json_number_with_no_fraction_is_its_count(n: int) -> None:
    assert count.normalize(float(n), COUNT, CTX) == Ok(int(float(n)))


@given(st.integers(max_value=-1))
def test_a_negative_number_is_invalid(n: int) -> None:
    assert count.normalize(n, COUNT, CTX) == Invalid("negative")
    assert count.normalize(str(n), COUNT, EN) == Invalid("negative")


@pytest.mark.parametrize("raw", [2.5, "2.5", "0.5"])
def test_a_fraction_is_invalid(raw: JsonValue) -> None:
    assert count.normalize(raw, COUNT, EN) == Invalid("not_a_whole_number")


@given(_counts, _words, _after)
def test_the_one_number_in_a_text_is_its_count(n: int, before: str, after: str) -> None:
    assert count.normalize(f"{before}{n:,}{after}", COUNT, EN) == Ok(n)


def test_the_page_locale_reads_the_group_symbol() -> None:
    # CLDR: `.` groups digits in de, and is the decimal symbol in en.
    assert count.normalize("1.234 Stück", COUNT, DE) == Ok(1234)
    assert count.normalize("1.234", COUNT, EN) == Invalid("not_a_whole_number")


def test_a_number_the_locales_read_two_ways_is_ambiguous() -> None:
    # No page locale: `1.234` is 1234 where `.` groups digits and 1.234 where it is the decimal symbol.
    assert count.normalize("1.234", COUNT, CTX) == Ambiguous("decimal_separator", (1234,))


@pytest.mark.parametrize("raw", ["3 of 10 left", "2 to 5 in stock", "Pack of 6, 12 available"])
def test_a_text_with_two_numbers_is_invalid(raw: str) -> None:
    assert count.normalize(raw, COUNT, EN) == Invalid("several_numbers")


@pytest.mark.parametrize("raw", ["In stock", "Available", "few"])
def test_a_text_without_a_number_is_invalid(raw: str) -> None:
    assert count.normalize(raw, COUNT, EN) == Invalid("no_number")


@given(_counts)
def test_a_quantitative_value_is_its_value(n: int) -> None:
    values: tuple[JsonValue, ...] = (
        {"@type": "QuantitativeValue", "value": n},
        {"@type": "QuantitativeValue", "value": str(n)},
        {"value": n, "unitCode": "C62"},
    )

    assert [count.normalize(raw, COUNT, CTX) for raw in values] == [Ok(n)] * len(values)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"@type": "QuantitativeValue", "value": 5, "unitCode": "KGM"}, "unit"),
        ({"@type": "QuantitativeValue", "value": 5, "unitText": "kg"}, "unit"),
        ({"@type": "QuantitativeValue", "minValue": 1, "maxValue": 5}, "range"),
        ({"@type": "QuantitativeValue"}, "no_value"),
        ({"@type": "QuantitativeValue", "value": -1}, "negative"),
        ({"@type": "QuantitativeValue", "value": [1, 2]}, "not_a_count"),
    ],
)
def test_a_quantitative_value_that_is_no_count_is_invalid(raw: JsonValue, reason: str) -> None:
    assert count.normalize(raw, COUNT, CTX) == Invalid(reason)


@pytest.mark.parametrize("raw", [True, None, [5], float("inf")])
def test_other_json_values_are_invalid(raw: JsonValue) -> None:
    assert count.normalize(raw, COUNT, CTX) == Invalid("not_a_count")


def test_a_lone_surrogate_is_invalid() -> None:
    assert count.normalize("5 \ud800", COUNT, CTX) == Invalid("surrogate")


@given(_counts)
def test_normalizing_a_count_again_gives_the_same_count(n: int) -> None:
    once = normalize(n, COUNT, CTX)

    assert isinstance(once, Ok)
    assert normalize(once.value, COUNT, CTX) == once


@given(_counts, _counts)
def test_two_counts_are_equal_exactly_when_they_are_the_same_number(a: int, b: int) -> None:
    assert equal(a, b, COUNT) == (a == b)


def test_a_spec_of_another_type_is_a_programming_error() -> None:
    spec = FieldSpec(type=FieldType.TEXT)

    with pytest.raises(TypeError):
        count.normalize("5", spec, CTX)


@pytest.mark.parametrize("text", ["In stock - 5 left", "Qty \u2013 5", "5 left - in stock"])
def test_a_minus_set_apart_from_the_number_is_punctuation(text: str) -> None:
    assert count.normalize(text, COUNT, EN) == Ok(5)


def test_a_minus_against_the_number_still_negates_it() -> None:
    assert count.normalize("Stock: -5", COUNT, EN) == Invalid("negative")
    assert count.normalize("Stock: \u22125", COUNT, EN) == Invalid("negative")


@pytest.mark.parametrize("unit_text", ["kg", "Kilograms", " km "])
def test_a_measurement_unit_beside_c62_declines(unit_text: str) -> None:
    raw: JsonValue = {"value": 5, "unitCode": "C62", "unitText": unit_text}

    assert count.normalize(raw, COUNT, EN) == Invalid("unit")
    assert count.normalize(raw, COUNT, CTX) == Invalid("unit")  # no page language: every language's units


@pytest.mark.parametrize("unit_text", ["items", "pieces", "units in stock"])
def test_a_unit_text_naming_no_measurement_unit_does_not_contradict_c62(unit_text: str) -> None:
    raw: JsonValue = {"value": 5, "unitCode": "C62", "unitText": unit_text}

    assert count.normalize(raw, COUNT, EN) == Ok(5)
