"""The count normalizer: a non-negative whole number, such as a stock quantity, from a JSON
number, a schema.org `QuantitativeValue` (`inventoryLevel`), or the one number a text holds, read by the CLDR number
symbols of the page's locales. A fraction, a negative number, a range, a unit other than "one" and two numbers decline
(C7)."""

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from snowcrawl.normalize import count
from snowcrawl.normalize.base import Ambiguous, Context, Invalid, Ok
from snowcrawl.normalize.dispatch import equal, normalize
from snowcrawl.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 1, 1, tzinfo=UTC))
EN = CTX.model_copy(update={"html_lang": "en-US"})
DE = CTX.model_copy(update={"html_lang": "de-DE"})
COUNT = FieldSpec(type=FieldType.COUNT)

_counts = st.integers(min_value=0, max_value=10**12)


@settings(deadline=None)
@given(_counts)
def test_a_json_number_or_quantitative_value_is_its_count(n: int) -> None:
    values: tuple[JsonValue, ...] = (
        n,
        float(n),
        {"@type": "QuantitativeValue", "value": str(n)},
        {"value": n, "unitCode": "C62"},
    )

    assert [count.normalize(raw, COUNT, CTX) for raw in values] == [Ok(n)] * len(values)
    assert normalize(n, COUNT, CTX) == Ok(n)
    assert equal(n, n, COUNT)


@settings(deadline=None)
@given(_counts)
def test_the_one_number_in_a_text_is_its_count(n: int) -> None:
    assert count.normalize(f"Only {n:,} left", COUNT, EN) == Ok(n)


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (-3, "negative"),
        ("-5", "negative"),
        ("Stock: \u22125", "negative"),
        (2.5, "not_a_whole_number"),
        ("0.5", "not_a_whole_number"),
        ("3 of 10 left", "several_numbers"),
        ("1K+ reviews", "compact"),
        ("2,5 Mio.", "compact"),
        ("h1", "in_a_word"),
        ("q\u03011", "in_a_word"),
        ("In stock", "no_number"),
        ("5 \ud800", "surrogate"),
        (True, "not_a_count"),
        (None, "not_a_count"),
        (float("inf"), "not_a_count"),
        ({"@type": "QuantitativeValue", "value": 5, "unitCode": "KGM"}, "unit"),
        ({"@type": "QuantitativeValue", "minValue": 1, "maxValue": 5}, "range"),
        ({"@type": "QuantitativeValue"}, "no_value"),
        ({"value": 5, "unitCode": "C62", "unitText": "kg"}, "unit"),
    ],
)
def test_what_is_no_count_is_invalid(raw: JsonValue, reason: str) -> None:
    assert count.normalize(raw, COUNT, EN) == Invalid(reason)


def test_the_page_locale_reads_the_group_symbol() -> None:
    assert count.normalize("1.234 Stück", COUNT, DE) == Ok(1234)
    assert count.normalize("1.234", COUNT, EN) == Invalid("not_a_whole_number")
    assert count.normalize("1.234", COUNT, CTX) == Ambiguous("decimal_separator", (1234,))
