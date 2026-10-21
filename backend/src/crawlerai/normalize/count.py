"""Count normalizer (normalization spec, D-0782): a non-negative whole number of items, such as a stock quantity.

Accepts:
- a JSON number with no fraction;
- a schema.org `QuantitativeValue` (the range of `Offer.inventoryLevel`): its `value`, with no unit or the UN/CEFACT
  common code `C62` ("one", the unit of a count);
- a string, from the DOM or an LLM: the one number in it ("In stock (5 available)" is 5), read by the Unicode CLDR
  number symbols of the locales the page and the request state.

Nothing is defaulted (C7): a fraction, a negative number, a range, another unit, a number written in a CLDR compact
form (`1K+`, `2,5 Mio.`: a rounded magnitude, not a count), a text with no number or two numbers is `Invalid`; a number
the page's locales read as different values is `Ambiguous`.
"""

import unicodedata
from collections.abc import Hashable, Iterator, Mapping
from decimal import Decimal
from functools import cache

from babel import Locale
from babel.localedata import locale_identifiers
from pydantic import JsonValue

from crawlerai.normalize import numbers, vocab
from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# UN/CEFACT Recommendation 20 common code for "one" (a unit count), the unit schema.org `unitCode` names for a count.
_ONE = "C62"
# schema.org `QuantitativeValue`: `minValue` and `maxValue` state a range, not one count.
_RANGE_KEYS = ("minValue", "maxValue")
# CLDR unit id of "item": the one measurement unit of the CLDR unit data that is a count, so it does not contradict C62.
_CLDR_COUNT_UNIT = "concentr-item"


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a count field (normalization spec)."""
    if spec.type is not FieldType.COUNT:
        raise TypeError(f"the count normalizer does not handle type {spec.type}")
    if isinstance(raw, dict):
        return _quantitative_value(raw, ctx)
    return _scalar(raw, ctx)


def _scalar(raw: Raw, ctx: Context) -> NormalizeResult:
    if isinstance(raw, str):
        return _text(raw, ctx)
    value = numbers.json_decimal(raw)
    if value is None or not value.is_finite():
        return Invalid("not_a_count")
    return _count(value)


def _quantitative_value(raw: Mapping[str, JsonValue], ctx: Context) -> NormalizeResult:
    unit_code, unit_text = raw.get("unitCode"), raw.get("unitText")
    if unit_code not in (None, _ONE) or (unit_code is None and unit_text is not None):
        return Invalid("unit")
    if unit_code == _ONE and isinstance(unit_text, str) and _names_a_measure(unit_text, ctx):
        return Invalid("unit")
    if "value" not in raw:
        return Invalid("range" if any(k in raw for k in _RANGE_KEYS) else "no_value")
    return _scalar(raw["value"], ctx)


def _names_a_measure(unit_text: str, ctx: Context) -> bool:
    """Whether `unitText` is the name or symbol of a CLDR measurement unit other than a count (D-1271): "one" and
    "kg" cannot both be right. Text that names no CLDR unit ("items", "pieces") does not contradict "one"."""
    label = unicodedata.normalize("NFKC", unit_text).strip().casefold()
    languages = vocab.context_languages(ctx) & _cldr_languages()
    return label in _measure_labels(languages)


def warm() -> None:
    """Build the unit labels of every CLDR locale, which a page that states no language is read with, now, so that the
    first such page a process reads does not wait for them."""
    _measure_labels(frozenset())


@cache
def _cldr_languages() -> frozenset[str]:
    """The primary language subtags (RFC 5646 §2.2.1) CLDR has locale data for. A page-stated subtag outside it selects
    no unit labels, so it is dropped before the cached lookup: the cache keys only on languages CLDR knows, and a page
    whose subtags CLDR does not know reads like a page that states no language."""
    return frozenset(i.split("_")[0] for i in locale_identifiers())


@cache
def _measure_labels(languages: frozenset[str]) -> frozenset[str]:
    """Every CLDR unit pattern's text beside its `{0}` placeholder (names and symbols, singular and plural, all
    widths) of the languages' locales, or of every locale when the page states no language."""
    idents = (i for i in locale_identifiers() if not languages or i.split("_")[0] in languages)
    labels = {label for ident in idents for label in _locale_labels(ident)}
    labels.discard("")
    return frozenset(labels)


def _locale_labels(ident: str) -> Iterator[str]:
    for unit, widths in Locale.parse(ident)._data["unit_patterns"].items():
        if unit != _CLDR_COUNT_UNIT:
            for forms in widths.values():
                for pattern in forms.values():
                    if isinstance(pattern, str):
                        yield unicodedata.normalize("NFKC", pattern.replace("{0}", "")).strip().casefold()


def _text(raw: str, ctx: Context) -> NormalizeResult:
    found = numbers.stated(raw)
    if isinstance(found, str):
        return Invalid(found)
    if numbers.negated(found.before):
        return Invalid("negative")
    if numbers.compact(found.after):
        return Invalid("compact")  # `1K+ reviews` states a rounded magnitude, not the count (CLDR compact decimals)
    values = numbers.readings(found.written, numbers.locale_set(ctx), ctx.page_convention)
    if not values:
        return Invalid("not_a_count")  # a run no CLDR convention parses strictly ("1,2,3")
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
    """Equality as a key (normalization spec): exact. A normalized count is one JSON integer."""
    return raw_key(value)
