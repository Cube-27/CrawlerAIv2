"""Numbers as pages write them (normalization spec): the locales a page and its request state, and the values a written
number has under their Unicode CLDR number symbols (Babel). Shared by the normalizers that read numbers from text
(money, count, number), so each reads them one way."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from babel.numbers import NumberFormatError, get_decimal_symbol, get_group_symbol, parse_decimal

from crawlerai.normalize.base import Context, has_surrogate

# Structural: a written amount is a run of digits joined by single separators (CLDR decimal and group symbols: `.`,
# `,`, apostrophes, spaces). An amount below one may open with its decimal symbol (`.99`), unless a letter or digit
# precedes it; CLDR then decides whether that symbol is a decimal point. A text holding two runs states two amounts:
# a range or a list, never one value.
AMOUNT_RUN = re.compile(r"(?:(?<![^\W_])[.,])?\d+(?:[.,'\u2019\s]\d+)*")
# Unicode HYPHEN-MINUS and MINUS SIGN (the CLDR `minusSign` symbols, after NFKC) before the amount: a negative value.
MINUS = ("-", "\u2212")


def json_decimal(value: object) -> Decimal | None:
    """A JSON number as the exact decimal its text writes (`repr` is the shortest string that reads back as the same
    float), or `None` for any other value; a JSON boolean is no number."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return Decimal(repr(value))
    return None


@dataclass(frozen=True, slots=True)
class Stated:
    """The one number a text holds, as written (for `readings`), the text before it, where a sign would be, the text
    after it, and the whole text (NFKC, stripped) they are cut from."""

    written: str
    before: str
    after: str
    text: str


def stated(raw: str, *, percentages: bool = True) -> Stated | str:
    """The one number `raw` holds; else why it holds none (`surrogate`, `empty`, `no_number`, `several_numbers`).
    Without `percentages`, a number written with a CLDR percent sign next to it (`-20%`, `%20`) is not counted: a
    discount beside a price is a ratio, not a second amount."""
    if has_surrogate(raw):
        return "surrogate"
    # Unicode NFKC (UAX #15): fullwidth digits and no-break spaces read as their plain form, as CLDR symbols are.
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        return "empty"
    runs = [run for run in AMOUNT_RUN.finditer(text) if percentages or not _percentage(text, run.start(), run.end())]
    if not runs:
        return "no_number"
    if len(runs) > 1:
        return "several_numbers"
    run = runs[0]
    return Stated(run.group(), text[: run.start()], text[run.end() :], text)


def _percentage(text: str, start: int, end: int) -> bool:
    """Whether a CLDR percent sign is written right after the number (white space between allowed, as `20 %` writes
    it) or right before it (`%20`), bidi marks (Unicode Cf, as some locales write around the sign) aside."""
    after, before = _unmarked(text[end:]).lstrip(), _unmarked(text[:start])
    return after.startswith(_percent_signs()) or before.endswith(_percent_signs())


def _unmarked(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


@cache
def _percent_signs() -> tuple[str, ...]:
    """The CLDR percent signs (`percentSign`, Latin digits) of every locale, NFKC, without bidi marks (Unicode Cf)."""
    signs = {
        "".join(c for c in unicodedata.normalize("NFKC", sign) if unicodedata.category(c) != "Cf")
        for sign in (
            Locale.parse(identifier).number_symbols.get("latn", {}).get("percentSign", "")
            for identifier in identifiers()
        )
    }
    return tuple(sorted(sign for sign in signs if sign))


def compact_unit(after: str, locales: frozenset[str]) -> tuple[int, int] | None:
    """The CLDR compact decimal unit written right after a number (`万` in `3.5万`, `K` in `12K`: Unicode CLDR
    `decimalFormats-short`), as the power of ten it multiplies by and its length in `after`; `None` when the locales
    write none there, or when they read the unit as different powers. Only the page's locales are asked: a unit means
    nothing outside its locale."""
    found: dict[str, set[int]] = {}
    for identifier in locales:
        for unit, power in _compact_units(identifier):
            if after.startswith(unit) and not _word_letter(after[len(unit) : len(unit) + 1]):
                found.setdefault(unit, set()).add(power)
    if not found:
        return None
    unit = max(found, key=len)
    powers = found[unit]
    return (powers.pop(), len(unit)) if len(powers) == 1 else None


def _word_letter(char: str) -> bool:
    """Whether `char` is a letter of a script that spaces its words: a unit followed by one is the start of a word
    (`Kg`), while a wide East Asian character after it (Unicode UAX #11: `円`) starts the next sign."""
    letter = bool(char) and unicodedata.category(char).startswith("L")
    return letter and unicodedata.east_asian_width(char) not in ("W", "F")


@cache
def _compact_units(identifier: str) -> tuple[tuple[str, int], ...]:
    """A locale's compact decimal units (suffixes of its short decimal patterns, NFKC, CLDR quoting removed), each with
    the power of ten it stands for: the pattern for `10^n` written with `k` digits stands for `10^(n-k+1)`."""
    units: set[tuple[str, int]] = set()
    for patterns in (Locale.parse(identifier).compact_decimal_formats.get("short") or {}).values():
        for magnitude, pattern in patterns.items():
            unit = unicodedata.normalize("NFKC", pattern.suffix[0]).replace("'", "")
            if unit.strip() and not pattern.prefix[0].strip():
                units.add((unit, len(magnitude) - pattern.pattern.count("0")))
    return tuple(units)


def negative(before: str) -> bool:
    """Whether the text before a number holds a minus sign (`MINUS`) anywhere, so the number may be negative."""
    return any(minus in before for minus in MINUS)


def negated(before: str) -> bool:
    """Whether a minus sign (`MINUS`) in the text before a number touches it, so the number is negative.

    CLDR number patterns write the minus sign against the digits (`-5`, `-$5`); a minus set apart by a space is
    punctuation ("In stock - 5 left"), not a sign (D-1270)."""
    last = max(before.rfind(minus) for minus in MINUS)
    return last >= 0 and not any(c.isspace() for c in before[last + 1 :])


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
        except (NumberFormatError, InvalidOperation):
            # A digit run longer than the decimal context holds (Python `decimal`, 28 digits) is no amount either.
            continue
    return sorted(values)


def locale_set(ctx: Context) -> frozenset[str]:
    """The CLDR locales the page and the request state (normalization spec). A tag that names no territory stands for
    every territory its language is used in, unless the ccTLD names one; the ccTLD alone stands for its territory's
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
