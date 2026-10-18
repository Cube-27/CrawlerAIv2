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
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
RANGE = FieldSpec(type=FieldType.RANGE)
CODES = ("EUR", "USD", "JPY")
PERIODS = ("HOUR", "DAY", "WEEK", "MONTH", "YEAR")


def _money(raw: Raw, _ctx: Context) -> NormalizeResult:
    if isinstance(raw, dict):
        code, price = raw["priceCurrency"], raw["price"]
        if code not in CODES:
            return Invalid("unknown_currency")
        return _positive(Decimal(str(price)), str(code))
    assert isinstance(raw, str)
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
def test_a_monetary_amount_and_its_rendered_text_give_the_same_range(
    bounds: list[Decimal], code: str, period: str
) -> None:
    lo, hi = bounds
    structured: JsonValue = {
        "@type": "MonetaryAmount",
        "currency": code,
        "value": {"@type": "QuantitativeValue", "minValue": str(lo), "maxValue": str(hi), "unitText": period},
    }
    expected = Ok(_value(lo, hi, currency=code, period=period))

    assert norm(structured) == expected
    assert norm(f"{code} {lo} - {code} {hi} per {period.lower()}") == expected
    assert norm(f"{lo} - {hi} {code} / {period.lower()}") == expected


@given(_bounds, st.sampled_from(CODES), st.sampled_from(PERIODS))
def test_a_missing_currency_or_period_is_ambiguous(bounds: list[Decimal], code: str, period: str) -> None:
    lo, hi = bounds
    structured: JsonValue = {"currency": code, "value": {"minValue": str(lo), "maxValue": str(hi)}}

    assert norm(f"{lo} - {hi} per {period.lower()}") == Ambiguous("currency_missing", ())
    assert norm(f"{code} {lo} - {hi}") == Ambiguous("period_missing", ())
    assert norm(structured) == Ambiguous("period_missing", ())


@given(_bounds, st.sampled_from(PERIODS))
def test_an_unresolved_currency_symbol_keeps_the_money_options(bounds: list[Decimal], period: str) -> None:
    lo, hi = bounds

    result = norm(f"${lo} - ${hi} per {period.lower()}")

    assert result == Ambiguous("symbol", tuple(_value(lo, hi, currency=c, period=period) for c in ("USD", "CAD")))


@pytest.mark.parametrize("raw", ["10", "EUR 10 per year", "10 - 20 - 30 EUR", "up to EUR 20"])
def test_text_that_is_not_two_bounds_around_one_separator_is_invalid(raw: str) -> None:
    assert norm(raw) == Invalid("not_a_range")


def test_a_quantitative_value_with_a_unit_code_needs_no_period_and_a_single_value_is_both_bounds() -> None:
    unit: JsonValue = {"@type": "QuantitativeValue", "minValue": 1, "maxValue": "2.5", "unitCode": "KGM"}
    single: JsonValue = {"currency": "EUR", "value": {"value": "5", "unitText": "YEAR"}}

    assert norm(unit) == Ok(_value(Decimal(1), Decimal("2.5"), unit="KGM"))
    assert norm(single) == Ok(_value(Decimal(5), Decimal(5), currency="EUR", period="YEAR"))
