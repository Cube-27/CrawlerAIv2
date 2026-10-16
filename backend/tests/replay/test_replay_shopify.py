"""Storefront API answers replayed through `extract_page` (SPEC-15 §4.5, §7): a product page's answer publishes the
product, its variants as rows and the offer fields every variant agrees on; a collection page's answer publishes one
row per product, with a price only where its range is one price.

The answers are synthetic, written to the documented shapes (`example.test` hosts, invented products, C3, C9).
"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.adapters.registry import Registry
from crawlerai.adapters.shopify import API_VERSION, Shopify
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult, FieldSet
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(
    vocabulary=VOCABULARY,
    orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER),
    calibration=None,
    adapters=Registry([Shopify()], active={"shopify"}),
)
SHOP = "https://shop.example.test"
ENDPOINT = f"{SHOP}/api/{API_VERSION}/graphql.json"


def _preset(name: str) -> SchemaDef:
    preset = next(p for p in load_presets() if p.name == name)
    return SchemaDef(**preset.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


DETAIL, LISTING = _preset("commerce_detail"), _preset("commerce_listing")


def _extract(page_url: str, answer: JsonValue, schema: SchemaDef) -> ExtractionResult:
    raw = json.dumps(answer).encode()
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=page_url,
        final_url=ENDPOINT,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="api",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("X-Shopify-API-Version", API_VERSION),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    bundle = CaptureBundle(manifest=manifest, body=raw, network=())
    return asyncio.run(extract_page(bundle, schema, None, None, data=DATA))


def _money(amount: str) -> dict[str, JsonValue]:
    return {"amount": amount, "currencyCode": "EUR"}


def _variant(n: int, price: str, *, title: str | None = None, for_sale: bool = True) -> dict[str, JsonValue]:
    return {
        "id": f"gid://shopify/ProductVariant/{n}",
        "title": title or f"Size {n}",
        "sku": f"W-{n}",
        "barcode": None,
        "availableForSale": for_sale,
        "currentlyNotInStock": False,
        "price": _money(price),
    }


def _shop(*currencies: str) -> dict[str, JsonValue]:
    return {"paymentSettings": {"enabledPresentmentCurrencies": list(currencies)}}


def _product(*variants: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "data": {
            "shop": _shop("EUR"),
            "product": {
                "id": "gid://shopify/Product/1",
                "title": "Synthetic Widget",
                "description": "A widget for tests.",
                "vendor": "Synthetic Works",
                "onlineStoreUrl": f"{SHOP}/products/widget",
                "featuredImage": {"url": f"{SHOP}/img/1.png"},
                "images": {"nodes": [{"url": f"{SHOP}/img/{n}.png"} for n in (1, 2, 3)]},
                "variants": {"nodes": list(variants)},
            },
        }
    }


def _published(fields: FieldSet) -> dict[str, JsonValue]:
    return {name: outcome.value for name, outcome in fields.items() if outcome.status == "published"}


def test_a_product_whose_variants_agree_publishes_the_page_and_one_row_per_variant() -> None:
    result = _extract(f"{SHOP}/products/widget", _product(*(_variant(n, "19.90") for n in (1, 2, 3))), DETAIL)

    assert result.entity is not None
    published = _published(result.entity)
    assert {k: v for k, v in published.items() if k != "variants"} == {
        "title": "Synthetic Widget",
        "price": {"amount": "19.90", "currency": "EUR"},
        "availability": "InStock",
        "url": f"{SHOP}/products/widget",
        "image_url": f"{SHOP}/img/1.png",
        "additional_images": [f"{SHOP}/img/{n}.png" for n in (1, 2, 3)],
        "description": "A widget for tests.",
        "brand": "Synthetic Works",
        "product_id": {"scheme": "custom", "value": "gid://shopify/Product/1"},
    }
    assert published["variants"] == [
        {
            "variant_id": {"scheme": "custom", "value": f"gid://shopify/ProductVariant/{n}"},
            "sku": {"scheme": "sku", "value": f"W-{n}"},
            "price": {"amount": "19.90", "currency": "EUR"},
            "availability": "InStock",
            "name": f"Size {n}",
        }
        for n in (1, 2, 3)
    ]
    assert {outcome.evidence for outcome in result.entity.values() if outcome.status == "published"} == {"adapter"}


def test_variants_that_disagree_keep_their_prices_in_their_rows_and_publish_no_page_price() -> None:
    answer = _product(_variant(1, "19.90"), _variant(2, "24.90", for_sale=False))

    result = _extract(f"{SHOP}/products/widget", answer, DETAIL)

    assert result.entity is not None
    assert (result.entity["price"].status, result.entity["availability"].status) == ("conflict", "conflict")
    rows = result.entity["variants"].value
    assert isinstance(rows, list)
    assert [(row["price"], row["availability"]) for row in rows if isinstance(row, dict)] == [
        ({"amount": "19.90", "currency": "EUR"}, "InStock"),
        ({"amount": "24.90", "currency": "EUR"}, "OutOfStock"),
    ]


def test_the_one_variant_of_a_product_without_options_has_no_name() -> None:
    result = _extract(f"{SHOP}/products/widget", _product(_variant(1, "5.00", title="Default Title")), DETAIL)

    assert result.entity is not None
    published = _published(result.entity)
    assert published["sku"] == {"scheme": "sku", "value": "W-1"}  # every variant agrees: variant fill
    rows = published["variants"]
    assert isinstance(rows, list)
    assert [sorted(row) for row in rows if isinstance(row, dict)] == [["availability", "price", "sku", "variant_id"]]


def _collection(prices: list[tuple[str, str]], currencies: tuple[str, ...] = ("EUR",)) -> dict[str, JsonValue]:
    nodes: list[JsonValue] = [
        {
            "id": f"gid://shopify/Product/{n}",
            "title": f"Widget {n}",
            "onlineStoreUrl": f"{SHOP}/products/widget-{n}",
            "featuredImage": {"url": f"{SHOP}/img/{n}.png"},
            "priceRange": {"minVariantPrice": _money(low), "maxVariantPrice": _money(high)},
        }
        for n, (low, high) in enumerate(prices)
    ]
    return {"data": {"shop": _shop(*currencies), "collection": {"products": {"nodes": nodes}}}}


amounts = st.integers(min_value=1, max_value=99_999).map(lambda cents: f"{cents // 100}.{cents % 100:02d}")


@given(prices=st.lists(st.tuples(amounts, amounts), min_size=1, max_size=8))
def test_every_listed_product_is_a_row_with_a_price_only_when_its_range_is_one_price(
    prices: list[tuple[str, str]],
) -> None:
    result = _extract(f"{SHOP}/collections/widgets", _collection(prices), LISTING)

    assert result.outcome == "extracted"
    expected = [
        {"title": f"Widget {n}", "url": f"{SHOP}/products/widget-{n}"}
        | ({"price": {"amount": low, "currency": "EUR"}} if low == high else {})
        for n, (low, high) in enumerate(prices)
    ]
    assert [_published(row) for row in result.rows] == expected


@pytest.mark.parametrize("currencies", [("EUR", "SEK"), ()])
def test_a_shop_that_may_show_another_currency_lists_its_products_without_prices(currencies: tuple[str, ...]) -> None:
    # SPEC-15 §4.5: the API prices in the shop's primary market; a shop presenting several currencies may show the
    # page in another one, so no listed price is the page's for certain (C7).
    answer = _collection([("1.00", "1.00"), ("2.00", "2.00")], currencies)

    result = _extract(f"{SHOP}/collections/widgets", answer, LISTING)

    assert [_published(row) for row in result.rows] == [
        {"title": f"Widget {n}", "url": f"{SHOP}/products/widget-{n}"} for n in (0, 1)
    ]
