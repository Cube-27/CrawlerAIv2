"""The money normalizer (normalization spec): CLDR currency symbols and number symbols (Babel) for the
locales the context states, `price-parser` to locate the amount, and declines on ambiguous signs, ambiguous decimal
separators, ranges and amounts that are not positive. The tests use ISO codes and CLDR symbols only (normalization
spec)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import money
from crawlerai.normalize.base import Ambiguous, Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
MONEY = FieldSpec(type=FieldType.MONEY)
_CODES = ["EUR", "USD", "GBP", "CHF", "INR", "JPY"]
_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999999.99"), places=2)


def _ok(amount: str, currency: str) -> Ok:
    return Ok({"amount": amount, "currency": currency})


def _ctx(**fields: object) -> Context:
    return Context(captured_at=AT, **fields)  # type: ignore[arg-type]


def test_a_shared_symbol_without_context_is_ambiguous_and_never_defaults() -> None:
    result = money.normalize("$ 12", MONEY, CTX)  # C7: never USD by default

    assert isinstance(result, Ambiguous)
    assert {"amount": "12", "currency": "USD"} in result.options
    assert {"amount": "12", "currency": "CAD"} in result.options


def test_a_page_currency_or_territory_settles_a_shared_symbol() -> None:
    assert money.normalize("$ 12", MONEY, _ctx(page_currencies=("CAD",))) == _ok("12", "CAD")
    assert money.normalize("$12.99", MONEY, _ctx(html_lang="en-AU")) == _ok("12.99", "AUD")
    assert money.normalize("$12.99", MONEY, _ctx(html_lang="en", cctld_territory="CA")) == _ok("12.99", "CAD")
    assert isinstance(money.normalize("$12.99", MONEY, _ctx(html_lang="en")), Ambiguous)
    assert money.normalize("$12 CAD", MONEY, CTX) == _ok("12", "CAD")


def test_a_lone_separator_is_ambiguous_until_the_page_locale_settles_it() -> None:
    readings: tuple[JsonValue, ...] = ({"amount": "1.234", "currency": "EUR"}, {"amount": "1234", "currency": "EUR"})

    assert money.normalize("1.234 EUR", MONEY, CTX) == Ambiguous("decimal_separator", readings)
    assert money.normalize("1.234 EUR", MONEY, _ctx(html_lang="en-US")) == _ok("1.234", "EUR")
    assert money.normalize("1.234 EUR", MONEY, _ctx(html_lang="de-DE")) == _ok("1234", "EUR")
    # Locales that disagree decline.
    assert money.normalize("1.234 EUR", MONEY, _ctx(html_lang="en-US", og_locale="de_DE")) == Ambiguous(
        "decimal_separator", readings
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("-12.50 EUR", "not_positive"),
        ("\u221212.50 EUR", "not_positive"),
        ("0.00 EUR", "not_positive"),
        ("EUR 10 - 20", "range"),
        ("EUR 10 to 20", "range"),
        ("EUR", "no_amount"),
        ("12.50", "no_currency"),
        ("EUR 12\ud800", "surrogate"),
        (True, "not_money"),
        (None, "not_money"),
        ({"priceCurrency": "EUR"}, "no_amount"),
        ({"price": "12.50"}, "no_currency"),
        ({"price": "12.50", "priceCurrency": "eur"}, "unknown_currency"),
        ({"price": "€12.50", "priceCurrency": "USD"}, "currency_conflict"),
        ({"price": "$10 - $20", "priceCurrency": "USD"}, "range"),
        ({"price": "Free", "priceCurrency": "EUR"}, "no_amount"),
        ({"amount": "$12.50", "currency": "USD"}, "unparsable_amount"),
        ({"price": float("nan"), "priceCurrency": "EUR"}, "unparsable_amount"),
        ({"price": "1000000000000", "priceCurrency": "EUR"}, "out_of_range"),
        ({"price": "0", "priceCurrency": "EUR"}, "not_positive"),
    ],
)
def test_what_is_no_positive_single_price_is_invalid(raw: JsonValue, reason: str) -> None:
    assert money.normalize(raw, MONEY, CTX) == Invalid(reason)


@pytest.mark.parametrize(
    ("price", "tag", "amount"),
    [("$1,295.99", "en-US", "1295.99"), ("1.295,99", "de-DE", "1295.99")],
)
def test_a_structured_price_with_grouping_reads_in_the_page_locale(price: str, tag: str, amount: str) -> None:
    raw: JsonValue = {"price": price, "priceCurrency": "USD"}

    assert money.normalize(raw, MONEY, _ctx(html_lang=tag)) == _ok(amount, "USD")
