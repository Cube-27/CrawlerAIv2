"""Money normalizer (normalization spec): `{"amount": "<decimal>", "currency": "<ISO 4217>" | null}`.

Accepts:
- a string, from the DOM or an LLM: the one amount in it, and the currency sign written next to it (a CLDR symbol
  or ISO 4217 code) or, failing that, the sign `price-parser` locates. Unicode CLDR data (Babel) resolves both for
  the locales the page and the request state;
- a JSON object from a structured source: schema.org `price` + `priceCurrency` (Offer, PriceSpecification), or the
  normalized form `amount` + `currency`. The amount is a JSON number or a string of digits with `.` as the decimal
  point (schema.org `price`: no grouping, no currency sign); a `price` written as display text instead (`$1,295.99`)
  is read like text, in the stated currency, which any sign it writes must denote.

A grounded amount always gives a value; its currency comes from the best evidence (normalization spec, "money"): the
sign or code written with it, the item's structured data, a page-level declaration, the page's locale and region
narrowing a shared sign to one currency, else none (`null`, basis `unknown`). Nothing is invented: a currency is
only ever one the page or its locale names. Any other JSON value is `Invalid("not_money")`; an amount the locales
read differently is `Ambiguous`.
"""

import re
import unicodedata
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from urllib.parse import urlsplit

from babel import Locale
from babel.core import get_global
from babel.numbers import list_currencies
from price_parser import Price
from pydantic import JsonValue

from crawlerai.normalize import numbers
from crawlerai.normalize.base import Ambiguous, Basis, Context, Invalid, NormalizeResult, Ok, Raw, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org `price`: ASCII digits with `.` (U+002E) as the decimal point and no grouping symbols.
_SCHEMA_ORG_PRICE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
# persistence-storage spec D-0005: money is stored as `numeric(18,6)`, so an amount has at most 12 integer and 6
# fraction digits.
_MAX_AMOUNT = Decimal(10) ** 12
_MAX_EXPONENT = -6
# `numbers.stated` declines a text without one number as `no_number` or `several_numbers`; money names them by what
# they mean for an amount: none is no amount, and two are a range, not one value.
_NUMBER_REASONS = {"no_number": "no_amount", "several_numbers": "range"}


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a money field (normalization spec)."""
    if spec.type is not FieldType.MONEY:
        raise TypeError(f"the money normalizer does not handle type {spec.type}")
    if isinstance(raw, dict):
        return _structured(raw, ctx)
    if isinstance(raw, str):
        return _text(raw, ctx)
    return Invalid("not_money")


@dataclass(frozen=True, slots=True)
class _Currency:
    """A value's currency (`None`: unknown), the weaker evidence it rests on, and whether a sign or a structured
    currency is written with the amount (`Ok.checked`)."""

    code: str | None
    basis: Basis | None
    written: bool


def _structured(raw: Mapping[str, JsonValue], ctx: Context) -> NormalizeResult:
    amount_key, currency_key = ("price", "priceCurrency") if "price" in raw else ("amount", "currency")
    amount, currency = raw.get(amount_key), raw.get(currency_key)
    if amount is None:
        return Invalid("no_amount")
    # ISO 4217 as written; a code ISO 4217 does not list (`eur`, `$`) states no currency (C7: the case is not guessed).
    stated = currency if isinstance(currency, str) and currency in _currencies() else None
    if (number := numbers.json_decimal(amount)) is not None:
        value = number
    elif isinstance(amount, str) and _SCHEMA_ORG_PRICE.fullmatch(stripped := amount.strip()):
        value = Decimal(stripped)
    elif isinstance(amount, str) and amount_key == "price":
        # schema.org `priceCurrency` states the currency of a `price` the page wrote as display text (a sign,
        # grouping), so the text reader reads it with that currency stated (CLDR symbols and number symbols).
        return _text(amount, ctx, stated=stated)
    else:
        return Invalid("unparsable_amount")
    # The structured value names its amount a price, so it publishes; without a currency it takes the page's.
    found = _Currency(stated, None, True) if stated is not None else _unwritten(ctx, written=True)
    return _money(value, found)


def _text(raw: str, ctx: Context, stated: str | None = None) -> NormalizeResult:
    """Money written as text; `stated` is the currency structured data states beside it, which any sign the text
    writes must denote, and which a text without a sign is in."""
    found = numbers.stated(raw)
    if isinstance(found, str):
        return Invalid(_NUMBER_REASONS.get(found, found))
    text, before, after = found.text, found.before, found.after
    if numbers.negated(before):
        return Invalid("not_positive")
    currency = _currency_of(text, before, after, ctx, stated)
    if isinstance(currency, Invalid):
        return currency
    amounts = numbers.readings(found.written, numbers.locale_set(ctx))
    if not amounts:
        return Invalid("unparsable_amount")
    if len(amounts) == 1:
        return _money(amounts[0], currency)
    return Ambiguous("decimal_separator", tuple(_value(a, currency.code) for a in amounts))


def _currency_of(text: str, before: str, after: str, ctx: Context, stated: str | None) -> _Currency | Invalid:
    """The currency of a text amount: a `stated` one, which any sign must be able to denote; else the one the signs
    denote, narrowed by the evidence (`_narrowed`); else, with no sign, the page's (`_unwritten`). Two signs that share
    no currency (`USD 12 EUR`), or a sign that cannot denote the stated currency, contradict each other: `Invalid`."""
    signs = _signs(text, before, after)
    if isinstance(signs, Invalid):
        return _Currency(stated, None, True) if stated is not None else _unwritten(ctx, written=False)
    denoted = _agreed_currencies(signs)
    if isinstance(denoted, Invalid):
        return denoted
    if stated is not None:
        return _Currency(stated, None, True) if stated in denoted else Invalid("currency_conflict")
    if not denoted:
        # A sign `price-parser` locates that no CLDR symbol or ISO 4217 code is: written, but no currency.
        return _unwritten(ctx, written=True)
    return _narrowed(signs, denoted, ctx)


def _unwritten(ctx: Context, *, written: bool) -> _Currency:
    """The currency of an amount written without one: the one currency the page states and declares, when every
    statement agrees (normalization spec, "a page-level declaration ... consistent across the page"); else unknown."""
    declared = set(ctx.page_currencies) | set(ctx.declared_currencies)
    if len(declared) == 1:
        return _Currency(declared.pop(), "page", written)
    return _Currency(None, "unknown", written)


def _narrowed(signs: Sequence[str], denoted: frozenset[str], ctx: Context) -> _Currency:
    """Of the currencies a written sign can denote, the one the evidence settles, strongest first: the page's
    structured data (schema.org `priceCurrency`), its page-level declarations, then its locale and region (CLDR
    currency symbols of the locales its language tags and ccTLD name). Each step narrows what the one before left;
    none settling it leaves the currency unknown, never a default (C7)."""
    if len(denoted) == 1:
        return _Currency(next(iter(denoted)), None, True)
    steps: tuple[tuple[Callable[[], frozenset[str]], Basis | None], ...] = (
        (lambda: frozenset(ctx.page_currencies), None),
        (lambda: frozenset(ctx.declared_currencies), "page"),
        (lambda: _regional(signs, ctx), "locale"),
    )
    left = denoted
    for evidence, basis in steps:
        narrowed = left & evidence()
        if len(narrowed) == 1:
            return _Currency(next(iter(narrowed)), basis, True)
        left = narrowed or left
    return _Currency(None, "unknown", True)


def _regional(signs: Sequence[str], ctx: Context) -> frozenset[str]:
    """The currencies the signs stand for in the CLDR locales of the page's language and region: its language tags
    (`numbers.locale_set`), its Content-Language (RFC 9110 §8.5), and the territory its ccTLD names."""
    territory = ctx.cctld_territory or cctld_territory(ctx.page_url)
    tags = ctx.model_copy(update={"cctld_territory": territory, "hreflang": (*ctx.hreflang, *ctx.content_language)})
    locales = numbers.locale_set(tags)
    symbols = [unicodedata.normalize("NFKC", sign) for sign in signs]
    return frozenset(code for loc in locales for sign in symbols for code in _locale_symbols(loc).get(sign, ()))


def cctld_territory(url: str | None) -> str | None:
    """The territory a URL's country-code top-level domain names (RFC 1591 §2: a two-letter ISO 3166-1 code), when
    CLDR knows it as a territory; `None` for a generic TLD or no URL."""
    host = urlsplit(url).hostname if url else None
    label = (host or "").rstrip(".").rpartition(".")[2].upper()
    return label if len(label) == 2 and label in _territories() else None


def _signs(text: str, before: str, after: str) -> list[str] | Invalid:
    """The currency signs written next to the amount, or else the one `price-parser` locates in `text` when it is
    written on its own."""
    signs = _adjacent_signs(before.rstrip(), after.lstrip())
    if signs:
        return signs
    located = Price.fromstring(text).currency
    if located is None:
        return Invalid("no_currency")
    if not _whole_sign(text, located):
        return Invalid("unknown_currency")
    return [located]


def _agreed_currencies(signs: list[str]) -> frozenset[str] | Invalid:
    """The ISO 4217 codes every sign can denote (CLDR currency symbols anywhere); empty for a lone sign CLDR does not
    know."""
    # A sign on each side of the amount (`$5 USD`) must agree: the currencies both can denote. Two signs that share
    # none (`USD 12 EUR`) state two currencies, never one money value.
    each = [_currencies_for(sign) for sign in signs]
    currencies = each[0].intersection(*each[1:])
    if not currencies and len(each) > 1 and all(each):
        return Invalid("currency_conflict")
    return currencies


def _adjacent_signs(before: str, after: str) -> list[str]:
    """The longest CLDR currency symbol or ISO 4217 code written right before the amount, then the longest written
    right after it. A symbol can hold a shorter one (`$ AU`, `BS$`), which `price-parser` would locate instead."""
    tail = _longest_sign(before, lambda n: (len(before) - n, len(before)))
    head = _longest_sign(after, lambda n: (0, n))
    return [sign for sign in (tail, head) if sign is not None]


def _longest_sign(text: str, span: Callable[[int], tuple[int, int]]) -> str | None:
    for length, signs in _signs_by_length():
        start, end = span(length)
        if start >= 0 and (sign := text[start:end]) in signs and _bounded(text, start, end):
            return sign
    return None


def _whole_sign(text: str, sign: str) -> bool:
    """Whether `sign` is written on its own: not inside a longer run of letters, which would be a different sign
    (`S$` inside `BS$`)."""
    start = text.find(sign)
    while start >= 0:
        if _bounded(text, start, start + len(sign)):
            return True
        start = text.find(sign, start + 1)
    return False


def _bounded(text: str, start: int, end: int) -> bool:
    """Whether `text[start:end]` has no letter (Unicode category L) right before or right after it."""
    return not _is_letter(text[start - 1 : start]) and not _is_letter(text[end : end + 1])


def _is_letter(char: str) -> bool:
    return bool(char) and unicodedata.category(char).startswith("L")


def _money(amount: Decimal, currency: _Currency) -> NormalizeResult:
    # Trailing zeros are not precision: `12.5000000` fits six fraction digits.
    exponent = amount.normalize().as_tuple().exponent
    # A JSON number is finite (RFC 8259 §6); a NaN or infinity reaching here is no amount.
    if not isinstance(exponent, int):
        return Invalid("unparsable_amount")
    # A price that is not positive is not a price.
    if amount <= 0:
        return Invalid("not_positive")
    if amount >= _MAX_AMOUNT or exponent < _MAX_EXPONENT:
        return Invalid("out_of_range")
    return Ok(_value(amount, currency.code), basis=currency.basis, checked=currency.written)


def _value(amount: Decimal, currency: str | None) -> JsonValue:
    # Fixed-point notation, with the digits as written: `19.90` stays `19.90` (§4.5 compares amounts as Decimals).
    return {"amount": format(amount, "f"), "currency": currency}


def _currencies_for(sign: str) -> frozenset[str]:
    """The ISO 4217 codes `sign` can denote anywhere (normalization spec)."""
    if sign in _currencies():
        # ISO 4217 alphabetic codes are three uppercase letters; a code names itself.
        return frozenset({sign})
    # CLDR currency symbols: the currencies the sign stands for in any locale.
    return _symbol_currencies().get(unicodedata.normalize("NFKC", sign), frozenset())


def is_currency_code(code: str) -> bool:
    """Whether `code` is an ISO 4217 alphabetic code as written: three uppercase letters that ISO 4217 lists (through
    CLDR). A lowercase `usd` is not one: guessing the case is guessing (C7)."""
    return code in _currencies()


@cache
def _currencies() -> frozenset[str]:
    return frozenset(list_currencies())


@cache
def _territories() -> frozenset[str]:
    """The CLDR territories with currency data: the ISO 3166-1 regions a ccTLD can name."""
    return frozenset(get_global("territory_currencies"))


@cache
def _locale_symbols(identifier: str) -> dict[str, frozenset[str]]:
    """The currencies each CLDR symbol (NFKC) stands for in one locale."""
    by_symbol: dict[str, set[str]] = {}
    for code, symbol in Locale.parse(identifier).currency_symbols.items():
        by_symbol.setdefault(unicodedata.normalize("NFKC", symbol), set()).add(code)
    return {symbol: frozenset(codes) for symbol, codes in by_symbol.items()}


@cache
def _symbol_currencies() -> dict[str, frozenset[str]]:
    by_symbol: dict[str, set[str]] = {}
    for identifier in numbers.identifiers():
        for symbol, codes in _locale_symbols(identifier).items():
            by_symbol.setdefault(symbol, set()).update(codes)
    return {symbol: frozenset(codes) for symbol, codes in by_symbol.items()}


@cache
def _signs_by_length() -> tuple[tuple[int, frozenset[str]], ...]:
    """Every CLDR currency symbol and ISO 4217 code, grouped by length, longest first. A symbol of format characters
    only (Unicode Cf, such as a zero-width space) is not written on a page."""
    by_length: dict[int, set[str]] = {}
    for sign in [*_symbol_currencies(), *_currencies()]:
        if any(unicodedata.category(c) != "Cf" for c in sign):
            by_length.setdefault(len(sign), set()).add(sign)
    return tuple((length, frozenset(by_length[length])) for length in sorted(by_length, reverse=True))


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    """Equality as a key (normalization spec): the amounts equal as Decimals, without rounding (`19.9` equals `19.90`),
    and the same currency."""
    money = _money_value(value)
    return raw_key(value) if money is None else ("money", money)


def _money_value(value: JsonValue) -> tuple[Decimal, str | None] | None:
    """A normalized money value (`{amount, currency}`) as (amount, ISO 4217 code or `None` when unknown), or `None` for
    any other value."""
    if not isinstance(value, dict) or value.keys() != {"amount", "currency"}:
        return None
    amount, currency = value["amount"], value["currency"]
    if not (isinstance(amount, str) and _SCHEMA_ORG_PRICE.fullmatch(amount)):
        return None
    if not (currency is None or isinstance(currency, str)):
        return None
    return Decimal(amount), currency
