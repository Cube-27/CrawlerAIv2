"""The range normalizer (SPEC-04 §4.4, ARCHITECTURE §9): schema.org `MonetaryAmount` / `QuantitativeValue` and
text, with currency resolved by the money rules. Declines when the period or the currency is unresolved, and when
min > max.

The money rules are passed in (the dispatcher passes the money module). These tests pass a stand-in that follows
the money contract on ISO 4217 codes only, and reads a bare `$` as ambiguous, so they pin what range does with each
money result, not the money rules themselves.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import range as range_
from crawlerai.normalize import vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
RANGE = FieldSpec(type=FieldType.RANGE)
CODES = ("EUR", "USD", "JPY")
PERIODS = ("HOUR", "DAY", "WEEK", "MONTH", "YEAR")


def _money(raw: Raw, _ctx: Context) -> NormalizeResult:
    if isinstance(raw, dict):
        return _structured_money(raw)
    assert isinstance(raw, str)
    return _text_money(raw)


def _structured_money(raw: dict[str, JsonValue]) -> NormalizeResult:
    code, price = raw["priceCurrency"], raw["price"]
    if code not in CODES:
        return Invalid("unknown_currency")
    return _positive(Decimal(str(price)), str(code))


def _text_money(raw: str) -> NormalizeResult:
    number = re.search(r"[0-9]+(?:\.[0-9]+)?", raw)
    if number is None:
        return Invalid("no_number")
    amount = Decimal(number.group())
    codes = [c for c in CODES if c in raw]
    if "$" in raw and not codes:
        return Ambiguous("symbol", tuple({"amount": str(amount), "currency": c} for c in ("USD", "CAD")))
    if len(codes) != 1:
        return Invalid("no_currency")
    return _positive(amount, codes[0])


def _positive(amount: Decimal, code: str) -> NormalizeResult:
    if amount <= 0:
        return Invalid("not_positive")
    return Ok({"amount": str(amount), "currency": code})


def norm(raw: JsonValue) -> NormalizeResult:
    return range_.normalize(raw, RANGE, CTX, money=_money)


def _value(
    lo: Decimal, hi: Decimal, *, currency: str | None = None, unit: str | None = None, period: str | None = None
) -> dict[str, JsonValue]:
    return {"min": str(lo), "max": str(hi), "currency": currency, "unit": unit, "period": period}


_amounts = st.decimals(min_value=1, max_value=10**6, places=2)
_bounds = st.tuples(_amounts, _amounts).map(sorted)


@given(_bounds, st.sampled_from(CODES), st.sampled_from(PERIODS))
def test_a_monetary_amount_round_trips(bounds: list[Decimal], code: str, period: str) -> None:
    lo, hi = bounds
    raw: JsonValue = {
        "@type": "MonetaryAmount",
        "currency": code,
        "value": {"@type": "QuantitativeValue", "minValue": str(lo), "maxValue": str(hi), "unitText": period},
    }

    assert norm(raw) == Ok(_value(lo, hi, currency=code, period=period))


@given(_bounds, st.sampled_from(CODES), st.sampled_from(PERIODS), st.sampled_from([" - ", "\u2013", " to ", "-"]))
def test_rendered_text_round_trips(bounds: list[Decimal], code: str, period: str, separator: str) -> None:
    lo, hi = bounds
    raw = f"{code} {lo}{separator}{code} {hi} per {period.lower()}"

    assert norm(raw) == Ok(_value(lo, hi, currency=code, period=period))


@given(_bounds, st.sampled_from(CODES), st.sampled_from(PERIODS))
def test_a_currency_written_once_applies_to_both_bounds(bounds: list[Decimal], code: str, period: str) -> None:
    lo, hi = bounds
    expected = Ok(_value(lo, hi, currency=code, period=period))

    assert norm(f"{code}{lo} - {hi}/{period.title()}") == expected
    assert norm(f"{lo} - {hi} {code} / {period.lower()}") == expected


@given(_bounds, st.sampled_from(PERIODS))
def test_text_without_a_currency_is_ambiguous(bounds: list[Decimal], period: str) -> None:
    lo, hi = bounds

    assert norm(f"{lo} - {hi} per {period.lower()}") == Ambiguous("currency_missing", ())


@given(_bounds, st.sampled_from(CODES))
def test_a_missing_period_is_ambiguous(bounds: list[Decimal], code: str) -> None:
    lo, hi = bounds
    structured: JsonValue = {"currency": code, "value": {"minValue": str(lo), "maxValue": str(hi)}}

    assert norm(f"{code} {lo} - {hi}") == Ambiguous("period_missing", ())
    assert norm(structured) == Ambiguous("period_missing", ())


@given(_bounds, st.sampled_from(CODES), st.sampled_from(["per hours", "per hourly", "/ annum", "a year", "today"]))
def test_only_a_period_unit_after_per_or_slash_is_a_period(bounds: list[Decimal], code: str, tail: str) -> None:
    lo, hi = bounds

    # The words stay in the upper bound, and money declines it.
    assert norm(f"{code} {lo} - {hi} {tail}") == Invalid("no_currency")


@given(_bounds, st.sampled_from(PERIODS))
def test_an_unresolved_currency_symbol_keeps_the_money_options(bounds: list[Decimal], period: str) -> None:
    lo, hi = bounds

    result = norm(f"${lo} - ${hi} per {period.lower()}")

    assert result == Ambiguous("symbol", tuple(_value(lo, hi, currency=c, period=period) for c in ("USD", "CAD")))


@given(_bounds.filter(lambda b: b[0] < b[1]), st.sampled_from(CODES), st.sampled_from(PERIODS))
def test_min_greater_than_max_is_invalid(bounds: list[Decimal], code: str, period: str) -> None:
    lo, hi = bounds
    structured: JsonValue = {"currency": code, "minValue": str(hi), "maxValue": str(lo)}

    assert norm(f"{code} {hi} - {lo} per {period.lower()}") == Invalid("min_greater_than_max")
    assert norm(structured) == Invalid("min_greater_than_max")


@given(_bounds)
def test_bounds_in_two_currencies_are_invalid(bounds: list[Decimal]) -> None:
    lo, hi = bounds

    assert norm(f"EUR {lo} - USD {hi} per year") == Invalid("currency_mismatch")


@given(_bounds, st.sampled_from(CODES))
def test_two_different_periods_are_invalid(bounds: list[Decimal], code: str) -> None:
    lo, hi = bounds

    assert norm(f"{code} {lo}/hour - {code} {hi}/day") == Invalid("period_mismatch")


def test_a_money_decline_on_either_bound_is_the_range_decline() -> None:
    assert norm({"currency": "XXX", "minValue": 1, "maxValue": 2}) == Invalid("unknown_currency")
    assert norm("EUR 0 - 5 per year") == Invalid("not_positive")


@given(st.sampled_from(["10", "EUR 10 per year", "10 - 20 - 30 EUR", "up to EUR 20", "EUR - per year"]))
def test_text_that_is_not_two_bounds_around_one_separator_is_invalid(raw: str) -> None:
    assert norm(raw) == Invalid("not_a_range")


@given(_bounds, st.sampled_from(["KGM", "MTR", "CMT"]))
def test_a_quantitative_value_with_a_unit_code_needs_no_period(bounds: list[Decimal], unit: str) -> None:
    lo, hi = bounds
    raw: JsonValue = {"@type": "QuantitativeValue", "minValue": float(lo), "maxValue": str(hi), "unitCode": unit}

    assert norm(raw) == Ok(_value(Decimal(str(float(lo))), hi, unit=unit))


@given(_amounts, st.sampled_from(CODES), st.sampled_from(PERIODS))
def test_a_single_value_is_both_bounds(amount: Decimal, code: str, period: str) -> None:
    raw: JsonValue = {"currency": code, "value": {"value": str(amount), "unitText": period}}

    assert norm(raw) == Ok(_value(amount, amount, currency=code, period=period))


@given(st.sampled_from(PERIODS))
def test_a_quantitative_value_with_only_a_period_is_ambiguous(period: str) -> None:
    assert norm({"minValue": 1, "maxValue": 2, "unitText": period}) == Ambiguous("currency_missing", ())


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ({"currency": "EUR", "minValue": 1}, "bound_missing"),
        ({"currency": "EUR", "minValue": True, "maxValue": 2}, "bound_not_a_number"),
        ({"minValue": "1", "maxValue": "NaN", "unitCode": "KGM"}, "bound_not_a_number"),
        ({"minValue": "one", "maxValue": "2", "unitCode": "KGM"}, "bound_not_a_number"),
        ({"currency": "EUR", "value": [1, 2]}, "bound_not_a_number"),
        ({"currency": 978, "minValue": 1, "maxValue": 2}, "currency_not_a_string"),
        ([1, 2], "not_a_range_value"),
        (3, "not_a_range_value"),
        (None, "not_a_range_value"),
    ],
)
def test_malformed_structured_input_is_invalid(raw: JsonValue, reason: str) -> None:
    assert norm(raw) == Invalid(reason)


def test_another_type_is_a_programming_error() -> None:
    money = FieldSpec(type=FieldType.MONEY)

    with pytest.raises(TypeError):
        range_.normalize("EUR 1 - 2", money, CTX, money=_money)


@given(_bounds, st.sampled_from(CODES), st.sampled_from(PERIODS), st.sampled_from(["per ", "/"]))
def test_the_period_words_are_those_of_the_page_language(
    bounds: list[Decimal], code: str, period: str, marker: str
) -> None:
    lo, hi = bounds
    raw = f"{code} {lo} - {hi} {marker}{period.lower()}"

    def in_language(html_lang: str) -> NormalizeResult:
        return range_.normalize(raw, RANGE, Context(captured_at=AT, html_lang=html_lang), money=_money)

    assert in_language("en-GB") == Ok(_value(lo, hi, currency=code, period=period))
    # The `type:period` vocabulary has no `de` phrases, so on a German page the English words are not a period, and
    # money declines the bound they stay in.
    assert in_language("de") == Invalid("no_currency")


def test_the_period_vocabulary_names_each_schema_org_salary_unit_once() -> None:
    by_language = vocab.type_vocabulary("period")

    assert by_language is not None
    assert sorted(by_language["en"].phrases.values()) == sorted(PERIODS)


@given(_bounds, st.sampled_from(CODES))
def test_the_word_separator_is_that_of_the_page_language(bounds: list[Decimal], code: str) -> None:
    lo, hi = bounds

    def in_language(raw: str, html_lang: str) -> NormalizeResult:
        return range_.normalize(raw, RANGE, Context(captured_at=AT, html_lang=html_lang), money=_money)

    assert in_language(f"{code} {lo} to {code} {hi} per year", "en") == Ok(_value(lo, hi, currency=code, period="YEAR"))
    # The `type:range_to` vocabulary has no `de` words, so on a German page "to" separates nothing; a dash does.
    assert in_language(f"{code} {lo} to {code} {hi}", "de") == Invalid("not_a_range")
    assert in_language(f"{code} {lo} - {code} {hi}", "de") == Ambiguous("period_missing", ())
