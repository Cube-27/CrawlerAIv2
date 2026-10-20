"""Per-unit and per-period amounts (normalization spec, "money"; extraction spec, "Structural DOM values"): an amount
written with a CLDR "per" pattern and a unit after it (`€25/kg`, `$0.50 per 100 ml`, `$25/mo`) is a price of one unit
or one period, not the price of the item.

The patterns and the unit names are Unicode CLDR unit data (Babel, the version `backend/data/manifest.json` pins), for
the CLDR root locale and the locales the page and the request state (`numbers.locale_set`), never a word list (C4):
- a unit's own per pattern (`unitPattern-count-per`: `{0}/kg`, `{0} pro Kilogramm`);
- the compound per pattern (`compoundUnitPattern` "per": `{0}/{1}`, `{0} per {1}`) with a unit's name after it, a
  count before the name allowed (`per 100 ml`): its unit patterns' text (`{0} kg`, `{0} kilograms`) and its display
  names; a word written as the leading letters of such a name is its abbreviation (`mo` of `mon`, `month`).

A form of two letters or more matches in any case (`KG`, `Month`); a form of one letter (`L`, `m`, German `M` for
Monat) is a symbol whose case is its meaning, so it matches only as CLDR writes it, and right after the separator
(`/L`), never apart from it: `$40 / M` and `$25 / S` write a size, not a unit. After a count (`/100 g`) it may stand
apart.

Mass, volume, length and area units and CLDR `item` are per-unit; duration units are per-period. Other categories
(speed, temperature) say nothing about a price.
"""

import bisect
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, Literal

from babel import Locale

from crawlerai.normalize import numbers
from crawlerai.normalize.base import Context

Per = Literal["per_unit", "per_period"]
PER_UNIT: Per = "per_unit"
PER_PERIOD: Per = "per_period"

# CLDR unit categories (the key's first part): per-unit for the quantities goods are sold by, per-period for time.
_KINDS: Mapping[str, Per] = {
    "mass": PER_UNIT,
    "volume": PER_UNIT,
    "length": PER_UNIT,
    "area": PER_UNIT,
    "duration": PER_PERIOD,
}
# CLDR `concentr-item`: a count of items ("{0} items"), the unit of a price per piece.
_COUNT_UNITS = frozenset({"concentr-item"})
_ROOT = "root"
_SLOT = "{0}"
_OTHER_SLOT = "{1}"
# A word written as a unit name's leading letters is its abbreviation from two letters on: one letter alone is too
# short to name one unit.
_MIN_ABBREVIATION = 2


@dataclass(frozen=True, slots=True)
class _Table:
    """One locale's CLDR unit data as this module reads it, NFKC and white space collapsed; each form keyed by `_key`
    (case-folded from two letters on, as written below)."""

    suffixes: Mapping[str, frozenset[Per]]  # per patterns without `{0}`: `/kg`, `per kilogram`
    # The compound per pattern's text between `{0}` and `{1}` (`/`, `per`), case-folded, each with whether the pattern
    # writes a space after it: one written apart (`{0} per {1}`) is a word, followed by a space, not by more letters.
    separators: frozenset[tuple[str, bool]]
    names: Mapping[str, frozenset[Per]]  # unit names and symbols: `kg`, `kilograms`, `mon`, `L`
    words: tuple[str, ...]  # the case-folded names that are one word of letters, sorted, for abbreviations
    longest: int  # the length of the longest name
    suffix_lengths: tuple[int, ...]  # the lengths of the per patterns, longest first


def per_suffix(text: str, ctx: Context) -> tuple[str, frozenset[Per]] | None:
    """The text up to the first amount followed by a per pattern and a unit, and what the unit is a price of; `None`
    when no amount is. White space and one sign token between the amount and the pattern are allowed (`25 €/kg`)."""
    written = unicodedata.normalize("NFKC", text)
    tables = [_table(identifier) for identifier in sorted({_ROOT, *numbers.locale_set(ctx)})]
    for run in numbers.AMOUNT_RUN.finditer(written):
        for start in _suffix_starts(written, run.end()):
            if kinds := _per(written[start:], tables):
                return written[:start], kinds
    return None


def is_unit(word: str, ctx: Context) -> bool:
    """Whether `word` is a unit's name or symbol (mass, volume, length, area, duration or item) in the CLDR root locale
    or a locale the page and the request state, in the case rules the module docstring gives."""
    written = _form(word)
    return any(_key(written) in _table(identifier).names for identifier in {_ROOT, *numbers.locale_set(ctx)})


def _suffix_starts(text: str, end: int) -> Iterator[int]:
    """Where a per pattern may start after an amount ending at `end`: right after it, white space aside, and after
    one token of a sign written there (`€`, `EUR`)."""
    first = len(text) - len(text[end:].lstrip())
    yield first
    token = re.match(r"[^\s\d/]+\s*", text[first:])
    if token is not None:
        yield first + token.end()


def _per(text: str, tables: Iterable["_Table"]) -> frozenset[Per]:
    written = " ".join(text.split())
    found: set[Per] = set()
    for table in tables:
        found |= _suffix(written, table) or _compound(written, table)
    return frozenset(found)


def _suffix(text: str, table: _Table) -> frozenset[Per]:
    """What the longest unit's own per pattern written at the start of `text` makes the amount a price of."""
    for length in table.suffix_lengths:
        if (kinds := table.suffixes.get(_key(text[:length]))) is not None and _ends(text, length):
            return kinds
    return frozenset()


def _compound(text: str, table: _Table) -> frozenset[Per]:
    """What the compound per pattern and a unit's name (a count before it allowed) at the start of `text` make the
    amount a price of."""
    for separator, apart in table.separators:
        after = text[len(separator) :]
        if text[: len(separator)].casefold() != separator or (apart and not after.startswith(" ")):
            continue
        rest = after.lstrip()
        if kinds := _named(rest, table, symbols=rest == after):
            return kinds
        # A count before the unit (`per 100 ml`), a number as `numbers` reads one.
        if (count := numbers.AMOUNT_RUN.match(rest)) and (
            kinds := _named(rest[count.end() :].lstrip(), table, symbols=True)
        ):
            return kinds
    return frozenset()


def _named(text: str, table: _Table, *, symbols: bool) -> frozenset[Per]:
    """The unit the start of `text` names: the longest unit name written there (a one-letter symbol only when
    `symbols`), else a word abbreviating names."""
    for length in range(min(len(text), table.longest), 0, -1):
        piece = text[:length]
        if not symbols and _letters(piece) < _MIN_ABBREVIATION:
            continue
        if (kinds := table.names.get(_key(piece))) is not None and _ends(text, length):
            return kinds
    word = re.match(r"[^\W\d_]+", text)
    if word is None or len(abbreviation := word.group().casefold()) < _MIN_ABBREVIATION:
        return frozenset()
    at = bisect.bisect_left(table.words, abbreviation)
    abbreviated = []
    while at < len(table.words) and table.words[at].startswith(abbreviation):
        abbreviated.append(table.names[table.words[at]])
        at += 1
    return frozenset().union(*abbreviated)


def _ends(text: str, end: int) -> bool:
    """Whether a match ending at `end` is a whole word: no letter of a script that spaces its words follows it."""
    return not _spaced_letter(text[end : end + 1])


def _spaced_letter(char: str) -> bool:
    """Whether `char` is a letter of a script that spaces its words (not wide, Unicode UAX #11: `毎` is not)."""
    letter = bool(char) and unicodedata.category(char).startswith("L")
    return letter and unicodedata.east_asian_width(char) not in ("W", "F")


def _form(pattern: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", pattern).split())


def _letters(text: str) -> int:
    return sum(char.isalpha() for char in text)


def _key(form: str) -> str:
    """A form as the table keys it: case-folded when it has two letters or more, else as written (a symbol)."""
    return form.casefold() if _letters(form) >= _MIN_ABBREVIATION else form


@cache
def _table(identifier: str) -> _Table:
    data = Locale.parse(identifier)._data  # Babel exposes CLDR unit patterns only through its locale data
    separators = {
        (form.casefold(), between[-1:].isspace())
        for width in data["compound_unit_patterns"].get("per", {}).values()
        if (between := _between(width.get("compound", ""))) is not None and (form := _form(between))
    }
    suffixes: dict[str, set[Per]] = {}
    names: dict[str, set[Per]] = {}
    for unit, kind in _units(data["unit_patterns"]):
        for written, is_suffix in _unit_forms(data, unit):
            (suffixes if is_suffix else names).setdefault(_key(_form(written)), set()).add(kind)
    names.pop("", None)
    suffixes.pop("", None)
    frozen = {name: frozenset(kinds) for name, kinds in names.items()}
    words = tuple(sorted(name for name in frozen if name.isalpha()))
    longest = max(map(len, frozen), default=0)
    lengths = tuple(sorted({len(suffix) for suffix in suffixes}, reverse=True))
    return _Table(
        {s: frozenset(k) for s, k in suffixes.items()}, frozenset(separators), frozen, words, longest, lengths
    )


# Babel's locale data is untyped (`LocaleDataDict`); `_unit_forms` reads only the CLDR unit keys `_table` names.
def _unit_forms(data: Mapping[str, Any], unit: str) -> Iterator[tuple[str, bool]]:
    """A unit's forms, each with whether it is a per pattern's suffix (`/kg`, from `{0}/kg`) or a name: the text of its
    count patterns (`{0} kg` gives `kg`) and its display names."""
    for width in data["unit_patterns"][unit].values():
        for count, pattern in width.items():
            if count == "per" and pattern.startswith(_SLOT):
                yield pattern.removeprefix(_SLOT), True
            elif count != "per" and _SLOT in pattern:
                yield pattern.replace(_SLOT, ""), False
    for name in data["unit_display_names"].get(unit, {}).values():
        yield name, False


def _between(compound: str) -> str | None:
    """The text a compound per pattern writes between the amount and the unit (`{0}/{1}` gives `/`); `None` for a
    pattern that writes the unit first (`每{1}{0}`)."""
    head, slot, rest = compound.partition(_SLOT)
    between, other, _ = rest.partition(_OTHER_SLOT)
    return between if slot and other and not head.strip() else None


def _units(patterns: Iterable[str]) -> Iterator[tuple[str, Per]]:
    for unit in patterns:
        kind = PER_UNIT if unit in _COUNT_UNITS else _KINDS.get(unit.split("-", 1)[0])
        if kind is not None:
            yield unit, kind
