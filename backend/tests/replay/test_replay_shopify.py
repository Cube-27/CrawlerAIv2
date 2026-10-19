"""Storefront API answers replayed through `extract_page` (adapters spec): a collection page's answer publishes one
row per product, with a price only where its range is one price.

The answers are synthetic, written to the documented shapes (`example.test` hosts, invented products, C3, C9).
"""

import asyncio
import json
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
from tests.replay.captures import capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(
    vocabulary=VOCABULARY,
    orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER),
    calibration=None,
    adapters=Registry([Shopify()]),
)
SHOP = "https://shop.example.test"
ENDPOINT = f"{SHOP}/api/{API_VERSION}/graphql.json"


def _preset(name: str) -> SchemaDef:
    preset = next(p for p in load_presets() if p.name == name)
    return SchemaDef(**preset.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


LISTING = _preset("commerce_listing")


def _extract(page_url: str, answer: JsonValue, schema: SchemaDef) -> ExtractionResult:
    raw = json.dumps(answer).encode()
    bundle = capture(raw, url=page_url, final_url=ENDPOINT, api=True, headers=(("X-Shopify-API-Version", API_VERSION),))
    return asyncio.run(extract_page(bundle, schema, None, None, data=DATA))


def _money(amount: str) -> dict[str, JsonValue]:
    return {"amount": amount, "currencyCode": "EUR"}


def _shop(*currencies: str) -> dict[str, JsonValue]:
    return {"paymentSettings": {"enabledPresentmentCurrencies": list(currencies)}}


def _published(fields: FieldSet) -> dict[str, JsonValue]:
    return {name: outcome.value for name, outcome in fields.items() if outcome.status == "published"}


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
def test_every_listed_product_is_a_row_priced_only_when_its_range_is_one_price(
    prices: list[tuple[str, str]],
) -> None:
    result = _extract(f"{SHOP}/collections/widgets", _collection(prices), LISTING)

    assert result.outcome == "extracted"
    expected = [
        {"title": f"Widget {n}", "url": f"{SHOP}/products/widget-{n}"}
        | ({"price": {"amount": low, "currency": "EUR"}} if low == high else {})
        for n, (low, high) in enumerate(prices)
    ]
    # A range's bounds are two Offers and the answer states no one price of the product: a range is no price.
    assert [_published(row) for row in result.rows] == expected
    assert [row["price"].reason for row in result.rows if row["price"].status == "conflict"] == [
        "offers_disagree" for low, high in prices if low != high
    ]


@pytest.mark.parametrize("currencies", [("EUR", "SEK"), ()])
def test_a_shop_that_may_show_another_currency_lists_its_products_without_the_answers_prices(
    currencies: tuple[str, ...],
) -> None:
    # The API prices in the shop's primary market; a shop presenting several currencies may show the page in another
    # market, with other amounts, so an answer's amount is not the page's price even with its currency unknown. Live,
    # such a shop is not served (`test_shopify_adapter`) and the page path publishes the price the page shows.
    answer = _collection([("1.00", "1.00"), ("2.00", "2.00")], currencies)

    result = _extract(f"{SHOP}/collections/widgets", answer, LISTING)

    assert [_published(row) for row in result.rows] == [
        {"title": f"Widget {n}", "url": f"{SHOP}/products/widget-{n}"} for n in (0, 1)
    ]
