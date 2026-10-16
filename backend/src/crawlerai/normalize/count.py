"""Count normalizer (SPEC-04 §4.4, D-0782): a non-negative whole number of items, such as a stock quantity.

Accepts:
- a JSON number with no fraction;
- a schema.org `QuantitativeValue` (the range of `Offer.inventoryLevel`): its `value`, with no unit or the UN/CEFACT
  common code `C62` ("one", the unit of a count);
- a string, from the DOM or an LLM: the one number in it ("In stock (5 available)" is 5), read by the Unicode CLDR
  number symbols of the locales the page and the request state.

Nothing is defaulted (C7): a fraction, a negative number, a range, another unit, a text with no number or two numbers
is `Invalid`; a number the page's locales read as different values is `Ambiguous`.
"""

import math
import unicodedata
from collections.abc import Hashable, Mapping
from decimal import Decimal

from pydantic import JsonValue

from crawlerai.normalize import numbers
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# UN/CEFACT Recommendation 20 common code for "one" (a unit count), the unit schema.org `unitCode` names for a count.
_ONE = "C62"
# schema.org `QuantitativeValue`: `minValue` and `maxValue` state a range, not one count.
_RANGE_KEYS = ("minValue", "maxValue")


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a count field (SPEC-04 §4.4)."""
    if spec.type is not FieldType.COUNT:
        raise TypeError(f"the count normalizer does not handle type {spec.type}")
    if isinstance(raw, dict):
        return _quantitative_value(raw, ctx)
    return _scalar(raw, ctx)


def _scalar(raw: Raw, ctx: Context) -> NormalizeResult:
    if isinstance(raw, str):
        return _text(raw, ctx)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return Invalid("not_a_count")
    # JSON numbers are exact decimals in the text; `repr` is the shortest string that reads back as the same float.
    return _count(Decimal(repr(raw)))


def _quantitative_value(raw: Mapping[str, JsonValue], ctx: Context) -> NormalizeResult:
    unit_code, unit_text = raw.get("unitCode"), raw.get("unitText")
    if unit_code not in (None, _ONE) or (unit_code is None and unit_text is not None):
        return Invalid("unit")
    if "value" not in raw:
        return Invalid("range" if any(k in raw for k in _RANGE_KEYS) else "no_value")
    return _scalar(raw["value"], ctx)


def _text(raw: str, ctx: Context) -> NormalizeResult:
    if has_surrogate(raw):
        return Invalid("surrogate")
    # Unicode NFKC (UAX #15): fullwidth digits and no-break spaces read as their plain form, as CLDR symbols are.
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        return Invalid("empty")
    runs = list(numbers.AMOUNT_RUN.finditer(text))
    if not runs:
        return Invalid("no_number")
    if len(runs) > 1:
        return Invalid("several_numbers")
    run = runs[0]
    if text[: run.start()].rstrip().endswith(numbers.MINUS):
        return Invalid("negative")
    values = numbers.readings(run.group(), numbers.locale_set(ctx))
    if not values:
        return Invalid("not_a_count")
    if len(values) == 1:
        return _count(values[0])
    whole = tuple(int(v) for v in values if v == v.to_integral_value())
    return Ambiguous("decimal_separator", whole) if whole else Invalid("not_a_whole_number")


def _count(value: Decimal) -> NormalizeResult:
    if value < 0:
        return Invalid("negative")
    if value != value.to_integral_value():
        return Invalid("not_a_whole_number")
    return Ok(int(value))


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    """Equality as a key (SPEC-04 §4.5): exact. A normalized count is one JSON integer."""
    return raw_key(value)
