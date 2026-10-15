"""The date and datetime normalizer (SPEC-04 §4.4, ARCHITECTURE §9): ISO 8601 output, RFC 3339 input parsed directly,
other input through CLDR date orders and `dateparser`, and declines on order ambiguity, two-digit years, relative
datetimes, missing offsets and years outside 1970 to 2100."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import date as date_module
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
CTX = Context(captured_at=AT)
DATE = FieldSpec(type=FieldType.DATE)
DATETIME = FieldSpec(type=FieldType.DATETIME)

_dates = st.dates(min_value=date(1970, 1, 1), max_value=date(2100, 12, 31))
_offsets = st.integers(min_value=-14 * 60, max_value=14 * 60).map(lambda m: timezone(timedelta(minutes=m)))
_datetimes = st.datetimes(min_value=datetime(1970, 1, 2), max_value=datetime(2100, 12, 30), timezones=_offsets)
# The first call for a locale loads its CLDR and `dateparser` data from disk, once per process, which can take longer
# than Hypothesis's default deadline; the tests that read locale data have no deadline.
_LOADS_LOCALE_DATA = settings(deadline=None)


def _ctx(html_lang: str | None = None, og_locale: str | None = None) -> Context:
    return Context(captured_at=AT, html_lang=html_lang, og_locale=og_locale)


def normalize(raw: JsonValue, spec: FieldSpec = DATE, ctx: Context = CTX) -> object:
    return date_module.normalize(raw, spec, ctx)


@given(_dates)
def test_an_iso_date_round_trips(value: date) -> None:
    iso = value.isoformat()

    assert normalize(iso) == Ok(iso)


@given(_datetimes)
def test_an_rfc_3339_datetime_normalizes_to_utc_and_to_itself_and_a_date_field_takes_its_date(value: datetime) -> None:
    result = normalize(value.isoformat(), DATETIME)

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert result.value.endswith("Z")
    assert datetime.fromisoformat(result.value) == value
    assert normalize(result.value, DATETIME) == result
    # The date the datetime states, in its own offset, not in UTC.
    assert normalize(value.isoformat()) == Ok(value.date().isoformat())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-04T10:00Z", "2026-03-04T10:00:00Z"),
        ("2026-03-04t10:00:00.5+02:00", "2026-03-04T08:00:00.500000Z"),
        ("2026-03-04 00:30:00-01:30", "2026-03-04T02:00:00Z"),
        ("2026-03-04T10:00:00.123456789Z", "2026-03-04T10:00:00.123456Z"),
    ],
)
def test_rfc_3339_forms_parse_directly(raw: str, expected: str) -> None:
    assert normalize(raw, DATETIME) == Ok(expected)


def _iso_offset(minutes: int, form: str) -> str:
    """An ISO 8601 UTC offset in one of its forms: extended `±hh:mm`, basic `±hhmm`, or hours only `±hh`."""
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return {
        "extended": f"{sign}{hours:02d}:{rest:02d}",
        "basic": f"{sign}{hours:02d}{rest:02d}",
        "hours": f"{sign}{hours:02d}",
    }[form]


_ISO_LOCALES = st.sampled_from(["en-GB", "de-DE", "en-US", "fr"])


@_LOADS_LOCALE_DATA
@given(
    _datetimes.map(lambda v: v.replace(tzinfo=None)),
    st.sampled_from(["extended", "basic", "hours"]),
    st.integers(min_value=-14 * 60, max_value=14 * 60),
    st.sampled_from(["T", " "]),
    st.booleans(),
    _ISO_LOCALES,
)
def test_an_iso_datetime_with_any_offset_form_keeps_its_date_in_every_locale(
    value: datetime, form: str, minutes: int, sep: str, fraction: bool, lang: str
) -> None:
    if form == "hours":
        minutes = minutes // 60 * 60
    time = value.strftime("%H:%M:%S") + (".250" if fraction else "")
    raw = f"{value.date().isoformat()}{sep}{time}{_iso_offset(minutes, form)}"
    stated = value.replace(microsecond=250_000 if fraction else 0, tzinfo=timezone(timedelta(minutes=minutes)))

    assert normalize(raw, ctx=_ctx(lang)) == Ok(value.date().isoformat())
    result = normalize(raw, DATETIME, _ctx(lang))
    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert datetime.fromisoformat(result.value) == stated


@_LOADS_LOCALE_DATA
@given(_dates, st.sampled_from(["T10:00:00 UTC", " 10:00 UTC", "T23:30:00 GMT", " UTC"]), _ISO_LOCALES)
def test_a_date_first_iso_prefix_fixes_the_field_order_in_every_locale(value: date, suffix: str, lang: str) -> None:
    # ISO 8601 fixes the order of `YYYY-MM-DD`, so the page's day-first or month-first order never applies to it.
    assert normalize(f"{value.isoformat()}{suffix}", ctx=_ctx(lang)) == Ok(value.isoformat())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-04T10:00:00+0000", "2026-03-04T10:00:00Z"),
        ("2026-03-04T10:00:00.000+0100", "2026-03-04T09:00:00Z"),
        ("2026-03-04T10:00:00-05", "2026-03-04T15:00:00Z"),
        ("2026-03-04T10:00:00,5Z", "2026-03-04T10:00:00.500000Z"),
    ],
)
def test_iso_8601_offset_forms_parse_directly_without_a_language(raw: str, expected: str) -> None:
    assert normalize(raw, DATETIME) == Ok(expected)
    assert normalize(raw) == Ok("2026-03-04")


@_LOADS_LOCALE_DATA
@given(
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1970, max_value=2100),
    st.sampled_from("/.-"),
)
def test_a_numeric_date_valid_in_both_orders_is_ambiguous_without_a_locale(a: int, b: int, year: int, sep: str) -> None:
    raw = f"{a:02d}{sep}{b:02d}{sep}{year}"
    day_first, month_first = date(year, b, a).isoformat(), date(year, a, b).isoformat()

    result = normalize(raw)

    if a == b:
        assert result == Ok(day_first)
    else:
        assert result == Ambiguous("date_order", tuple(sorted([day_first, month_first])))
    assert normalize(raw, ctx=_ctx(og_locale="en_GB")) == Ok(day_first)
    assert normalize(raw, ctx=_ctx(og_locale="en_US")) == Ok(month_first)
    assert normalize(raw, ctx=_ctx("de-DE")) == Ok(day_first)


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        # en-US is month first and de-DE day first (CLDR short date patterns): the locale set disagrees.
        (_ctx("de-DE", "en_US"), Ambiguous("date_order", ("2026-03-04", "2026-04-03"))),
        # CLDR locales of the language `en` order dates differently (en_US, en_GB, en_CA).
        (_ctx("en"), Ambiguous("date_order", ("2026-03-04", "2026-04-03"))),
        # Every CLDR locale of `de` is day first.
        (_ctx("de"), Ok("2026-04-03")),
        (_ctx("not a tag"), Ambiguous("date_order", ("2026-03-04", "2026-04-03"))),
    ],
)
def test_the_locale_set_decides_the_date_order(ctx: Context, expected: object) -> None:
    assert normalize("03/04/2026", ctx=ctx) == expected


def test_a_numeric_date_valid_in_one_order_only_needs_no_locale() -> None:
    assert normalize("13/04/2026") == Ok("2026-04-13")
    assert normalize("2026/04/13") == Ok("2026-04-13")
    assert normalize("13/04/2026", ctx=_ctx(og_locale="en_US")) == Invalid("not_a_date")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # A two-digit year names a year in each century; only the 1970 to 2100 window settles which.
        ("03/04/26", Ok("2026-04-03")),
        ("03/04/85", Ambiguous("two_digit_year", ("1985-04-03", "2085-04-03"))),
        ("03/04/00", Ambiguous("two_digit_year", ("2000-04-03", "2100-04-03"))),
        ("4 March 85", Ambiguous("two_digit_year", ("1985-03-04", "2085-03-04"))),
        ("4 March 26", Ok("2026-03-04")),
    ],
)
def test_a_two_digit_year_resolves_only_through_the_year_range(raw: str, expected: object) -> None:
    assert normalize(raw, ctx=_ctx(og_locale="en_GB")) == expected


@pytest.mark.parametrize(
    ("raw", "ctx", "expected"),
    [
        ("4 March 2026", _ctx("en"), Ok("2026-03-04")),
        ("March 4, 2026", _ctx("en-US"), Ok("2026-03-04")),
        ("4. März 2026", _ctx("de"), Ok("2026-03-04")),
        ("4 March 2026 23:30 +02:00", _ctx("en"), Ok("2026-03-04")),
        ("March 2026", _ctx("en"), Invalid("not_a_date")),
        ("in stock", _ctx("en"), Invalid("not_a_date")),
        ("4 March 2026", CTX, Invalid("no_language")),
        ("4 March 2026", _ctx("xx-YY"), Invalid("no_language")),
    ],
)
def test_text_dates_parse_in_the_page_language(raw: str, ctx: Context, expected: object) -> None:
    assert normalize(raw, ctx=ctx) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2 days ago", Ok("2026-03-08")),
        ("yesterday", Ok("2026-03-09")),
        ("today", Ok("2026-03-10")),
        # A relative date coarser than a day does not name a day.
        ("1 month ago", Invalid("not_a_date")),
    ],
)
def test_a_relative_date_counts_from_the_capture_time(raw: str, expected: object) -> None:
    assert normalize(raw, ctx=_ctx("en")) == expected


def test_a_relative_date_depends_on_the_capture_time() -> None:
    ctx = Context(captured_at=AT + timedelta(days=30), html_lang="en")

    assert normalize("2 days ago", ctx=ctx) == Ok("2026-04-07")


@given(st.datetimes(min_value=datetime(1971, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)))
def test_a_relative_time_counts_back_from_the_capture_time(captured_at: datetime) -> None:
    ctx = Context(captured_at=captured_at, html_lang="en")

    assert normalize("3 hours ago", ctx=ctx) == Ok((captured_at - timedelta(hours=3)).date().isoformat())


@pytest.mark.parametrize(
    ("raw", "ctx", "expected"),
    [
        ("2026-03-04", CTX, Invalid("no_time")),
        ("03/04/2026", _ctx(og_locale="en_GB"), Invalid("no_time")),
        ("4 March 2026", _ctx("en"), Invalid("no_time")),
        ("2026-03-04T10:00:00", CTX, Invalid("no_offset")),
        ("4 March 2026 10:00", _ctx("en"), Invalid("no_offset")),
        # A zone abbreviation names more than one offset (IANA time zone database), so only numeric offsets count.
        ("4 March 2026 10:00 IST", _ctx("en"), Invalid("no_offset")),
        ("4 March 2026 10:00 +05:30", _ctx("en"), Ok("2026-03-04T04:30:00Z")),
        ("2 hours ago", _ctx("en"), Invalid("relative_datetime")),
    ],
)
def test_a_datetime_needs_a_time_and_a_numeric_offset(raw: str, ctx: Context, expected: object) -> None:
    assert normalize(raw, DATETIME, ctx) == expected


@pytest.mark.parametrize(
    ("raw", "spec"),
    [
        ("1969-12-31", DATE),
        ("2101-01-01", DATE),
        ("1969-12-31T23:00:00Z", DATETIME),
        # A datetime's value is in UTC, so its year is checked there too.
        ("2100-12-31T23:00:00-05:00", DATETIME),
        ("1970-01-01T00:30:00+01:00", DATETIME),
        ("31/12/1969", DATE),
        ("4 March 1969", DATE),
    ],
)
def test_a_year_outside_1970_to_2100_is_invalid(raw: str, spec: FieldSpec) -> None:
    assert normalize(raw, spec, _ctx("en-GB")) == Invalid("year_out_of_range")


def test_a_date_field_checks_the_year_of_the_date_it_states() -> None:
    assert normalize("2100-12-31T23:00:00-05:00", DATE) == Ok("2100-12-31")


@pytest.mark.parametrize("raw", ["2026-02-30", "2026-13-01", "31/31/2026", "2026-03-04T25:00:00Z"])
def test_an_impossible_date_is_invalid(raw: str) -> None:
    assert normalize(raw, ctx=_ctx("en-GB")) == Invalid("not_a_date")


@pytest.mark.parametrize("raw", [None, 20260304, True, ["2026-03-04"], {"@value": "2026-03-04"}])
def test_a_non_string_is_invalid(raw: JsonValue) -> None:
    assert normalize(raw) == Invalid("not_a_string")


@given(st.characters(categories=["Cs"]))
def test_input_with_a_lone_surrogate_is_invalid(surrogate: str) -> None:
    assert normalize(f"2026-03-04{surrogate}") == Invalid("surrogate")


@pytest.mark.parametrize("type_", [FieldType.TEXT, FieldType.MONEY])
def test_a_spec_of_another_type_is_a_programming_error(type_: FieldType) -> None:
    spec = FieldSpec(type=type_)

    with pytest.raises(TypeError):
        normalize("2026-03-04", spec)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-03-04 10:00 +0100", Ok("2026-03-04")),
        # `dateparser` reads this as another day; a reading must state the date its ISO 8601 prefix fixes.
        ("2026-03-04 March", Invalid("not_a_date")),
        ("2026-13-04 10:00 UTC", Invalid("not_a_date")),
    ],
)
def test_text_after_an_iso_date_never_changes_that_date(raw: str, expected: object) -> None:
    assert normalize(raw, ctx=_ctx("en-GB")) == expected
