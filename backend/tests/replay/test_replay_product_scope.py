"""A detail page's DOM passes replayed through `extract_page`: they skip the
cards of other items, whose prices structured data does not state. Pages are synthetic (`example.test`, C3, C9)."""

import asyncio
import json
from pathlib import Path

from pydantic import JsonValue

from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.support.captures import PAGE_URL, capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm", "dom")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
FIELDS = {
    "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
    "price": FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"),
    "brand": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
}
SCHEMA = SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=FIELDS)


def _extract(head: str, main: str, schema: SchemaDef = SCHEMA) -> ExtractionResult:
    raw = f"<html><head>{head}</head><body><main>{main}</main></body></html>".encode()
    return asyncio.run(extract_page(capture(raw), schema, None, None, data=DATA))


def _dom(result: ExtractionResult) -> dict[str, list[JsonValue]]:
    found: dict[str, list[JsonValue]] = {}
    for c in result.candidates:
        if c.source_kind == "dom" and isinstance(c.normalized, Ok):
            found.setdefault(c.field, []).append(c.normalized.value)
    return found


def _jsonld(price: str) -> str:
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Synthetic Shoe",
        "url": PAGE_URL,
        "offers": {"@type": "Offer", "price": price, "priceCurrency": "USD"},
    }
    return f'<script type="application/ld+json">{json.dumps(product)}</script>'


PRODUCT = "<h1>Synthetic Shoe</h1><p><span>$80.00</span></p><p>Brand: <span>Example Brand</span></p>"
# One "complete the look" card: a single block linking to another product, with that product's price and brand.
CARD = (
    '<section><div><a href="/p/2">Synthetic Belt</a><span>$20.00</span><p>Brand: <span>Other</span></p></div></section>'
)


def test_another_item_s_card_gives_the_dom_passes_no_value() -> None:
    result = _extract(_jsonld("80.00"), PRODUCT + CARD)

    assert _dom(result) == {"price": [{"amount": "80.00", "currency": "USD"}], "brand": ["Example Brand"]}


def test_a_card_whose_link_holds_only_its_price_is_set_apart() -> None:
    card = '<section><div><a href="/p/2"><span>$20.00</span></a><p>Brand: <span>Other</span></p></div></section>'

    result = _extract(_jsonld("80.00"), PRODUCT + card)

    assert _dom(result)["brand"] == ["Example Brand"]


def test_a_nested_product_item_without_the_title_is_set_apart() -> None:
    nested = (
        '<div itemscope itemtype="https://schema.org/Product">'
        + PRODUCT
        + '<div itemprop="isAccessoryOrSparePartFor" itemscope itemtype="https://schema.org/Product">'
        "<p>Brand: <span>Other</span></p></div></div>"
    )

    result = _extract(_jsonld("80.00"), nested)

    assert _dom(result)["brand"] == ["Example Brand"]


def test_without_a_stated_price_no_card_is_set_apart() -> None:
    result = _extract("", PRODUCT + CARD)

    assert "price" not in _dom(result)  # $80 and $20: no price is the product's for certain


def test_a_block_around_another_item_s_card_is_no_description() -> None:
    long_text = FieldSpec(type=FieldType.LONG_TEXT, description="d", schema_org="Product.description")
    schema = SCHEMA.model_copy(update={"fields": {**FIELDS, "description": long_text}})
    wrapped = f"<div><p>{'Woven upper, cushioned sole and a grippy outsole for the long walk. ' * 3}</p>{CARD}</div>"

    result = _extract(_jsonld("80.00"), PRODUCT + wrapped, schema)

    assert "Synthetic Belt" not in str(_dom(result).get("description"))


def test_a_related_item_s_stated_price_does_not_make_its_card_the_product_s() -> None:
    # A price structured data states for a related item (`isRelatedTo`) is in that item's scope (collect/scope.py),
    # so its card's shown price is still another item's.
    offer = {"@type": "Offer", "price": "20.00", "priceCurrency": "USD"}
    related = {"@type": "Product", "name": "Synthetic Belt", "url": f"{PAGE_URL}-belt", "offers": offer}
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Synthetic Shoe",
        "url": PAGE_URL,
        "offers": {"@type": "Offer", "price": "80.00", "priceCurrency": "USD"},
        "isRelatedTo": related,
    }

    result = _extract(f'<script type="application/ld+json">{json.dumps(product)}</script>', PRODUCT + CARD)

    assert _dom(result) == {"price": [{"amount": "80.00", "currency": "USD"}], "brand": ["Example Brand"]}


def test_a_root_of_another_kind_naming_the_page_does_not_set_the_product_apart() -> None:
    # The page's WebPage names the page; its Product states the URL under another path (a locale prefix). Only an item
    # of the Product's kind naming the page would make the Product another page's item (collect/scope.py).
    page = {"@context": "https://schema.org", "@type": "WebPage", "url": PAGE_URL}
    product = json.loads(_jsonld("80.00").removeprefix('<script type="application/ld+json">').removesuffix("</script>"))
    product["url"] = PAGE_URL.replace("example.test/", "example.test/en/")
    head = "".join(f'<script type="application/ld+json">{json.dumps(n)}</script>' for n in (page, product))

    result = _extract(head, PRODUCT + CARD)

    assert _dom(result)["price"] == [{"amount": "80.00", "currency": "USD"}]
