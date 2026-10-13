"""Range normalizer (SPEC-04 §4.4, ARCHITECTURE §9): `{min, max, currency, unit, period}`, which covers salary.

Accepts:
- a schema.org `MonetaryAmount` (`currency`, and `minValue`/`maxValue`/`value` either on it or on a nested
  `QuantitativeValue` under `value`, whose `unitText` gives the period), or a `QuantitativeValue` (`minValue`,
  `maxValue`, `value`, `unitText`, `unitCode`), as a JSON object;
- text: two amounts around one separator, with the period from an explicit "per X" or "/X".

Exactly one of `currency` and `unit` is set. Bounds are decimal strings. The currency of a monetary range always
comes from the money rules, which the caller passes in (the dispatcher passes the money module): this module never
reads a currency itself (C8), and it does not import the money module (the normalize-independence contract).

Declines (§9): the currency unresolved, or the period unresolved on a monetary range → `Ambiguous`; min > max →
`Invalid`. A unit range (a `QuantitativeValue` with a unit) has no period to resolve.

`equal` is a stub until SPEC-04 PR 9 implements §4.5.
"""

import re
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate
from crawlerai.schemas.types import FieldSpec, FieldType

MoneyRules = Callable[[Raw, Context], NormalizeResult]
"""The money normalizer for one value (SPEC-04 §4.4). Range passes it a structured `{"price", "priceCurrency"}` or a
text amount, and reads each value it returns as `{"amount", "currency"}` (a decimal and an ISO 4217 code)."""

# schema.org `unitText` for a salary period, per the `baseSalary` / `MonetaryAmount` guidance on JobPosting:
# HOUR, DAY, WEEK, MONTH, YEAR.
_PERIODS = ("HOUR", "DAY", "WEEK", "MONTH", "YEAR")
# The `type:period` vocabulary, language `en` (SPEC-04 §4.4): the same five units, de-capitalized, after an explicit
# "per" or "/". Justification: schema.org unitText for salary. A unit with another word around it ("hourly",
# "per hours") is not a period.
_PERIOD_TOKEN = re.compile(r"(?:\bper\s+|/\s*)(hour|day|week|month|year)\b", re.IGNORECASE)
# The range separators SPEC-04 §4.4 names: hyphen-minus, en dash (the range dash, Unicode U+2013) and `en` "to".
_SEPARATOR = re.compile(r"\s*(?:-|\u2013|\bto\b)\s*", re.IGNORECASE)
# A written amount: ASCII digits, with the grouping and decimal marks CLDR number patterns use between them (full
# stop, comma, apostrophe, space, no-break space U+00A0, narrow no-break space U+202F). Reading the amount is the
# money rules' job; this only finds where it sits in a bound, to tell the amount from the currency around it.
_AMOUNT = re.compile(r"[0-9](?:[0-9.,' \u00a0\u202f]*[0-9])?")


def normalize(raw: Raw, spec: FieldSpec, ctx: Context, *, money: MoneyRules) -> NormalizeResult:
    """Normalize a range field (SPEC-04 §4.4), resolving every currency through `money`."""
    if spec.type is not FieldType.RANGE:
        raise TypeError(f"the range normalizer does not handle type {spec.type}")
    if isinstance(raw, str):
        return _from_text(raw, ctx, money)
    if isinstance(raw, dict):
        return _from_structured(raw, ctx, money)
    return Invalid("not_a_range_value")


def _from_structured(raw: dict[str, JsonValue], ctx: Context, money: MoneyRules) -> NormalizeResult:
    # schema.org MonetaryAmount: `value` may be a number or a QuantitativeValue that carries the bounds and unitText.
    inner = raw.get("value")
    quantity = inner if isinstance(inner, dict) else raw
    bounds = _bounds(quantity)
    if isinstance(bounds, Invalid):
        return bounds
    lo, hi = bounds
    unit_text = _string(quantity.get("unitText"))
    period = unit_text.upper() if unit_text is not None else None
    period = period if period in _PERIODS else None
    currency = raw.get("currency")
    if currency is not None:
        if not isinstance(currency, str):
            return Invalid("currency_not_a_string")
        # The money rules validate the ISO 4217 code and the amounts, as they do for Offer.price+priceCurrency.
        return _monetary(
            money({"price": format(lo, "f"), "priceCurrency": currency}, ctx),
            money({"price": format(hi, "f"), "priceCurrency": currency}, ctx),
            period,
        )
    unit = _string(quantity.get("unitCode")) or (unit_text if period is None else None)
    if unit is None:
        return Ambiguous("currency_missing", ())
    if lo > hi:
        return Invalid("min_greater_than_max")
    return Ok(_value(lo, hi, currency=None, unit=unit, period=period))


def _bounds(quantity: dict[str, JsonValue]) -> tuple[Decimal, Decimal] | Invalid:
    # QuantitativeValue: `minValue` and `maxValue` bound a range; a lone `value` is both bounds.
    lo, hi = quantity.get("minValue"), quantity.get("maxValue")
    if lo is None and hi is None:
        lo = hi = quantity.get("value")
    if lo is None or hi is None:
        return Invalid("bound_missing")
    lo_number, hi_number = _decimal(lo), _decimal(hi)
    if lo_number is None or hi_number is None:
        return Invalid("bound_not_a_number")
    return lo_number, hi_number


def _decimal(value: JsonValue) -> Decimal | None:
    # schema.org Number: a JSON number or its string form. Booleans are JSON literals, not numbers.
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _string(value: JsonValue) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _from_text(raw: str, ctx: Context, money: MoneyRules) -> NormalizeResult:
    if has_surrogate(raw):
        return Invalid("surrogate")
    if not raw.strip():
        return Invalid("empty")
    periods: set[str] = set()

    def _drop_period(m: re.Match[str]) -> str:
        periods.add(m.group(1).upper())
        return " "

    text = _PERIOD_TOKEN.sub(_drop_period, raw)
    if len(periods) > 1:
        return Invalid("period_mismatch")
    # A separator splits two bounds only with an amount on each side; exactly one such separator makes a range.
    starts = [m.start() for m in _AMOUNT.finditer(text)]
    splits = [m for m in _SEPARATOR.finditer(text) if starts and starts[0] < m.start() and m.end() <= starts[-1]]
    if len(splits) != 1:
        return Invalid("not_a_range")
    left_parts = _around_amount(text[: splits[0].start()].strip())
    right_parts = _around_amount(text[splits[0].end() :].strip())
    if left_parts is None or right_parts is None:
        return Invalid("not_a_range")
    (left_before, left_amount, left_after), (right_before, right_amount, right_after) = left_parts, right_parts
    left_has, right_has = bool(left_before or left_after), bool(right_before or right_after)
    if not (left_has or right_has):
        return Ambiguous("currency_missing", ())
    # Structural: a range written with its currency once ("€10-20", "10-20 EUR") states it for both bounds, so the
    # bound without one takes the other bound's text around its amount.
    if not left_has:
        left_before, left_after = right_before, right_after
    elif not right_has:
        right_before, right_after = left_before, left_after
    return _monetary(
        money(left_before + left_amount + left_after, ctx),
        money(right_before + right_amount + right_after, ctx),
        periods.pop() if periods else None,
    )


def _around_amount(bound: str) -> tuple[str, str, str] | None:
    """`bound` as (text before, amount, text after), or `None` unless it holds exactly one amount."""
    amounts = list(_AMOUNT.finditer(bound))
    if len(amounts) != 1:
        return None
    m = amounts[0]
    return bound[: m.start()], m.group(), bound[m.end() :]


def _monetary(lo: NormalizeResult, hi: NormalizeResult, period: str | None) -> NormalizeResult:
    """Combine the money results of the two bounds: a decline on either is the range's decline (money's reason)."""
    match lo, hi:
        case (Invalid() as declined, _) | (_, Invalid() as declined):
            return declined
        case (Ambiguous(reason=reason), _) | (_, Ambiguous(reason=reason)):
            # Each reading of the range pairs a reading of each bound in the same currency.
            hi_readings = [_amount(v) for v in _options(hi)]
            options = tuple(
                _value(a[0], b[0], currency=a[1], unit=None, period=period)
                for a in map(_amount, _options(lo))
                for b in hi_readings
                if a[1] == b[1] and a[0] <= b[0]
            )
            return Ambiguous(reason, options)
        case Ok(), Ok():
            pass
    (lo_amount, lo_currency), (hi_amount, hi_currency) = _amount(lo.value), _amount(hi.value)
    if lo_currency != hi_currency:
        return Invalid("currency_mismatch")
    if lo_amount > hi_amount:
        return Invalid("min_greater_than_max")
    if period is None:
        return Ambiguous("period_missing", ())
    return Ok(_value(lo_amount, hi_amount, currency=lo_currency, unit=None, period=period))


def _options(result: NormalizeResult) -> tuple[JsonValue, ...]:
    if isinstance(result, Ok):
        return (result.value,)
    if isinstance(result, Ambiguous):
        return result.options
    raise TypeError("only Ok and Ambiguous results have readings")


def _amount(money_value: JsonValue) -> tuple[Decimal, str]:
    """A money value (`{amount, currency}`, SPEC-04 §4.4) as (amount, ISO 4217 code)."""
    fields = money_value if isinstance(money_value, dict) else {}
    amount, currency = _decimal(fields.get("amount")), fields.get("currency")
    if amount is None or not isinstance(currency, str):
        raise TypeError(f"the money rules returned {money_value!r}, not a money value")
    return amount, currency


def _value(lo: Decimal, hi: Decimal, *, currency: str | None, unit: str | None, period: str | None) -> JsonValue:
    # Plain notation, never an exponent, so a bound reads as the page wrote it ("50000", not "5E+4").
    return {"min": format(lo, "f"), "max": format(hi, "f"), "currency": currency, "unit": unit, "period": period}


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (all four parts).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b
