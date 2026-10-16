"""Numbers as pages write them (SPEC-04 §4.4): the locales a page and its request state, and the values a written
number has under their Unicode CLDR number symbols (Babel). Shared by the normalizers that read numbers from text
(money, count), so each reads them one way."""

import re
import unicodedata
from collections.abc import Callable
from decimal import Decimal
from functools import cache

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from babel.numbers import NumberFormatError, get_decimal_symbol, get_group_symbol, parse_decimal

from crawlerai.normalize.base import Context

# Structural: a written amount is a run of digits joined by single separators (CLDR decimal and group symbols: `.`,
# `,`, apostrophes, spaces). An amount below one may open with its decimal symbol (`.99`), unless a letter or digit
# precedes it; CLDR then decides whether that symbol is a decimal point. A text holding two runs states two amounts:
# a range or a list, never one value.
AMOUNT_RUN = re.compile(r"(?:(?<![^\W_])[.,])?\d+(?:[.,'\u2019\s]\d+)*")
# Unicode HYPHEN-MINUS and MINUS SIGN (the CLDR `minusSign` symbols, after NFKC) before the amount: a negative value.
MINUS = ("-", "\u2212")


def readings(written: str, locales: frozenset[str]) -> list[Decimal]:
    """Every value the written amount has under the decimal and group symbols of the locales (CLDR number symbols).
    With no locale evidence, every CLDR convention is possible."""
    # Locales with one convention read an amount the same way, so one of them is parsed.
    conventions: dict[tuple[str, str, object], str] = {}
    for loc in locales or _number_conventions():
        conventions.setdefault(_convention(loc), loc)
    values: set[Decimal] = set()
    for (_, group, _), loc in conventions.items():
        # CLDR group symbols that are spaces (U+00A0, U+202F) are written as any Unicode space separator on pages.
        text = "".join(group if unicodedata.category(c) == "Zs" else c for c in written) if group.isspace() else written
        try:
            values.add(parse_decimal(text, loc, strict=True))
        except NumberFormatError:
            continue
    return sorted(values)


def locale_set(ctx: Context) -> frozenset[str]:
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
        if ctx.cctld_territory and with_territory in identifiers():
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
def identifiers() -> frozenset[str]:
    """Every CLDR locale identifier."""
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
    for identifier in identifiers():
        groups.setdefault(key(identifier), set()).add(identifier)
    return {key: frozenset(ids) for key, ids in groups.items()}


@cache
def _convention(identifier: str) -> tuple[str, str, object]:
    """A locale's CLDR number convention: decimal symbol, group symbol, grouping sizes. Babel reads symbols and parses
    in the Latin digit system (`latn`) by default, the digits `AMOUNT_RUN` reads after NFKC."""
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
    for identifier in sorted(identifiers()):
        seen.setdefault(_convention(identifier), identifier)
    return frozenset(seen.values())
