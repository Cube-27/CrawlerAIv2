"""The date and datetime normalizer (normalization spec): ISO 8601 output, RFC 3339 input parsed directly,
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
# The first call for a locale loads its CLDR and `dateparser` data from disk, which can exceed the default deadline.
_LOADS_LOCALE_DATA = settings(deadline=None)


def _ctx(html_lang: str | None = None, og_locale: str | None = None) -> Context:
    return Context(captured_at=AT, html_lang=html_lang, og_locale=og_locale)


def normalize(raw: JsonValue, spec: FieldSpec = DATE, ctx: Context = CTX) -> object:
    return date_module.normalize(raw, spec, ctx)


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
        ("2026-03-04T10:00:00.000+0100", "2026-03-04T09:00:00Z"),
        ("2026-03-04T10:00:00-05", "2026-03-04T15:00:00Z"),
        ("2026-03-04 10:00:00 UTC", "2026-03-04T10:00:00Z"),
        ("2026-01-01T10:30.5Z", "2026-01-01T10:30:30Z"),  # a fraction after minutes is of a minute
    ],
)
def test_iso_8601_forms_parse_directly_without_a_language(raw: str, expected: str) -> None:
    assert normalize(raw, DATETIME) == Ok(expected)
    assert normalize(raw) == Ok(expected[:10])


@_LOADS_LOCALE_DATA
@given(st.integers(1, 12), st.integers(1, 12), st.integers(1970, 2100), st.sampled_from("/.-"))
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


@pytest.mark.parametrize(
    ("ctx", "expected"),
    [
        (_ctx("de-DE", "en_US"), Ambiguous("date_order", ("2026-03-04", "2026-04-03"))),  # the locales disagree
        (_ctx("en"), Ambiguous("date_order", ("2026-03-04", "2026-04-03"))),  # en_US, en_GB order differently
        (_ctx("de"), Ok("2026-04-03")),  # every CLDR locale of `de` is day first
    ],
)
def test_the_locale_set_decides_the_date_order(ctx: Context, expected: object) -> None:
    assert normalize("03/04/2026", ctx=ctx) == expected
    assert normalize("13/04/2026") == Ok("2026-04-13")
    assert normalize("13/04/2026", ctx=_ctx(og_locale="en_US")) == Invalid("not_a_date")


@pytest.mark.parametrize(
    ("raw", "ctx", "expected"),
    [
        ("4 March 2026", _ctx("en"), Ok("2026-03-04")),
        ("4. März 2026", _ctx("de"), Ok("2026-03-04")),
        ("March 2026", _ctx("en"), Invalid("not_a_date")),
        ("4 March 2026", CTX, Invalid("no_language")),
        ("2 days ago", _ctx("en"), Ok("2026-03-08")),
        ("yesterday", _ctx("en"), Ok("2026-03-09")),
        ("1 month ago", _ctx("en"), Invalid("not_a_date")),
    ],
)
def test_text_dates_parse_in_the_page_language_and_relative_ones_count_from_the_capture_time(
    raw: str, ctx: Context, expected: object
) -> None:
    assert normalize(raw, ctx=ctx) == expected


@pytest.mark.parametrize(
    ("raw", "ctx", "expected"),
    [
        ("2026-03-04", CTX, Invalid("no_time")),
        ("2026-03-04T10:00:00", CTX, Invalid("no_offset")),
        # A zone abbreviation names more than one offset, so only numeric offsets count.
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
        ("2100-12-31T23:00:00-05:00", DATETIME),  # the year is checked in UTC
        ("4 March 1969", DATE),
    ],
)
def test_a_year_outside_1970_to_2100_is_invalid(raw: str, spec: FieldSpec) -> None:
    assert normalize(raw, spec, _ctx("en-GB")) == Invalid("year_out_of_range")
    assert normalize("2100-12-31T23:00:00-05:00", DATE) == Ok("2100-12-31")


def test_a_lone_surrogate_is_invalid_and_another_type_is_a_programming_error() -> None:
    assert normalize("2026-03-04\ud800") == Invalid("surrogate")
    with pytest.raises(TypeError):
        normalize("2026-03-04", FieldSpec(type=FieldType.TEXT))
