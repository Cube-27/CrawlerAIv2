"""The currencies a page states (normalization spec, money): schema.org `priceCurrency` in JSON-LD, microdata and RDFa
Lite, and page-wide declarations (OGP price currency, generic currency members of state JSON); ISO 4217 codes as
written, each once."""

import json
from datetime import UTC, datetime
from typing import Any

from crawlerai.collect.currencies import (
    declared_currencies,
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
    # schemas spec: `$` alone stands for several currencies; the Offer's USD settles it.
    page = _page(_jsonld({"@context": "https://schema.org", "@type": "Offer", "priceCurrency": "USD"}))
    spec = FieldSpec(type=FieldType.MONEY, description="d")

    assert money.normalize("$12.50", spec, CTX) == Ok({"amount": "12.50", "currency": None}, basis="unknown")
    assert money.normalize("$12.50", spec, with_page_declarations(CTX, page)) == Ok(
        {"amount": "12.50", "currency": "USD"}
    )


def test_a_page_declares_currencies_in_ogp_and_in_generic_state_members() -> None:
    state = {"shop": {"activeCurrency": "SEK", "cart": [{"currency_code": "SEK"}, {"currency": "sek"}]}, "price": "EUR"}
    page = _page(
        '<meta property="og:price:currency" content="SEK"><meta property="product:price:currency" content="NOK">',
        f'<script type="application/json">{json.dumps(state)}</script>',
    )

    assert set(declared_currencies(page)) == {"SEK", "NOK"}
    # A price written without a sign takes the page's currency only when every statement agrees.
    one = _page('<meta property="og:price:currency" content="SEK">')
    spec = FieldSpec(type=FieldType.MONEY, description="d")
    assert money.normalize("12", spec, with_page_declarations(CTX, one)) == Ok(
        {"amount": "12", "currency": "SEK"}, basis="page", checked=False
    )
    assert money.normalize("12", spec, with_page_declarations(CTX, page)) == Ok(
        {"amount": "12", "currency": None}, basis="unknown", checked=False
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
