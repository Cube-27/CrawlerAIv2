"""Range normalizer (SPEC-04 §4.4, ARCHITECTURE §9): `{min, max, currency, unit, period}`, which covers salary.

Accepts:
- a schema.org `MonetaryAmount` (`currency`, and `minValue`/`maxValue`/`value` either on it or on a nested
  `QuantitativeValue` under `value`, whose `unitText` gives the period), or a `QuantitativeValue` (`minValue`,
  `maxValue`, `value`, `unitText`, `unitCode`), as a JSON object;
- text: two amounts around one separator, with the period from an explicit "per X" or "/X".

The period of a monetary range is read from `unitText`, else `unitCode`, in any of the forms `_period` lists: a
schema.org unit word, an interval of one unit ("1 YEAR"), an ISO 8601 duration of one unit ("P1Y"), a UN/CEFACT
Recommendation 20 code ("ANN"), or a `type:period` phrase of the page's languages ("per year").

Exactly one of `currency` and `unit` is set. Bounds are decimal strings. The currency of a monetary range always
comes from the money rules, which the caller passes in (the dispatcher passes the money module): this module never
reads a currency itself (C8), and it does not import the money module (the normalize-independence contract).

Declines (§9): the currency unresolved, or the period unresolved on a monetary range → `Ambiguous`; min > max →
`Invalid`. A unit range (a `QuantitativeValue` with a unit) has no period to resolve.
"""

import re
from collections.abc import Callable, Hashable
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from pydantic import JsonValue

from crawlerai.normalize import vocab
from crawlerai.normalize.base import (
    Ambiguous,
    Context,
    Invalid,
    NormalizeResult,
    Ok,
    Raw,
    frozen,
    has_surrogate,
    raw_key,
)
from crawlerai.schemas.types import FieldSpec, FieldType

MoneyRules = Callable[[Raw, Context], NormalizeResult]
"""The money normalizer for one value (SPEC-04 §4.4). Range passes it a structured `{"price", "priceCurrency"}` or a
text amount, and reads each value it returns as `{"amount", "currency"}` (a decimal and an ISO 4217 code)."""

# schema.org `unitText` for a salary period, per the `baseSalary` / `MonetaryAmount` guidance on JobPosting:
# HOUR, DAY, WEEK, MONTH, YEAR.
_PERIODS = ("HOUR", "DAY", "WEEK", "MONTH", "YEAR")
# The `type:period` vocabulary (SPEC-04 §4.4) maps each phrase to one of these units; its JUSTIFICATION.md names the
# source.
_PERIOD_VOCABULARY = "period"
# An interval written as a count of one and a unit word ("1 YEAR"): ISO 80000-1 writes a quantity as a number and a
# unit, and one unit is the period itself.
_ONE_UNIT = re.compile(rf"1\s+({'|'.join(_PERIODS)})", re.IGNORECASE | re.ASCII)
# ISO 8601-1 §5.5.2 durations of exactly one unit (`P1Y`, `P1M`, `P1W`, `P1D`, `PT1H`); more than one unit ("P1Y6M") or
# another count is not a period.
_ISO_DURATION = re.compile(r"P(?:1([YMWD])|T1(H))", re.ASCII)
_ISO_DURATION_UNITS = {"Y": "YEAR", "M": "MONTH", "W": "WEEK", "D": "DAY", "H": "HOUR"}
# UN/CEFACT Recommendation 20 common codes of the schema.org `unitCode` for each period (annum, month, week, day,
# hour).
_UN_CEFACT_PERIODS = {"ANN": "YEAR", "MON": "MONTH", "WEE": "WEEK", "DAY": "DAY", "HUR": "HOUR"}
# The range separators SPEC-04 §4.4 names: hyphen-minus and en dash (the range dash, Unicode U+2013), in any language;
# the `type:range_to` vocabulary holds the words, such as `en` "to", for the page's languages.
_DASHES = r"-|\u2013"
_SEPARATOR_VOCABULARY = "range_to"
# A written amount: ASCII digits (`re.ASCII`), with the grouping and decimal marks CLDR number patterns use between
# them (full stop, comma, apostrophe, space, no-break space U+00A0, narrow no-break space U+202F). Reading the amount
# is the money rules' job; this only finds where it sits in a bound, to tell the amount from the currency around it.
_AMOUNT = re.compile(r"\d(?:[\d.,' \u00a0\u202f]*\d)?", re.ASCII)

# The keys of a normalized range (D-0276).
_VALUE_KEYS = frozenset({"min", "max", "currency", "unit", "period"})


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
    unit_text, unit_code = _string(quantity.get("unitText")), _string(quantity.get("unitCode"))
    currency = raw.get("currency")
    if currency is not None:
        if not isinstance(currency, str):
            return Invalid("currency_not_a_string")
        # The money rules validate the ISO 4217 code and the amounts, as they do for Offer.price+priceCurrency.
        return _monetary(
            money({"price": format(lo, "f"), "priceCurrency": currency}, ctx),
            money({"price": format(hi, "f"), "priceCurrency": currency}, ctx),
            _period(unit_text, ctx) or _period(unit_code, ctx),
        )
    period = unit_text.upper() if unit_text is not None else None
    period = period if period in _PERIODS else None
    unit = unit_code or (unit_text if period is None else None)
    if unit is None:
        return Ambiguous("currency_missing", ())
    if lo > hi:
        return Invalid("min_greater_than_max")
    return Ok(_value(lo, hi, currency=None, unit=unit, period=period))


def _period(written: str | None, ctx: Context) -> str | None:
    """The `_PERIODS` unit an interval written as `written` names, or `None` when it names none."""
    if written is None:
        return None
    upper = written.upper()
    if upper in _PERIODS:
        return upper
    if upper in _UN_CEFACT_PERIODS:
        return _UN_CEFACT_PERIODS[upper]
    if one := _ONE_UNIT.fullmatch(written):
        return one.group(1).upper()
    if duration := _ISO_DURATION.fullmatch(upper):
        return _ISO_DURATION_UNITS[duration.group(1) or duration.group(2)]
    found = _period_phrases(vocab.context_languages(ctx))
    if found is None or (phrase := found[0].fullmatch(written)) is None:
        return None
    return found[1][phrase.lastgroup or ""]


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
    languages = vocab.context_languages(ctx)
    text, periods = _strip_periods(raw, languages)
    if len(periods) > 1:
        return Invalid("period_mismatch")
    bounds = _split_bounds(text, _separator(languages))
    if bounds is None:
        return Invalid("not_a_range")
    texts = _bound_texts(*bounds)
    if texts is None:
        return Ambiguous("currency_missing", ())
    return _monetary(money(texts[0], ctx), money(texts[1], ctx), periods.pop() if periods else None)


Parts = tuple[str, str, str]


def _split_bounds(text: str, separator: re.Pattern[str]) -> tuple[Parts, Parts] | None:
    """The two bounds of `text`, each as (text before, amount, text after), or `None` unless it is one range."""
    # A separator splits two bounds only with an amount on each side; exactly one such separator makes a range.
    starts = [m.start() for m in _AMOUNT.finditer(text)]
    splits = [m for m in separator.finditer(text) if starts and starts[0] < m.start() and m.end() <= starts[-1]]
    if len(splits) != 1:
        return None
    left = _around_amount(text[: splits[0].start()].strip())
    right = _around_amount(text[splits[0].end() :].strip())
    if left is None or right is None:
        return None
    return left, right


def _bound_texts(left: Parts, right: Parts) -> tuple[str, str] | None:
    """The text of each bound with its currency, or `None` when neither bound writes one."""
    (left_before, left_amount, left_after), (right_before, right_amount, right_after) = left, right
    left_has, right_has = bool(left_before or left_after), bool(right_before or right_after)
    if not (left_has or right_has):
        return None
    # Structural: a range written with its currency once ("€10-20", "10-20 EUR") states it for both bounds, so the
    # bound without one takes the other bound's text around its amount.
    if not left_has:
        left_before, left_after = right_before, right_after
    elif not right_has:
        right_before, right_after = left_before, left_after
    return left_before + left_amount + left_after, right_before + right_amount + right_after


@lru_cache(maxsize=64)  # keyed by the page's languages, a small set
def _separator(languages: frozenset[str]) -> re.Pattern[str]:
    """The dashes and the `type:range_to` words of the page's languages (every language when it states none), each
    word whole and in any case, with the white space around them."""
    entries = vocab.entries_for(vocab.type_vocabulary(_SEPARATOR_VOCABULARY) or {}, languages)
    words = sorted({phrase for e in entries for phrase in e.phrases})
    return re.compile(rf"\s*(?:{'|'.join([_DASHES, *map(_whole_words, words)])})\s*", re.IGNORECASE)


def _whole_words(phrase: str) -> str:
    """A vocabulary phrase (token form) as a pattern: its words whole, with any white space between them."""
    return r"\b" + r"\s+".join(map(re.escape, phrase.split(" "))) + r"\b"


def _strip_periods(raw: str, languages: frozenset[str]) -> tuple[str, set[str]]:
    """`raw` with each `type:period` phrase replaced by a space, and the units those phrases name."""
    found = _period_phrases(languages)
    if found is None:
        return raw, set()
    pattern, codes = found
    periods = {codes[m.lastgroup or ""] for m in pattern.finditer(raw)}
    return pattern.sub(" ", raw), periods


@lru_cache(maxsize=64)  # keyed by the page's languages, a small set
def _period_phrases(languages: frozenset[str]) -> tuple[re.Pattern[str], dict[str, str]] | None:
    """A pattern that finds the `type:period` phrases of the page's languages (every language when it states none),
    with the unit each named group stands for; `None` when the vocabulary has no phrases for them.

    A phrase matches as whole words in any case, and so does its solidus form `/<last word>` (the SI Brochure and
    ISO 80000-1 write "per" between units as `/`). A unit with another word around it ("hourly", "per hours") is not
    a period.
    """
    entries = vocab.entries_for(vocab.type_vocabulary(_PERIOD_VOCABULARY) or {}, languages)
    phrases = {phrase: code for e in entries for phrase, code in e.phrases.items()}
    if not phrases:
        return None
    alternatives: list[str] = []
    codes: dict[str, str] = {}
    for i, (phrase, code) in enumerate(sorted(phrases.items())):
        last = phrase.rsplit(" ", 1)[-1]
        alternatives.append(rf"(?P<p{i}>{_whole_words(phrase)}|/\s*{re.escape(last)}\b)")
        codes[f"p{i}"] = code
    return re.compile("|".join(alternatives), re.IGNORECASE), codes


def _around_amount(bound: str) -> Parts | None:
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
        case Ok(value=lo_value), Ok(value=hi_value):
            (lo_amount, lo_currency), (hi_amount, hi_currency) = _amount(lo_value), _amount(hi_value)
            if lo_currency != hi_currency:
                return Invalid("currency_mismatch")
            if lo_amount > hi_amount:
                return Invalid("min_greater_than_max")
            if period is None:
                return Ambiguous("period_missing", ())
            return Ok(_value(lo_amount, hi_amount, currency=lo_currency, unit=None, period=period))
    raise TypeError("a normalize result is Ok, Ambiguous or Invalid")


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


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    """Equality as a key (SPEC-04 §4.5): every part equal, the bounds as Decimals without rounding (`50000` equals
    `50000.00`)."""
    parts = _range_value(value)
    return raw_key(value) if parts is None else ("range", *parts[:2], *(frozen(p) for p in parts[2:]))


def _range_value(value: JsonValue) -> tuple[Decimal, Decimal, JsonValue, JsonValue, JsonValue] | None:
    """A normalized range as (min, max, currency, unit, period), or `None` for any other value."""
    if not isinstance(value, dict) or value.keys() != _VALUE_KEYS:
        return None
    lo, hi = value["min"], value["max"]
    lo_number = _decimal(lo) if isinstance(lo, str) else None
    hi_number = _decimal(hi) if isinstance(hi, str) else None
    if lo_number is None or hi_number is None:
        return None
    return lo_number, hi_number, value["currency"], value["unit"], value["period"]
