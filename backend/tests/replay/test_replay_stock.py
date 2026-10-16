"""Availability and stock quantity replayed through `extract_page` on synthetic captures (D-0782, SPEC-04 §4.4): an
Offer that writes its availability in words publishes the schema.org member its first clause names, or declines;
`inventoryLevel` publishes as the count `stock_quantity` of preset `commerce_detail` version 4. Pages are synthetic
(`example.test`, C3, C9)."""

import asyncio
import json
from datetime import UTC, datetime
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
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
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
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=PAGE_URL,
        final_url=PAGE_URL,
        fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        method="http",
        status_code=200,
        block_class="ok",
        headers=Headers(request=(), response=(("Content-Type", "text/html"),)),
        timings_ms={},
        html_sha256=sha256_hex(raw),
        network_bodies=(),
        fetch_policy={},
        engine_version="0+cal.0",
    )
    result = asyncio.run(
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), SCHEMA, None, None, data=DATA)
    )
    assert result.entity is not None
    outcomes = {name: result.entity[name] for name in ("availability", "stock_quantity")}
    return {name: (o.status, o.reason, o.value) for name, o in outcomes.items()}


@pytest.mark.parametrize(
    ("offer", "availability", "stock"),
    [
        ({"availability": "In stock (5 available)", "inventoryLevel": "5"}, ("published", None, "InStock"), 5),
        ({"availability": "instock"}, ("published", None, "InStock"), None),
        ({"availability": "Out of stock", "inventoryLevel": 0}, ("published", None, "OutOfStock"), 0),
        (
            {"availability": "https://schema.org/PreOrder", "inventoryLevel": {"value": 12}},
            ("published", None, "PreOrder"),
            12,
        ),
    ],
)
def test_an_offer_s_availability_and_inventory_level_publish_as_two_fields(
    offer: dict[str, Any], availability: tuple[str, None, JsonValue], stock: int | None
) -> None:
    fields = _fields(offer)

    assert fields["availability"] == availability
    published = ("published", None, stock)
    assert fields["stock_quantity"] == (published if stock is not None else ("missing", "no_candidates", None))


@pytest.mark.parametrize("written", ["Not in stock", "Available", "In stock soon"])
def test_availability_text_that_qualifies_or_negates_a_member_never_publishes_one(written: str) -> None:
    assert _fields({"availability": written})["availability"] == ("missing", "invalid", None)


def test_an_inventory_level_with_another_unit_is_no_stock_quantity() -> None:
    fields = _fields({"availability": "InStock", "inventoryLevel": {"value": 2.5, "unitCode": "KGM"}})

    assert fields["stock_quantity"] == ("missing", "invalid", None)
