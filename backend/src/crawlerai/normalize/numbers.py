"""Numbers as pages write them (normalization spec): the locales a page and its request state, and the values a written
number has under their Unicode CLDR number symbols (Babel). Shared by the normalizers that read numbers from text
(money, count, number), so each reads them one way."""

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from babel.numbers import NumberFormatError, parse_decimal

from crawlerai.normalize.base import Context, has_surrogate

# Structural: a written amount is a run of digits (any Unicode decimal digits) joined by single separators (CLDR
# decimal and group symbols: `.`, `,`, apostrophes, spaces, and the `arab`/`arabext` U+066B decimal and U+066C group
# separators). An amount below one may open with its decimal symbol (`.99`), unless a letter or digit precedes it;
# CLDR then decides whether that symbol is a decimal point. A text holding two runs states two amounts: a range or a
# list, never one value.
AMOUNT_RUN = re.compile(r"(?:(?<![^\W_])[.,\u066b])?\d+(?:[.,'\u2019\u066b\u066c\s]\d+)*")
# UTS #35 numbering systems pages write with their own separators: Arabic-Indic (`arab`) and Extended Arabic-Indic
# (`arabext`) digits, with U+066B ARABIC DECIMAL SEPARATOR and U+066C ARABIC THOUSANDS SEPARATOR. A locale whose
# default or native numbering system is one of them reads both its `latn` and that system's symbols.
_ARABIC_SYSTEMS = frozenset({"arab", "arabext"})
# The ASCII and compatibility forms pages write for a CLDR group symbol: U+2019 RIGHT SINGLE QUOTATION MARK (`de-CH`)
# as the ASCII apostrophe and back; a space symbol (U+00A0, U+202F) as any Unicode space separator.
_GROUP_FALLBACKS = {"\u2019": frozenset("'"), "'": frozenset("\u2019")}
# A CLDR number convention: decimal symbol, group symbol, grouping sizes.
Convention = tuple[str, str, object]
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
    runs: list[tuple[int, int]] = []
    for run in AMOUNT_RUN.finditer(text):
        start, end = run.span()
        if not percentages and _percentage(text, start, end):
            # A ratio is not grouped by white space: in `12.99 20%` only the last piece is the ratio, the rest a
            # number of its own.
            spaced = [m.start() for m in re.finditer(r"\s", run.group())]
            if not spaced or not _percentage(text, start + spaced[-1] + 1, end):
                continue
            end = start + spaced[-1]
        runs.append((start, end))
    if not runs:
        return "no_number"
    if len(runs) > 1:
        return "several_numbers"
    start, end = runs[0]
    return Stated(text[start:end], text[:start], text[end:], text)


def percentage(before: str, value: str, after: str) -> bool:
    """Whether the one number of `value`, written between `before` and `after`, is a percentage: a CLDR percent sign
    is written next to it (`_percentage`), inside `value` or beside it. False when `value` holds no one number."""
    found = stated(value)
    if isinstance(found, str):
        return False
    left, middle = unicodedata.normalize("NFKC", before), unicodedata.normalize("NFKC", value)
    start = len(left) + len(middle) - len(middle.lstrip()) + len(found.before)
    end = start + len(found.written)
    return _percentage(left + middle + unicodedata.normalize("NFKC", after), start, end)


def _percentage(text: str, start: int, end: int) -> bool:
    """Whether a CLDR percent sign is written right after the number (white space between allowed, as `20 %` writes
    it) or right before it (`%20`), bidi marks (Unicode Cf, as some locales write around the sign) aside. A sign
    followed by a digit opens the next number (`12.99 %20`), so it is not this number's. Only the characters next to
    the number are read, so a text with many numbers is read in linear time."""
    signs = _percent_signs()
    width = max(map(len, signs))
    after = _unmarked(text, end, 1, width + 1, skip_space=True)
    before = _unmarked(text, start - 1, -1, width, skip_space=False)[::-1]
    return any(after.startswith(s) and not after[len(s) : len(s) + 1].isdigit() for s in signs) or before.endswith(
        signs
    )


def _unmarked(text: str, index: int, step: int, count: int, *, skip_space: bool) -> str:
    """Up to `count` characters of `text` from `index` on, walking by `step`, format characters (Unicode Cf) left out;
    with `skip_space`, white space before the first other character too."""
    kept: list[str] = []
    while 0 <= index < len(text) and len(kept) < count:
        char = text[index]
        index += step
        if unicodedata.category(char) == "Cf" or (skip_space and not kept and char.isspace()):
            continue
        kept.append(char)
    return "".join(kept)


def warm() -> None:
    """Build the tables read across every CLDR locale (number conventions, percent signs, compact units) now, so that
    the first page a process reads does not wait for them."""
    _number_conventions()
    _percent_signs()
    _every_compact_unit()


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


def compact(after: str) -> bool:
    """Whether a CLDR compact decimal unit (`compact_unit`) of any locale is written right after a number, whatever
    power it stands for: the number is a rounded magnitude (`1K+`). Every locale is asked, as pages write the compact
    forms of other languages than their own."""
    return any(after.startswith(u) and not _word_letter(after[len(u) : len(u) + 1]) for u in _every_compact_unit())


@cache
def _every_compact_unit() -> frozenset[str]:
    return frozenset(unit for identifier in identifiers() for unit, _ in _compact_units(identifier))


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


def readings(written: str, locales: frozenset[str], decimal: str | None = None) -> list[Decimal]:
    """Every value the written amount has (CLDR number symbols), the one a page's declared locales settle when it has
    several, then the one the page's decimal symbol (the context's `page_convention`) settles. A string only one CLDR
    convention can read (`1.234,56`, `12.50`) has one value whatever the page says; one that conventions read
    differently (`1.234`, `1,234`) takes the values its declared `locales` give it, then those of the conventions whose
    decimal symbol is `decimal`, and with no evidence keeps every value."""
    every = _values(written, _number_conventions())
    if len(every) < 2:
        return every
    declared = _values(written, locales) if locales else every
    if len(declared) < 2 or decimal is None:
        return declared
    return _values(written, locales or _number_conventions(), decimal) or declared


def _values(written: str, locales: Iterable[str], decimal: str | None = None) -> list[Decimal]:
    # Locales with one convention read an amount the same way, so one of them is parsed.
    conventions: dict[Convention, tuple[str, dict[int, str]]] = {}
    for loc in locales:
        for convention, as_latn in _conventions(loc):
            conventions.setdefault(convention, (loc, as_latn))
    # Unicode decimal digits (`١٢٣`, `۱۲۳`) read as the ASCII digits Babel parses in every numbering system.
    latin = "".join(str(d) if (d := unicodedata.decimal(c, None)) is not None else c for c in written)
    values: set[Decimal] = set()
    for (symbol, group, _), (loc, as_latn) in conventions.items():
        if decimal is not None and symbol != decimal:
            continue
        try:
            value = parse_decimal(_grouped(latin, group).translate(as_latn), loc, strict=True)
        except (NumberFormatError, InvalidOperation):
            # A digit run longer than the decimal context holds (Python `decimal`, 28 digits) is no amount either.
            continue
        # Babel also reads `.` as the decimal point of a locale whose group symbol is a space (`10.999` in `fr`): a
        # reading in the page's convention has its fraction after the page's decimal symbol.
        if decimal is None or decimal in written or int(value.as_tuple().exponent) >= 0:
            values.add(value)
    return sorted(values)


def _grouped(written: str, group: str) -> str:
    """`written` with the forms a page writes for the CLDR `group` symbol (`_GROUP_FALLBACKS`) as the symbol itself."""
    if group.isspace():
        return "".join(group if unicodedata.category(c) == "Zs" else c for c in written)
    fallbacks = _GROUP_FALLBACKS.get(group, frozenset())
    return "".join(group if c in fallbacks else c for c in written)


def locale_set(ctx: Context) -> frozenset[str]:
    """The CLDR locales whose number symbols the page declares and the request states (normalization spec): `<html
    lang>`, `og:locale`, JSON-LD `inLanguage`, Content-Language, the page's own `hreflang` and the request's locale. A
    tag with a territory is that locale; a tag with a language only is the language's own CLDR locale (`de` writes
    `1.234,5`), or its locale of the ccTLD's territory when the ccTLD names one; the ccTLD alone stands for its
    territory's locales."""
    return _declared(ctx, whole_language=False)


def regional_locales(ctx: Context) -> frozenset[str]:
    """The CLDR locales the page's declarations leave possible, for what a locale only narrows (a currency symbol shared
    by several currencies): as `locale_set`, but a tag with a language only stands for every territory its language is
    used in, so that the language alone settles nothing a territory would."""
    return _declared(ctx, whole_language=True)


def _declared(ctx: Context, *, whole_language: bool) -> frozenset[str]:
    declared = (
        ctx.html_lang,
        ctx.og_locale,
        ctx.request_locale,
        *ctx.in_language,
        *ctx.content_language,
        *ctx.hreflang,
    )
    out: set[str] = set()
    known = False
    for tag in filter(None, declared):
        locale = _parse_tag(tag)
        if locale is None:
            continue  # Not a BCP 47 tag CLDR knows (`x-default`): no evidence.
        known = True
        with_territory = f"{locale.language}_{ctx.cctld_territory}"
        if locale.territory:
            out.add(str(locale))
        elif ctx.cctld_territory and with_territory in identifiers():
            out.add(with_territory)
        elif not whole_language and str(locale) in identifiers():
            out.add(str(locale))
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
def _conventions(identifier: str) -> tuple[tuple[Convention, dict[int, str]], ...]:
    """A locale's CLDR number conventions (decimal symbol, group symbol, grouping sizes): its `latn` one, and that of
    the Arabic system (`_ARABIC_SYSTEMS`) that is its default or native one, each with the translation of its symbols
    into the `latn` ones, in which Babel parses."""
    locale = Locale.parse(identifier)
    pattern = locale.decimal_formats.get(None)
    grouping = pattern.grouping if pattern is not None else None
    native = {str(locale.default_numbering_system), str(locale.other_numbering_systems.get("native"))}
    latn = _symbols(locale, "latn")
    found: list[tuple[Convention, dict[int, str]]] = [((*latn, grouping), {})]
    for system in sorted(native & _ARABIC_SYSTEMS):
        decimal, group = _symbols(locale, system)
        found.append(((decimal, group, grouping), str.maketrans({decimal: latn[0], group: latn[1]})))
    return tuple(found)


def _symbols(locale: Locale, system: str) -> tuple[str, str]:
    """A locale's CLDR decimal and group symbols in a numbering system (Babel's defaults where CLDR has none)."""
    symbols = locale.number_symbols.get(system, {})
    return symbols.get("decimal", "."), symbols.get("group", ",")


@cache
def _number_conventions() -> frozenset[str]:
    """One locale per distinct CLDR number convention."""
    seen: dict[Convention, str] = {}
    for identifier in sorted(identifiers()):
        for convention, _ in _conventions(identifier):
            seen.setdefault(convention, identifier)
    return frozenset(seen.values())
