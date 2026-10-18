"""The currencies a page's structured data states (schemas spec): schema.org `priceCurrency` in JSON-LD, microdata
and RDFa Lite, and the OGP `product:price:currency`; ISO 4217 codes as written, each once."""

import json
from datetime import UTC, datetime
from typing import Any

from crawlerai.collect.currencies import stated_currencies, with_stated_currencies
from crawlerai.content.page import ParsedPage
from crawlerai.normalize import money
from crawlerai.normalize.base import Context, Ok
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

    assert not isinstance(money.normalize("$12.50", spec, CTX), Ok)
    assert money.normalize("$12.50", spec, with_stated_currencies(CTX, page)) == Ok(
        {"amount": "12.50", "currency": "USD"}
    )
