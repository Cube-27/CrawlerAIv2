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
"""

import re
import unicodedata
from collections.abc import Callable, Hashable, Iterable, Mapping
from decimal import Decimal
from functools import cache

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from babel.numbers import NumberFormatError, get_decimal_symbol, get_group_symbol, list_currencies, parse_decimal
from price_parser import Price
from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

# schema.org `price`: ASCII digits with `.` (U+002E) as the decimal point and no grouping symbols.
_SCHEMA_ORG_PRICE = re.compile(r"\d+(?:\.\d+)?", re.ASCII)
# Structural: a written amount is a run of digits joined by single separators (CLDR decimal and group symbols: `.`,
# `,`, apostrophes, spaces). An amount below one may open with its decimal symbol (`.99`), unless a letter or digit
# precedes it; CLDR then decides whether that symbol is a decimal point. A text holding two runs states two amounts:
# a range or a list, never one money value.
_AMOUNT_RUN = re.compile(r"(?:(?<![^\W_])[.,])?\d+(?:[.,'\u2019\s]\d+)*")
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
    elif isinstance(amount, str) and _SCHEMA_ORG_PRICE.fullmatch(stripped := amount.strip()):
        value = Decimal(stripped)
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
    run = _amount_run(text)
    if isinstance(run, Invalid):
        return run
    before, after = text[: run.start()], text[run.end() :]
    if any(minus in before for minus in _MINUS):
        return Invalid("not_positive")
    signs = _signs(text, before, after)
    if isinstance(signs, Invalid):
        return signs
    locales = _locale_set(ctx)
    currencies = _agreed_currencies(signs, locales, ctx)
    if isinstance(currencies, Invalid):
        return currencies
    amounts = _amounts(run.group(), locales)
    if not amounts:
        return Invalid("unparsable_amount")
    if len(currencies) == 1 and len(amounts) == 1:
        return _money(amounts[0], currencies[0])
    options = [_value(a, c) for c in currencies for a in amounts]
    reason = "decimal_separator" if len(currencies) == 1 else "currency_symbol"
    return Ambiguous(reason, tuple(options))


def _amount_run(text: str) -> re.Match[str] | Invalid:
    """The one run of amount characters in `text`; none is no amount, and two are a range, not one value."""
    runs = list(_AMOUNT_RUN.finditer(text))
    if not runs:
        return Invalid("no_amount")
    if len(runs) > 1:
        return Invalid("range")
    return runs[0]


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


def _agreed_currencies(signs: list[str], locales: frozenset[str], ctx: Context) -> list[str] | Invalid:
    """The ISO 4217 codes every sign can denote, sorted."""
    # A sign on each side of the amount (`$5 USD`) must agree: the currencies both can denote. Two signs that share
    # none (`USD 12 EUR`) state two currencies, never one money value.
    each = [_currencies_for(sign, locales, ctx.page_currencies) for sign in signs]
    currencies = sorted(set(each[0]).intersection(*each[1:]))
    if not currencies:
        return Invalid("currency_conflict" if len(each) > 1 and all(each) else "unknown_currency")
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
    in_locales = frozenset(code for loc in locales for code in _locale_symbols(loc).get(sign, ()))
    return sorted(in_locales or anywhere)


def _amounts(written: str, locales: frozenset[str]) -> list[Decimal]:
    """Every value the written amount has under the decimal and group symbols of the locales (CLDR number symbols).
    With no locale evidence, every CLDR convention is possible."""
    # Locales with one convention read an amount the same way, so one of them is parsed.
    conventions: dict[tuple[str, str, object], str] = {}
    for loc in locales or _number_conventions():
        conventions.setdefault(_convention(loc), loc)
    readings: set[Decimal] = set()
    for (_, group, _), loc in conventions.items():
        # CLDR group symbols that are spaces (U+00A0, U+202F) are written as any Unicode space separator on pages.
        text = "".join(group if unicodedata.category(c) == "Zs" else c for c in written) if group.isspace() else written
        try:
            readings.add(parse_decimal(text, loc, strict=True))
        except NumberFormatError:
            continue
    return sorted(readings)


def _locale_set(ctx: Context) -> frozenset[str]:
    """The CLDR locales the page and the request state (SPEC-04 §4.4). A tag that names no territory stands for every
    territory its language is used in, unless the ccTLD names one; the ccTLD alone stands for its territory's
    locales."""
    tags = [t for t in (ctx.html_lang, ctx.og_locale, ctx.request_locale, *ctx.hreflang) if t]
    out: set[str] = set()
    known = False
    for tag in tags:
        locale = _parse_tag(tag)
        if locale is None:
            continue  # Not a BCP 47 tag CLDR knows (`x-default`): no evidence.
        known = True
        if locale.territory:
            out.add(str(locale))
            continue
        with_territory = f"{locale.language}_{ctx.cctld_territory}"
        if ctx.cctld_territory and with_territory in _identifiers():
            out.add(with_territory)
        else:
            out.update(_by_language().get(locale.language, ()))
    if not known and ctx.cctld_territory:
        out.update(_by_territory().get(ctx.cctld_territory, ()))
    return frozenset(out)


@cache
def _parse_tag(tag: str) -> Locale | None:
    try:
        return Locale.parse(tag.replace("_", "-"), sep="-")
    except (ValueError, TypeError, UnknownLocaleError):
        return None


@cache
def _identifiers() -> frozenset[str]:
    return frozenset(locale_identifiers())


@cache
def _by_language() -> dict[str, frozenset[str]]:
    """CLDR locale identifiers by their language subtag."""
    return _index(lambda i: i.partition("_")[0])


@cache
def _by_territory() -> dict[str, frozenset[str]]:
    """CLDR locale identifiers by their last subtag (the territory, for identifiers that have one)."""
    return _index(lambda i: i.rpartition("_")[2] if "_" in i else "")


def _index(key: Callable[[str], str]) -> dict[str, frozenset[str]]:
    groups: dict[str, set[str]] = {}
    for identifier in _identifiers():
        groups.setdefault(key(identifier), set()).add(identifier)
    return {key: frozenset(ids) for key, ids in groups.items()}


def is_currency_code(code: str) -> bool:
    """Whether `code` is an ISO 4217 alphabetic code as written: three uppercase letters that ISO 4217 lists (through
    CLDR). A lowercase `usd` is not one: guessing the case is guessing (C7)."""
    return code in _currencies()


@cache
def _currencies() -> frozenset[str]:
    return frozenset(list_currencies())


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
    for identifier in _identifiers():
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


@cache
def _convention(identifier: str) -> tuple[str, str, object]:
    """A locale's CLDR number convention: decimal symbol, group symbol, grouping sizes. Babel reads symbols and parses
    in the Latin digit system (`latn`) by default, the digits `_AMOUNT_RUN` reads after NFKC."""
    locale = Locale.parse(identifier)
    pattern = locale.decimal_formats.get(None)
    return (
        get_decimal_symbol(locale),
        get_group_symbol(locale),
        pattern.grouping if pattern is not None else None,
    )


@cache
def _number_conventions() -> frozenset[str]:
    """One locale per distinct CLDR number convention."""
    seen: dict[tuple[str, str, object], str] = {}
    for identifier in sorted(_identifiers()):
        seen.setdefault(_convention(identifier), identifier)
    return frozenset(seen.values())


def equal(a: JsonValue, b: JsonValue, _spec: FieldSpec) -> bool:
    """SPEC-04 §4.5: the amounts equal as Decimals, without rounding (`19.9` equals `19.90`), and the same currency."""
    if a == b:
        return True
    left, right = _money_value(a), _money_value(b)
    return left is not None and left == right


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    money = _money_value(value)
    return raw_key(value) if money is None else ("money", money)


def _money_value(value: JsonValue) -> tuple[Decimal, str] | None:
    """A normalized money value (`{amount, currency}`) as (amount, ISO 4217 code), or `None` for any other value."""
    if not isinstance(value, dict) or value.keys() != {"amount", "currency"}:
        return None
    amount, currency = value["amount"], value["currency"]
    if not (isinstance(amount, str) and _SCHEMA_ORG_PRICE.fullmatch(amount) and isinstance(currency, str)):
        return None
    return Decimal(amount), currency
