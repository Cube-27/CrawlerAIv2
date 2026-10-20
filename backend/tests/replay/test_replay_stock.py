"""Availability and stock quantity replayed through `extract_page` on synthetic captures (D-0782, schemas spec): an
Offer that writes its availability in words publishes the schema.org member its first clause names, or declines;
`inventoryLevel` publishes as the count `stock_quantity` of preset `commerce_detail` version 4. Pages are synthetic
(`example.test`, C3, C9)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from tests.replay.captures import PAGE_URL, capture

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def _fields(offer: dict[str, Any]) -> dict[str, tuple[str, str | None, JsonValue]]:
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Synthetic Widget",
        "url": PAGE_URL,
        "sku": "W-1",
        "offers": {"@type": "Offer", "price": "10.00", "priceCurrency": "EUR"} | offer,
    }
    raw = f'<html><head><script type="application/ld+json">{json.dumps(product)}</script></head></html>'.encode()
    result = asyncio.run(extract_page(capture(raw), SCHEMA, None, None, data=DATA))
    assert result.entity is not None
    outcomes = {name: result.entity[name] for name in ("availability", "stock_quantity")}
    return {name: (o.status, o.reason, o.value) for name, o in outcomes.items()}


@pytest.mark.parametrize(
    ("offer", "availability", "stock"),
    [
        ({"availability": "In stock (5 available)", "inventoryLevel": "5"}, ("published", None, "InStock"), 5),
    ],
)
def test_an_offer_s_availability_and_inventory_level_publish_as_two_fields(
    offer: dict[str, Any], availability: tuple[str, None, JsonValue], stock: int | None
) -> None:
    fields = _fields(offer)

    assert fields["availability"] == availability
    published = ("published", None, stock)
    assert fields["stock_quantity"] == (published if stock is not None else ("missing", "no_candidates", None))


@pytest.mark.parametrize("written", ["Not in stock"])
def test_availability_text_that_qualifies_or_negates_a_member_never_publishes_one(written: str) -> None:
    assert _fields({"availability": written})["availability"] == ("missing", "invalid", None)


def test_each_source_s_one_offer_is_the_item_s_offer() -> None:
    # Two sources state the product and one Offer each: the microdata Offer names more fields, the JSON-LD one alone
    # states the availability, which is that one offer's, not another variant's.
    product = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Synthetic Widget",
        "url": PAGE_URL,
        "sku": "W-1",
        "offers": {"@type": "Offer", "price": "10.00", "priceCurrency": "EUR", "availability": "PreOrder"},
    }
    microdata = (
        '<div itemscope itemtype="https://schema.org/Product"><span itemprop="sku">W-1</span>'
        f'<link itemprop="url" href="{PAGE_URL}"><div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<meta itemprop="sku" content="W-1"><meta itemprop="gtin" content="4006381333931">'
        '<meta itemprop="price" content="10.00"><meta itemprop="priceCurrency" content="EUR"></div></div>'
    )
    raw = f'<html><head><script type="application/ld+json">{json.dumps(product)}</script></head>'
    raw += f"<body>{microdata}</body></html>"

    result = asyncio.run(extract_page(capture(raw.encode()), SCHEMA, None, None, data=DATA))

    assert result.entity is not None
    assert (result.entity["availability"].status, result.entity["availability"].value) == ("published", "PreOrder")
