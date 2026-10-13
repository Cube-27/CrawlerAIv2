"""Money normalizer (SPEC-04 §4.4, ARCHITECTURE §9): `{"amount": "<decimal>", "currency": "<ISO 4217>"}`.

Accepts:
- a string, from the DOM or an LLM: the one amount in it, and the currency sign written next to it (a CLDR symbol
  or ISO 4217 code) or, failing that, the sign `price-parser` locates. Unicode CLDR data (Babel) resolves both for
  the locales the page and the request state;
- a JSON object from a structured source: schema.org `price` + `priceCurrency` (Offer, PriceSpecification), or the
  normalized form `amount` + `currency`. The amount is a JSON number or a string of digits with `.` as the decimal
  point (schema.org `price`: no grouping, no currency sign).

Any other JSON value is `Invalid("not_money")`. Nothing is defaulted (C7): a sign that names several currencies, or
an amount the locales read differently, is `Ambiguous`.

`equal` is a stub until SPEC-04 PR 9 implements §4.5.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from decimal import Decimal
from functools import cache

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from babel.numbers import NumberFormatError, get_decimal_symbol, get_group_symbol, list_currencies, parse_decimal
from price_parser import Price
from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org `price`: digits with `.` (U+002E) as the decimal point and no grouping symbols.
_SCHEMA_ORG_PRICE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# Structural: a written amount is a run of digits joined by single separators (CLDR decimal and group symbols: `.`,
# `,`, apostrophes, spaces). A text holding two runs states two amounts: a range or a list, never one money value.
_AMOUNT_RUN = re.compile(r"\d+(?:[.,'\u2019\s]\d+)*")
# Unicode HYPHEN-MINUS and MINUS SIGN (the CLDR `minusSign` symbols, after NFKC) before the amount: a negative value.
_MINUS = ("-", "\u2212")
# SPEC-01 D-0005: money is stored as `numeric(18,6)`, so an amount has at most 12 integer and 6 fraction digits.
_MAX_AMOUNT = Decimal(10) ** 12
_MAX_EXPONENT = -6


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a money field (SPEC-04 §4.4)."""
    if spec.type is not FieldType.MONEY:
        raise TypeError(f"the money normalizer does not handle type {spec.type}")
    if isinstance(raw, dict):
        return _structured(raw)
    if isinstance(raw, str):
        return _text(raw, ctx)
    return Invalid("not_money")


def _structured(raw: Mapping[str, JsonValue]) -> NormalizeResult:
    amount_key, currency_key = ("price", "priceCurrency") if "price" in raw else ("amount", "currency")
    amount, currency = raw.get(amount_key), raw.get(currency_key)
    if amount is None:
        return Invalid("no_amount")
    if currency is None:
        return Invalid("no_currency")
    if not isinstance(currency, str) or currency not in _currencies():
        return Invalid("unknown_currency")
    # JSON numbers are exact decimals in the text; `repr` is the shortest string that reads back as the same float.
    if isinstance(amount, (int, float)) and not isinstance(amount, bool):
        value = Decimal(repr(amount))
    elif isinstance(amount, str) and _SCHEMA_ORG_PRICE.fullmatch(amount.strip()):
        value = Decimal(amount.strip())
    else:
        return Invalid("unparsable_amount")
    return _money(value, currency)


def _text(raw: str, ctx: Context) -> NormalizeResult:
    if has_surrogate(raw):
        return Invalid("surrogate")
    # Unicode NFKC (UAX #15): compatibility forms (fullwidth digits and signs, no-break spaces) read as their plain
    # form, which is also how CLDR symbols are compared below.
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        return Invalid("empty")
    runs = list(_AMOUNT_RUN.finditer(text))
    if not runs:
        return Invalid("no_amount")
    if len(runs) > 1:
        return Invalid("range")
    run = runs[0]
    if any(minus in text[: run.start()] for minus in _MINUS):
        return Invalid("not_positive")
    sign = _adjacent_sign(text[: run.start()].rstrip(), text[run.end() :].lstrip())
    if sign is None:
        located = Price.fromstring(text).currency
        if located is None:
            return Invalid("no_currency")
        if not _whole_sign(text, located):
            return Invalid("unknown_currency")
        sign = located
    locales = _locale_set(ctx)
    currencies = _currencies_for(sign, locales, ctx.page_currencies)
    if not currencies:
        return Invalid("unknown_currency")
    amounts = _amounts(run.group(), locales)
    if not amounts:
        return Invalid("unparsable_amount")
    if len(currencies) == 1 and len(amounts) == 1:
        return _money(amounts[0], currencies[0])
    options = [_value(a, c) for c in currencies for a in amounts]
    reason = "decimal_separator" if len(currencies) == 1 else "currency_symbol"
    return Ambiguous(reason, tuple(options))


def _adjacent_sign(before: str, after: str) -> str | None:
    """The longest CLDR currency symbol or ISO 4217 code written right before or after the amount. A symbol can hold
    a shorter one (`$ AU`, `BS$`), which `price-parser` would locate instead."""
    for sign in _signs():
        if (before.endswith(sign) and not _is_letter(before[-len(sign) - 1 : -len(sign)])) or (
            after.startswith(sign) and not _is_letter(after[len(sign) : len(sign) + 1])
        ):
            return sign
    return None


def _whole_sign(text: str, sign: str) -> bool:
    """Whether `sign` is written on its own: not inside a longer run of letters (Unicode category L), which would be
    a different sign (`S$` inside `BS$`)."""
    start = text.find(sign)
    while start >= 0:
        end = start + len(sign)
        if not _is_letter(text[start - 1 : start]) and not _is_letter(text[end : end + 1]):
            return True
        start = text.find(sign, start + 1)
    return False


def _is_letter(char: str) -> bool:
    return unicodedata.category(char).startswith("L") if char else False


def _money(amount: Decimal, currency: str) -> NormalizeResult:
    # Trailing zeros are not precision: `12.5000000` fits six fraction digits.
    exponent = amount.normalize().as_tuple().exponent
    # A JSON number is finite (RFC 8259 §6); a NaN or infinity reaching here is no amount.
    if not isinstance(exponent, int):
        return Invalid("unparsable_amount")
    # ARCHITECTURE §9: a price that is not positive is not a price.
    if amount <= 0:
        return Invalid("not_positive")
    if amount >= _MAX_AMOUNT or exponent < _MAX_EXPONENT:
        return Invalid("out_of_range")
    return Ok(_value(amount, currency))


def _value(amount: Decimal, currency: str) -> JsonValue:
    # Fixed-point notation, with the digits as written: `19.90` stays `19.90` (§4.5 compares amounts as Decimals).
    return {"amount": format(amount, "f"), "currency": currency}


def _currencies_for(sign: str, locales: frozenset[str], page_currencies: Iterable[str]) -> list[str]:
    """The ISO 4217 codes `sign` can denote, given the evidence (SPEC-04 §4.4)."""
    if sign in _currencies():
        # ISO 4217 alphabetic codes are three uppercase letters; a code names itself.
        return [sign]
    sign = unicodedata.normalize("NFKC", sign)
    # CLDR currency symbols: the currencies the sign stands for anywhere, then in the page's own locales.
    anywhere = _symbol_currencies().get(sign, frozenset())
    # SPEC-04 §4.4: a currency the page's structured data states settles the sign, when the sign can denote it.
    stated = anywhere.intersection(page_currencies)
    if stated:
        return sorted(stated)
    in_locales = frozenset(code for loc in locales for code, s in _locale_symbols(loc) if s == sign)
    return sorted(in_locales or anywhere)


def _amounts(written: str, locales: frozenset[str]) -> list[Decimal]:
    """Every value the written amount has under the decimal and group symbols of the locales (CLDR number symbols).
    With no locale evidence, every CLDR convention is possible."""
    readings: set[Decimal] = set()
    for loc in sorted(locales or _number_conventions()):
        group = get_group_symbol(loc, numbering_system="latn")
        # CLDR group symbols that are spaces (U+00A0, U+202F) are written as any Unicode space separator on pages.
        text = "".join(group if unicodedata.category(c) == "Zs" else c for c in written) if group.isspace() else written
        try:
            readings.add(parse_decimal(text, loc, strict=True, numbering_system="latn"))
        except NumberFormatError:
            continue
    return sorted(readings)


def _locale_set(ctx: Context) -> frozenset[str]:
    """The CLDR locales the page and the request state (SPEC-04 §4.4). A tag that names no territory stands for every
    territory its language is used in, unless the ccTLD names one; the ccTLD alone stands for its territory's
    locales."""
    tags = [t for t in (ctx.html_lang, ctx.og_locale, ctx.request_locale, *ctx.hreflang) if t]
    out: set[str] = set()
    for tag in tags:
        try:
            locale = Locale.parse(tag.replace("_", "-"), sep="-")
        except (ValueError, TypeError, UnknownLocaleError):
            continue  # Not a BCP 47 tag CLDR knows (`x-default`): no evidence.
        if locale.territory:
            out.add(str(locale))
            continue
        with_territory = f"{locale.language}_{ctx.cctld_territory}"
        if ctx.cctld_territory and with_territory in _identifiers():
            out.add(with_territory)
        else:
            out.update(i for i in _identifiers() if _language(i) == locale.language)
    if not tags and ctx.cctld_territory:
        out.update(i for i in _identifiers() if i.endswith(f"_{ctx.cctld_territory}"))
    return frozenset(out)


def _language(identifier: str) -> str:
    return identifier.partition("_")[0]


@cache
def _identifiers() -> frozenset[str]:
    return frozenset(locale_identifiers())


@cache
def _currencies() -> frozenset[str]:
    return frozenset(list_currencies())


@cache
def _locale_symbols(identifier: str) -> tuple[tuple[str, str], ...]:
    symbols = Locale.parse(identifier).currency_symbols
    return tuple((code, unicodedata.normalize("NFKC", s)) for code, s in symbols.items())


@cache
def _symbol_currencies() -> dict[str, frozenset[str]]:
    by_symbol: dict[str, set[str]] = {}
    for identifier in _identifiers():
        for code, symbol in _locale_symbols(identifier):
            by_symbol.setdefault(symbol, set()).add(code)
    return {symbol: frozenset(codes) for symbol, codes in by_symbol.items()}


@cache
def _signs() -> tuple[str, ...]:
    """Every CLDR currency symbol and ISO 4217 code, longest first. A symbol of format characters only (Unicode Cf,
    such as a zero-width space) is not written on a page."""
    signs = {s for s in [*_symbol_currencies(), *_currencies()] if any(unicodedata.category(c) != "Cf" for c in s)}
    return tuple(sorted(signs, key=lambda s: (-len(s), s)))


@cache
def _number_conventions() -> frozenset[str]:
    """One locale per distinct CLDR number convention (decimal symbol, group symbol, grouping sizes)."""
    seen: dict[tuple[str, str, object], str] = {}
    for identifier in sorted(_identifiers()):
        locale = Locale.parse(identifier)
        pattern = locale.decimal_formats.get(None)
        key = (
            get_decimal_symbol(locale, numbering_system="latn"),
            get_group_symbol(locale, numbering_system="latn"),
            pattern.grouping if pattern is not None else None,
        )
        seen.setdefault(key, identifier)
    return frozenset(seen.values())


def equal(a: JsonValue, b: JsonValue) -> bool:
    """Stub until SPEC-04 PR 9 implements §4.5 (Decimal amount and currency).

    Exact equality of two normalized values, which labels and engine output both hold (SPEC-03 §4.3).
    """
    return a == b
