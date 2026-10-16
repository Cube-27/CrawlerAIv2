"""Number normalizer (SPEC-04 §4.4): a decimal number as the page states it, such as a rating value (schema.org
`Rating.ratingValue`, whose range is Number or Text).

Accepts:
- a JSON number;
- a string, from structured data, the DOM or an LLM: the one number in it ("Rated 4.5 stars" is 4.5), read by the
  Unicode CLDR number symbols of the locales the page and the request state (`normalize.numbers`, as money and count
  read numbers).

The value is the decimal in fixed-point notation as a JSON string, with its digits as written (`4.50` stays `4.50`),
as money writes an amount; equality compares decimals. Nothing is defaulted or rescaled (C7): a text with no number or
two numbers ("4.5 out of 5") is `Invalid`, and so is a minus sign set apart from the number, which may be a dash; a
number the page's locales read as different values is `Ambiguous`.
"""

from collections.abc import Hashable
from decimal import Decimal, InvalidOperation

from pydantic import JsonValue

from crawlerai.normalize import numbers
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a number field (SPEC-04 §4.4)."""
    if spec.type is not FieldType.NUMBER:
        raise TypeError(f"the number normalizer does not handle type {spec.type}")
    if isinstance(raw, str):
        return _text(raw, ctx)
    value = numbers.json_decimal(raw)
    if value is None or not value.is_finite():
        return Invalid("not_a_number")
    return Ok(_written(value))


def _text(raw: str, ctx: Context) -> NormalizeResult:
    found = numbers.stated(raw)
    if isinstance(found, str):
        return Invalid(found)
    # CLDR number patterns write the minus sign against the digits; one set apart from them may be a dash.
    sign = next((m for m in numbers.MINUS if found.before.endswith(m)), None)
    if numbers.negative(found.before.removesuffix(sign or "")):
        return Invalid("sign")
    values = [-v if sign else v for v in numbers.readings(found.written, numbers.locale_set(ctx))]
    if not values:
        return Invalid("not_a_number")  # a run no CLDR convention parses strictly ("1,2,3")
    if len(values) == 1:
        return Ok(_written(values[0]))
    return Ambiguous("decimal_separator", tuple(_written(v) for v in sorted(values)))


def _written(value: Decimal) -> str:
    return format(value, "f")


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    """Equality as a key (SPEC-04 §4.5): equal as decimals, so `4.5` equals `4.50`."""
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return raw_key(value)
    return raw_key(value)
