"""A detail page's DOM passes replayed through `extract_page` (extraction spec, "Structural DOM values"): they skip the
cards of other items, whose prices structured data does not state, and do not run when two kinds of structured data
agree on every required field of a schema without variants. Pages are synthetic (`example.test`, C3, C9)."""

import asyncio
import json
from pathlib import Path

from pydantic import JsonValue

from crawlerai.collect.run import SETTLED
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Ok
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from tests.replay.captures import PAGE_URL, capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm", "dom")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
FIELDS = {
    "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
    "price": FieldSpec(type=FieldType.MONEY, description="d", required=True, schema_org="Offer.price+priceCurrency"),
    "brand": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
}
SCHEMA = SchemaDef(id=SchemaId(uuid7()), origin="user", status="active", name="s", page_kind="detail", fields=FIELDS)
VARIANTS = FieldSpec.model_validate(
    {
        "type": "list",
        "description": "d",
        "schema_org": "ProductGroup.hasVariant",
        "key": ["sku"],
        "item": {"type": "object", "fields": {"sku": {"type": "identifier", "scheme": "sku"}}},
    }
)


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


def test_without_a_stated_price_no_card_is_set_apart() -> None:
    result = _extract("", PRODUCT + CARD)

    assert "price" not in _dom(result)  # $80 and $20: no price is the product's for certain


def test_structured_data_that_agrees_on_every_required_field_settles_the_page() -> None:
    microdata = (
        '<div itemscope itemtype="https://schema.org/Product"><meta itemprop="name" content="Synthetic Shoe">'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="{}">'
        '<meta itemprop="priceCurrency" content="USD"></div></div>'
    )
    agreeing = _extract(_jsonld("80.00"), PRODUCT + microdata.format("80.00"))
    differing = _extract(_jsonld("80.00"), PRODUCT + microdata.format("85.00"))
    variants = SCHEMA.model_copy(update={"fields": {**FIELDS, "variants": VARIANTS}})
    with_variants = _extract(_jsonld("80.00"), PRODUCT + microdata.format("80.00"), variants)

    assert _dom(agreeing) == {}
    assert SETTLED in agreeing.diagnostics
    assert _dom(differing)
    assert SETTLED not in differing.diagnostics
    assert _dom(with_variants)
    assert SETTLED not in with_variants.diagnostics
