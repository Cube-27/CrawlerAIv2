"""The money normalizer (normalization spec): CLDR currency symbols and number symbols (Babel) for the
locales the context states, `price-parser` to locate the amount. A grounded amount always gives a value, its currency
from the best evidence or unknown; it declines on ambiguous decimal separators, ranges and amounts that are not
positive. The tests use ISO codes and CLDR symbols only (normalization spec)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.normalize import money
from crawlerai.normalize.base import Ambiguous, Basis, Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

AT = datetime(2026, 1, 1, tzinfo=UTC)
CTX = Context(captured_at=AT)
MONEY = FieldSpec(type=FieldType.MONEY)
_CODES = ["EUR", "USD", "GBP", "CHF", "INR", "JPY"]
_amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("999999999.99"), places=2)


def _ok(amount: str, currency: str | None, basis: Basis | None = None, *, checked: bool = True) -> Ok:
    return Ok({"amount": amount, "currency": currency}, basis=basis, checked=checked)


def _ctx(**fields: object) -> Context:
    return Context(captured_at=AT, **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw", ["$ 12", "12", {"price": "12"}, {"price": "12", "priceCurrency": "eur"}, {"amount": 12, "currency": None}]
)
def test_a_grounded_amount_whose_currency_nothing_settles_publishes_with_it_unknown(raw: JsonValue) -> None:
    # Owner decision 2026-10-18: the price is never skipped for its currency, and none is invented (C7: never USD).
    result = money.normalize(raw, MONEY, _ctx(html_lang="en"))

    assert isinstance(result, Ok)
    assert (result.value, result.basis) == ({"amount": "12", "currency": None}, "unknown")
    # Only a text with a sign, or a structured value, shows money's checked syntax.
    assert result.checked == (raw != "12")


def test_the_currency_comes_from_the_best_evidence_with_weaker_evidence_noted() -> None:
    # 1. Written with the price; 2. the item's structured data; 3. a page-wide declaration, consistent across the page;
    # 4. the page's locale and region narrowing a shared sign to one currency.
    assert money.normalize("$12 CAD", MONEY, CTX) == _ok("12", "CAD")
    assert money.normalize("$ 12", MONEY, _ctx(page_currencies=("CAD",), declared_currencies=("AUD",))) == _ok(
        "12", "CAD"
    )
    assert money.normalize("$ 12", MONEY, _ctx(declared_currencies=("AUD",))) == _ok("12", "AUD", "page")
    assert money.normalize("12", MONEY, _ctx(declared_currencies=("AUD",))) == _ok("12", "AUD", "page", checked=False)
    assert money.normalize("12", MONEY, _ctx(page_currencies=("AUD",), declared_currencies=("NZD",))) == _ok(
        "12", None, "unknown", checked=False
    )
    assert money.normalize("$12.99", MONEY, _ctx(html_lang="en-AU")) == _ok("12.99", "AUD", "locale")
    assert money.normalize("$12.99", MONEY, _ctx(html_lang="en", cctld_territory="CA")) == _ok("12.99", "CAD", "locale")
    cctld = "ca"  # RFC 1591: a two-letter ISO 3166-1 code; the host is synthetic, under RFC 2606's `example` label
    assert money.normalize("$5", MONEY, _ctx(page_url=f"https://shop.example.{cctld}/p")) == _ok("5", "CAD", "locale")
    assert money.normalize("$5", MONEY, _ctx(content_language=("en-NZ",))) == _ok("5", "NZD", "locale")
    # The locale a request asked for is the caller's, not the page's; two territories that read `$` differently settle
    # nothing.
    assert money.normalize("$5", MONEY, _ctx(request_locale="en-AU")) == _ok("5", None, "unknown")
    assert money.normalize("$5", MONEY, _ctx(html_lang="en-US", og_locale="en-CA")) == _ok("5", None, "unknown")


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
        ("EUR 12\ud800", "surrogate"),
        (True, "not_money"),
        (None, "not_money"),
        ({"priceCurrency": "EUR"}, "no_amount"),
        ({"price": "€12.50", "priceCurrency": "USD"}, "currency_conflict"),
        ({"price": "$10 - $20", "priceCurrency": "USD"}, "range"),
        ({"price": "Free", "priceCurrency": "EUR"}, "no_amount"),
        ({"amount": "$12.50", "currency": "USD"}, "unparsable_amount"),
        ({"price": float("nan"), "priceCurrency": "EUR"}, "unparsable_amount"),
        ({"price": "1000000000000", "priceCurrency": "EUR"}, "out_of_range"),
        ({"price": "0", "priceCurrency": "EUR"}, "not_positive"),
        ("EUR 1." + "9" * 40, "out_of_range"),
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
