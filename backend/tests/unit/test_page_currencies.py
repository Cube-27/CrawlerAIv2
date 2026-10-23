"""The currencies a page states (money): schema.org `priceCurrency` in JSON-LD, microdata and RDFa
Lite, page-wide declarations in the page's own name (OGP price currency, a platform's documented currency global) and
the generic currency members of state JSON; ISO 4217 codes as written, each once; and the decimal symbol of the page's
structured prices."""

import json
from datetime import UTC, datetime
from typing import Any

from crawlerai.collect.currencies import (
    declared_currencies,
    state_currencies,
    stated_currencies,
    stated_languages,
    with_page_declarations,
)
from crawlerai.content.page import ParsedPage
from crawlerai.normalize import money
from crawlerai.normalize.base import Ambiguous, Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))


def _jsonld(*nodes: Any) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(n)}</script>' for n in nodes)


def _page(head: str = "", body: str = "") -> ParsedPage:
    return ParsedPage(f"<html><head>{head}</head><body>{body}</body></html>")


def test_untyped_and_nested_price_objects_state_theirs_too() -> None:
    node = {
        "@context": "https://schema.org",
        "@type": "Product",
        "offers": {
            "@type": "AggregateOffer",
            "priceCurrency": "EUR",
            "priceSpecification": [{"price": 3, "priceCurrency": "GBP"}, {"priceCurrency": {"@value": "EUR"}}],
        },
    }
    assert stated_currencies(_page(_jsonld(node))) == ("EUR", "GBP")


def test_values_that_are_not_iso_4217_codes_as_written_are_not_currencies() -> None:
    node = {"@context": "https://schema.org", "@type": "Offer", "priceCurrency": ["usd", "US$", "QQQ", " EUR ", 5]}
    assert stated_currencies(_page(_jsonld(node))) == ("EUR",)


def test_the_stated_currency_settles_a_symbol_the_page_writes_in_text() -> None:
    # `$` alone stands for several currencies; the Offer's CAD settles it, else the sign's primary does.
    page = _page(_jsonld({"@context": "https://schema.org", "@type": "Offer", "priceCurrency": "CAD"}))
    spec = FieldSpec(type=FieldType.MONEY, description="d")

    assert money.normalize("$12.50", spec, CTX) == Ok({"amount": "12.50", "currency": "USD"}, basis="symbol")
    assert money.normalize("$12.50", spec, with_page_declarations(CTX, page)) == Ok(
        {"amount": "12.50", "currency": "CAD"}
    )


def test_a_page_declares_currencies_in_ogp_and_in_generic_state_members() -> None:
    state = {"shop": {"activeCurrency": "SEK", "cart": [{"currency_code": "SEK"}, {"currency": "sek"}]}, "price": "EUR"}
    page = _page(
        '<meta property="og:price:currency" content="SEK"><meta property="product:price:currency" content="NOK">',
        f'<script type="application/json">{json.dumps(state)}</script>',
    )

    assert set(declared_currencies(page)) == {"SEK", "NOK"}
    assert state_currencies(page) == ("SEK",)
    # A price written without a sign takes the page's currency only when every statement agrees.
    one = _page('<meta property="og:price:currency" content="SEK">')
    spec = FieldSpec(type=FieldType.MONEY, description="d")
    assert money.normalize("12", spec, with_page_declarations(CTX, one)) == Ok(
        {"amount": "12", "currency": "SEK"}, basis="page", checked=False
    )
    assert money.normalize("12", spec, with_page_declarations(CTX, page)) == Ok(
        {"amount": "12", "currency": None}, basis="unknown", checked=False
    )


def test_the_pages_own_declaration_outranks_an_anonymous_state_member() -> None:
    state = '<script type="application/json">{"config": {"currency": "USD"}}</script>'
    own = _page('<meta property="og:price:currency" content="NZD">', state)
    spec = FieldSpec(type=FieldType.MONEY, description="d")

    for text in ("$12", "12"):
        found = money.normalize(text, spec, with_page_declarations(CTX, own))
        assert isinstance(found, Ok)
        assert found.value == {"amount": "12", "currency": "NZD"}
    # A state member alone still settles the sign.
    assert money.normalize("$12", spec, with_page_declarations(CTX, _page(body=state))) == Ok(
        {"amount": "12", "currency": "USD"}, basis="page"
    )


def test_the_in_language_of_the_pages_json_ld_is_a_declared_locale() -> None:
    page = _page(
        _jsonld(
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "inLanguage": ["de-DE", " "],
                "x": {"inLanguage": "de"},
            }
        )
    )
    spec = FieldSpec(type=FieldType.NUMBER)

    assert stated_languages(page) == ("de-DE", "de")
    assert normalize("1.250", spec, CTX) == Ambiguous("decimal_separator", ("1.250", "1250"))
    assert normalize("1.250", spec, with_page_declarations(CTX, page)) == Ok("1250")


def test_a_platform_declares_its_currency_in_its_documented_global_only_on_its_pages() -> None:
    shopify = (
        '<script id="shopify-features"></script><script>Shopify.currency = {"active":"CAD","rate":"1.0"};</script>'
    )
    shopware = "<script>window.salesChannelId = 'abc'; window.currencyIsoCode = 'CHF';</script>"

    assert declared_currencies(_page(body=shopify)) == ("CAD",)
    assert declared_currencies(_page(body=shopware)) == ("CHF",)
    # Without the platform's signal the global is no declaration.
    assert declared_currencies(_page(body="<script>window.currencyIsoCode = 'CHF';</script>")) == ()


def test_the_decimal_symbol_of_the_pages_structured_prices_settles_an_ambiguous_amount() -> None:
    offer = {"@context": "https://schema.org", "@type": "Offer", "price": "19.99"}
    page = _page(_jsonld(offer))
    spec = FieldSpec(type=FieldType.MONEY, description="d")

    assert normalize("1.234", spec, CTX) == Ambiguous(
        "decimal_separator", ({"amount": "1.234", "currency": None}, {"amount": "1234", "currency": None})
    )
    assert normalize("1.234", spec, with_page_declarations(CTX, page)) == Ok(
        {"amount": "1.234", "currency": None}, basis="unknown", checked=False
    )
    # Prices written with different decimal symbols settle nothing.
    mixed = _page(_jsonld(offer, {**offer, "price": "1.234,56"}))
    assert with_page_declarations(CTX, mixed).page_convention is None
