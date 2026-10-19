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
    # A language alone is every territory it is used in: `en` settles no shared sign, though it settles a separator.
    assert money.normalize("$12.99", MONEY, _ctx(html_lang="en")) == _ok("12.99", None, "unknown")
    cctld = "ca"  # RFC 1591: a two-letter ISO 3166-1 code; the host is synthetic, under RFC 2606's `example` label
    assert money.normalize("$5", MONEY, _ctx(page_url=f"https://shop.example.{cctld}/p")) == _ok("5", "CAD", "locale")
    assert money.normalize("$5", MONEY, _ctx(content_language=("en-NZ",))) == _ok("5", "NZD", "locale")
    # The locale a request asked for is the caller's, not the page's; two territories that read `$` differently settle
    # nothing.
    assert money.normalize("$5", MONEY, _ctx(request_locale="en-AU")) == _ok("5", None, "unknown")
    assert money.normalize("$5", MONEY, _ctx(html_lang="en-US", og_locale="en-CA")) == _ok("5", None, "unknown")


def _cctld(code: str) -> str:
    """A synthetic URL under RFC 2606's `example` label with the ccTLD `code` (RFC 1591)."""
    return f"https://shop.example.{code}/p"


@pytest.mark.parametrize(
    ("url", "lang"),
    [
        ("https://shop.example.com/p/1", None),  # a generic TLD
        ("https://shop.example.com/en-gb/fr-ca/p", None),  # two locale segments
        ("https://ar.example.com/p", "ar"),  # a subdomain naming a territory the page's language is not used in
        (_cctld("co"), "en"),  # likewise a ccTLD
    ],
)
def test_a_url_naming_no_one_territory_of_the_page_names_no_currency(url: str, lang: str | None) -> None:
    assert money.normalize({"price": "12"}, MONEY, _ctx(page_url=url, html_lang=lang)) == _ok("12", None, "unknown")
    # The final URL decides: the requested URL never settles what it leaves unsettled.
    requested = "https://shop.example.com/en-gb/p"
    ctx = _ctx(page_url=url, request_url=requested, html_lang=lang)
    expected = _ok("12", "GBP", "url") if url == "https://shop.example.com/p/1" else _ok("12", None, "unknown")
    assert money.normalize({"price": "12"}, MONEY, ctx) == expected


def test_a_hreflang_fallback_marker_is_no_page_language() -> None:
    ctx = _ctx(page_url="https://shop.example.com/en-gb/p", hreflang=("x-default",))
    assert money.normalize({"price": "12"}, MONEY, ctx) == _ok("12", "GBP", "url")


def test_a_sign_written_with_an_abbreviation_full_stop_is_also_the_symbol_without_it() -> None:
    # CLDR writes the abbreviation `kr` both with and without its full stop, for different sets of currencies.
    assert money.normalize("kr. 12", MONEY, _ctx(page_currencies=("NOK",))) == _ok("12", "NOK")


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
