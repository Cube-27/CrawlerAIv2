"""Date and datetime normalizer (SPEC-04 §4.4, ARCHITECTURE §9): an ISO 8601 date (`YYYY-MM-DD`) or an RFC 3339
datetime in UTC (`YYYY-MM-DDTHH:MM:SS[.ffffff]Z`).

Accepts a string, from the DOM, an LLM or a structured source (JSON-LD `datePosted` and similar values are strings).
Any other JSON value is `Invalid("not_a_string")`. Three paths, tried in order:

1. RFC 3339, with the other ISO 8601 offset forms (`±hhmm`, `±hh`), parses directly.
2. A numeric date (`03/04/2026`) is read in each day/month/year order the page's locales allow (CLDR short date
   patterns); different readings decline as `Ambiguous`.
3. Anything else goes to `dateparser` in the page's languages, once per allowed order, with `ctx.captured_at` as the
   base of relative dates ("2 days ago").

The locales are `ctx.html_lang` and `ctx.og_locale` (SPEC-04 §4.4); with neither, every order is allowed. A datetime
needs a time and a numeric UTC offset; a date takes the calendar date the input states, in its own offset.
"""

import re
from collections.abc import Hashable
from datetime import UTC, date, datetime, timedelta
from functools import cache, lru_cache
from typing import Literal

from babel import Locale, UnknownLocaleError
from babel.localedata import locale_identifiers
from dateparser.data.languages_info import language_order
from dateparser.date import DateDataParser
from pydantic import JsonValue

from crawlerai.normalize.base import Ambiguous, Context, Invalid, NormalizeResult, Ok, Raw, has_surrogate, raw_key
from crawlerai.schemas.types import FieldSpec, FieldType

Order = Literal["DMY", "MDY", "YMD"]
# The day/month/year orders of CLDR short date patterns, which are also the orders `dateparser` takes (`DATE_ORDER`).
_ORDERS: tuple[Order, ...] = ("DMY", "MDY", "YMD")

# SPEC-04 §4.4: years outside this range are not values of the type.
_MIN_YEAR, _MAX_YEAR = 1970, 2100

# RFC 3339 §5.6 `full-date` and `date-time`, with the ISO 8601 space separator and lowercase `t`/`z` that RFC 3339
# §5.6 notes permit, and the other ISO 8601 offset forms (§4.2.5.1: `±hh:mm`, `±hhmm`, `±hh`) and decimal comma
# (§4.2.2.4). Fractions longer than microseconds are cut to six digits (Python's resolution).
_RFC_3339 = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[Tt ](?P<time>\d{2}:\d{2}(?::\d{2})?)(?:[.,](?P<fraction>\d+))?(?P<offset>[Zz]|[+-]\d{2}(?::?\d{2})?)?)?",
    re.ASCII,
)
# An ISO 8601 calendar date in extended format (`YYYY-MM-DD`, §4.1.2.2) fixes the order of its fields: text that
# starts with one is read year first whatever the page's locales say, and must state that date.
_ISO_DATE_PREFIX = re.compile(r"\d{4}-\d{2}-\d{2}(?!\d)", re.ASCII)
_YEAR_FIRST: tuple[Order, ...] = ("YMD",)
# Three numeric fields with one separator (CLDR short date patterns use `/`, `.` or `-`).
_NUMERIC = re.compile(r"(\d{1,4})([./-])(\d{1,2})\2(\d{1,4})", re.ASCII)
# A time followed by a numeric UTC offset (ISO 8601 time with offset; RFC 5322 §3.3 `zone`). Zone abbreviations do not
# count: one abbreviation names several offsets in the IANA time zone database.
_NUMERIC_OFFSET = re.compile(r"\d:\d{2}(?::\d{2})?(?:[.,]\d+)?\s*[+-]\d{2}:?\d{2}(?!\d)")
# Unicode decimal digits (`\d` without re.ASCII): a year written in full is one run of digits.
_DIGITS = re.compile(r"\d+")
# Quoted text in a CLDR date pattern is literal (UTS #35 Part 4 §8), not pattern letters.
_QUOTED = re.compile(r"'[^']*'")
# `dateparser` periods that name a day; a coarser period ("1 month ago", "March 2026") does not name a date.
_DAY_PERIODS = frozenset({"day", "time"})
# `dateparser` keeps every settings object it is given for the life of the process, so relative dates are read
# against two fixed bases and then moved onto `ctx.captured_at`: a per-call base would grow that registry per page.
_ANCHOR = datetime(2000, 1, 3)
_ONE_DAY = timedelta(days=1)
# The languages `dateparser` has data for (from CLDR); it rejects any other at parse time.
_DATEPARSER_LANGUAGES = frozenset(language_order)


def normalize(raw: Raw, spec: FieldSpec, ctx: Context) -> NormalizeResult:
    """Normalize a date or datetime field (SPEC-04 §4.4)."""
    if spec.type not in (FieldType.DATE, FieldType.DATETIME):
        raise TypeError(f"the date normalizer does not handle type {spec.type}")
    if not isinstance(raw, str):
        return Invalid("not_a_string")
    if has_surrogate(raw):
        return Invalid("surrogate")
    text = raw.strip()
    if not text:
        return Invalid("empty")
    want_time = spec.type is FieldType.DATETIME
    if match := _RFC_3339.fullmatch(text):
        return _from_rfc_3339(match, want_time)
    if prefix := _ISO_DATE_PREFIX.match(text):
        try:
            stated = date.fromisoformat(prefix.group())
        except ValueError:
            return Invalid("not_a_date")
        return _from_text(text, want_time, _YEAR_FIRST, _languages(ctx), ctx.captured_at, stated)
    orders = _orders(ctx)
    if match := _NUMERIC.fullmatch(text):
        return Invalid("no_time") if want_time else _from_numeric(match, orders)
    return _from_text(text, want_time, orders, _languages(ctx), ctx.captured_at)


def _from_rfc_3339(match: re.Match[str], want_time: bool) -> NormalizeResult:
    time, fraction, offset = match.group("time"), match.group("fraction"), match.group("offset")
    if want_time and time is None:
        return Invalid("no_time")
    if want_time and offset is None:
        return Invalid("no_offset")
    iso = match.group("date")
    if time is not None:
        iso += f"T{time}" + (f".{fraction[:6].ljust(6, '0')}" if fraction else "") + (offset or "").upper()
    try:
        value = datetime.fromisoformat(iso)
    except ValueError:
        return Invalid("not_a_date")
    return _decide({value}, want_time)


def _from_numeric(match: re.Match[str], orders: tuple[Order, ...]) -> NormalizeResult:
    first, _, second, third = match.groups()
    readings: set[date] = set()
    for order in orders:
        fields = dict(zip(order, (first, second, third), strict=True))
        for year in _years(fields["Y"]):
            try:
                readings.add(date(year, int(fields["M"]), int(fields["D"])))
            except ValueError:
                continue
    return _decide(readings, want_time=False)


def _years(field: str) -> list[int]:
    """The years a numeric year field names: a four-digit year itself; a one- or two-digit year names the same digits
    in every century (it does not state its century), and the 1970 to 2100 range settles which."""
    if len(field) == 4:
        return [int(field)]
    if len(field) <= 2:
        return _two_digit_years(int(field))
    return []


def _two_digit_years(two_digits: int) -> list[int]:
    return [century + two_digits for century in (1900, 2000, 2100)]


def _from_text(
    text: str,
    want_time: bool,
    orders: tuple[Order, ...],
    languages: tuple[str, ...],
    base: datetime,
    stated: date | None = None,
) -> NormalizeResult:
    """`stated` is the date an ISO 8601 prefix of `text` fixes; a reading of another date is a misreading."""
    if not languages:
        # Month and day names are words of a language; reading them without the page's language is a guess (C7).
        return Invalid("no_language")
    written = {int(run) for run in _DIGITS.findall(text)}
    readings: set[datetime] = set()
    for order in orders:
        reading = _day_reading(text, languages, order, base, stated)
        if reading is None:
            continue
        value, period, relative = reading
        if want_time and (problem := _datetime_problem(text, value, period, relative)) is not None:
            return problem
        if relative or value.year in written:
            readings.add(value)
        else:
            # The year is not written in full, so it was a two-digit year that `dateparser` put in a century.
            readings.update(_with_years(value))
    return _decide(readings, want_time)


def _day_reading(
    text: str, languages: tuple[str, ...], order: Order, base: datetime, stated: date | None
) -> tuple[datetime, str | None, bool] | None:
    """`text` read in `order` as a day, moved onto `base` when relative, and whether it is relative; None when this
    order gives no reading of a day (or of the `stated` day)."""
    reading = _parse(text, languages, order, _ANCHOR)
    if reading is None:
        return None
    value, period = reading
    if period not in _DAY_PERIODS or (stated is not None and value.date() != stated):
        return None
    # A relative date moves with its base and an absolute one does not: a structural test, not a phrase list.
    moved = _parse(text, languages, order, _ANCHOR + _ONE_DAY)
    relative = moved != reading
    if relative:
        if moved != (value + _ONE_DAY, period):
            return None  # not a fixed offset from its base, so moving it onto the capture time would misread it
        value += base.replace(tzinfo=None) - _ANCHOR
    return value, period, relative


def _datetime_problem(text: str, value: datetime, period: str | None, relative: bool) -> Invalid | None:
    """Why a day reading is not a datetime: it needs a time and a numeric UTC offset; None when it is one."""
    if relative:
        # "2 days ago" carries no time of day, and `dateparser` reports "2 hours ago" with the same period.
        return Invalid("relative_datetime")
    if period != "time":
        return Invalid("no_time")
    if value.tzinfo is None or _NUMERIC_OFFSET.search(text) is None:
        return Invalid("no_offset")
    return None


def _with_years(value: datetime) -> set[datetime]:
    """`value` in each year its two-digit year names; 29 February drops out of common years."""
    readings = set()
    for year in _two_digit_years(value.year % 100):
        try:
            readings.add(value.replace(year=year))
        except ValueError:
            continue
    return readings


def _parse(text: str, languages: tuple[str, ...], order: Order, base: datetime) -> tuple[datetime, str | None] | None:
    try:
        data = _parser(languages, order, base).get_date_data(text)
    except (ValueError, OverflowError):
        return None
    if data.date_obj is None:
        return None
    return data.date_obj, data.period


@lru_cache(maxsize=256)
def _parser(languages: tuple[str, ...], order: Order, base: datetime) -> DateDataParser:
    settings = {
        # A date missing its day, month or year is not a date; filling it from the clock would be a default (C7).
        "STRICT_PARSING": True,
        "DATE_ORDER": order,
        "RELATIVE_BASE": base,
        "RETURN_TIME_AS_PERIOD": True,
    }
    return DateDataParser(languages=list(languages), settings=settings)


def _decide(readings: set[date] | set[datetime], want_time: bool) -> NormalizeResult:
    """One value from the readings of the input, or a decline: several readings are `Ambiguous` (C7)."""
    if not readings:
        return Invalid("not_a_date")
    in_range = [v for v in readings if _in_range(v, want_time)]
    if not in_range:
        return Invalid("year_out_of_range")
    rendered = sorted({_render(v, want_time) for v in in_range})
    if len(rendered) == 1:
        return Ok(rendered[0])
    same_day = len({(_stated(v).month, _stated(v).day) for v in in_range}) == 1
    return Ambiguous("two_digit_year" if same_day else "date_order", tuple(rendered))


def _in_range(value: date | datetime, want_time: bool) -> bool:
    # SPEC-04 §4.4's year range holds for the value as stored: the stated date, and for a datetime its UTC date as
    # well (`2100-12-31T23:00-05:00` is 2101 in UTC). The stated year is checked first, so the UTC conversion never
    # leaves the years `datetime` can hold.
    if not _MIN_YEAR <= _stated(value).year <= _MAX_YEAR:
        return False
    return not (want_time and isinstance(value, datetime)) or _MIN_YEAR <= value.astimezone(UTC).year <= _MAX_YEAR


def _stated(value: date | datetime) -> date:
    """The calendar date the input states, in its own offset."""
    return value.date() if isinstance(value, datetime) else value


def _render(value: date | datetime, want_time: bool) -> str:
    if not want_time:
        return _stated(value).isoformat()
    if not isinstance(value, datetime):
        raise TypeError("a datetime value needs a time")
    return value.astimezone(UTC).replace(tzinfo=None).isoformat() + "Z"


def _orders(ctx: Context) -> tuple[Order, ...]:
    """The date orders of the page's locales (SPEC-04 §4.4); every order when no locale is known."""
    found = {order for tag in (ctx.html_lang, ctx.og_locale) if tag for order in _tag_orders(tag)}
    return tuple(o for o in _ORDERS if o in found) or _ORDERS


@lru_cache(maxsize=1024)  # tags come from pages, so the cache is bounded
def _tag_orders(tag: str) -> frozenset[Order]:
    """The orders of a BCP 47 tag (or an `ll_TT` Open Graph locale): its CLDR locale's short date pattern when the tag
    names a territory; else the patterns of every CLDR locale of its language and script, since a language alone does
    not fix the order (CLDR `en` locales disagree). An unknown tag has none."""
    try:
        locale = Locale.parse(tag.replace("-", "_"))
    except (ValueError, TypeError, UnknownLocaleError):
        return frozenset()
    if locale.territory:
        order = _pattern_order(locale)
        return frozenset() if order is None else frozenset({order})
    return _language_orders(locale.language, locale.script)


@cache  # keyed by CLDR language and script, a finite set
def _language_orders(language: str, script: str | None) -> frozenset[Order]:
    locales = (Locale.parse(identifier) for identifier in locale_identifiers())
    return frozenset(
        order
        for loc in locales
        if loc.language == language and (script is None or loc.script == script)
        if (order := _pattern_order(loc)) is not None
    )


def _pattern_order(locale: Locale) -> Order | None:
    """The order of the year, month and day fields in the locale's short date pattern (UTS #35 Part 4 §8)."""
    pattern = _QUOTED.sub("", locale.date_formats["short"].pattern)
    if any(letter not in pattern for letter in "yMd"):
        return None
    # CLDR date pattern letters (UTS #35 Part 4 §8): `y` year, `M` month, `d` day.
    order = "".join(sorted("yMd", key=pattern.find)).upper()
    return next((o for o in _ORDERS if o == order), None)


def _languages(ctx: Context) -> tuple[str, ...]:
    """The languages of the page's locales that `dateparser` reads, as primary language subtags (BCP 47 §2.2.1)."""
    primary = (re.split(r"[-_]", tag, maxsplit=1)[0].lower() for tag in (ctx.html_lang, ctx.og_locale) if tag)
    return tuple(dict.fromkeys(language for language in primary if language in _DATEPARSER_LANGUAGES))


def equal(a: JsonValue, b: JsonValue, _spec: FieldSpec) -> bool:
    """SPEC-04 §4.5: exact. A normalized value has one form (D-0296: a datetime is in UTC)."""
    return a == b


def key(value: JsonValue, _spec: FieldSpec) -> Hashable:
    return raw_key(value)  # equality is exact
