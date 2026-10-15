"""The currencies a page's structured data states (SPEC-04 §4.4): schema.org `priceCurrency` in JSON-LD, microdata
and RDFa Lite, and the OGP `product:price:currency`; ISO 4217 codes as written, each once."""

import json
from datetime import UTC, datetime
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.currencies import stated_currencies, with_stated_currencies
from crawlerai.content.page import ParsedPage
from crawlerai.normalize import money
from crawlerai.normalize.base import Context, Ok
from crawlerai.schemas.types import FieldSpec, FieldType

CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC))
_CODES = sorted(c for c in ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "INR", "CHF") if money.is_currency_code(c))


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


def test_a_bare_term_outside_schema_org_is_not_read_but_a_full_iri_is() -> None:
    other = {"@context": "https://vocab.example.test/", "priceCurrency": "USD"}
    iri = {"https://schema.org/priceCurrency": "JPY"}
    assert stated_currencies(_page(_jsonld(other, iri))) == ("JPY",)


def test_microdata_and_rdfa_state_currencies_in_a_schema_org_item() -> None:
    body = (
        '<div itemscope itemtype="https://schema.org/Offer"><span itemprop="price">$12.50</span>'
        '<meta itemprop="priceCurrency" content="USD"></div>'
        '<div itemscope><meta itemprop="priceCurrency" content="CAD"></div>'  # an untyped item: no vocabulary
        '<div vocab="https://schema.org/" typeof="Offer"><span property="priceCurrency">CHF</span></div>'
    )
    assert stated_currencies(_page(body=body)) == ("USD", "CHF")


def test_open_graph_states_the_product_price_currency() -> None:
    head = '<meta property="product:price:currency" content="INR"><meta name="og:currency" content="AUD">'
    assert stated_currencies(_page(head)) == ("INR",)


def test_values_that_are_not_iso_4217_codes_as_written_are_not_currencies() -> None:
    node = {"@context": "https://schema.org", "@type": "Offer", "priceCurrency": ["usd", "US$", "QQQ", " EUR ", 5]}
    assert stated_currencies(_page(_jsonld(node))) == ("EUR",)


@given(st.lists(st.sampled_from(_CODES), min_size=1, max_size=4))
def test_each_stated_code_is_read_once_in_the_order_written(codes: list[str]) -> None:
    nodes = [{"@context": "https://schema.org", "@type": "Offer", "priceCurrency": code} for code in codes]
    assert stated_currencies(_page(_jsonld(*nodes))) == tuple(dict.fromkeys(codes))


def test_the_stated_currency_settles_a_symbol_the_page_writes_in_text() -> None:
    # SPEC-04 §4.4: `$` alone stands for several currencies; the Offer's USD settles it.
    page = _page(_jsonld({"@context": "https://schema.org", "@type": "Offer", "priceCurrency": "USD"}))
    spec = FieldSpec(type=FieldType.MONEY, description="d")

    assert not isinstance(money.normalize("$12.50", spec, CTX), Ok)
    assert money.normalize("$12.50", spec, with_stated_currencies(CTX, page)) == Ok(
        {"amount": "12.50", "currency": "USD"}
    )
