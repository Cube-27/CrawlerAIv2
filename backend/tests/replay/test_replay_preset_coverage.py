"""Optional `commerce_detail` fields replayed through `extract_page` on synthetic captures: each publishes what the
page's schema.org Product states, by its own `schema_org` path, and nothing the page does not state. A JSON-LD block
with raw control characters inside its strings is read, not lost (RFC 8259 §9). Pages are synthetic (`example.test`,
C3, C9)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
IMAGES = ["https://shop.example.test/img/1.jpg", "https://shop.example.test/img/2.jpg"]
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")

PRODUCT: dict[str, Any] = {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Synthetic Widget",
    "url": PAGE_URL,
    "sku": "W-1",
    "mpn": "MPN-77",
    "productID": "isbn-less-42",
    "description": "First line.\nSecond line.",
    "color": "Teal",
    "material": "Cotton",
    "image": IMAGES,
    "itemCondition": "https://schema.org/RefurbishedCondition",
    "audience": {"@type": "PeopleAudience", "suggestedGender": "unisex"},
    "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.5", "reviewCount": 128},
    "offers": {"@type": "Offer", "price": "10.00", "priceCurrency": "EUR", "availability": "InStock"},
}


def _extract(block: str) -> ExtractionResult:
    raw = f'<html><head><script type="application/ld+json">{block}</script></head></html>'.encode()
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
    return asyncio.run(
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), SCHEMA, None, None, data=DATA)
    )


def _published(result: ExtractionResult) -> dict[str, JsonValue]:
    assert result.entity is not None
    return {name: outcome.value for name, outcome in result.entity.items() if outcome.status == "published"}


def test_each_optional_product_property_the_page_states_publishes_by_its_path() -> None:
    published = _published(_extract(json.dumps(PRODUCT)))

    assert {name: published.get(name) for name in ("description", "color", "material", "gender")} == {
        "description": "First line.\nSecond line.",
        "color": "Teal",
        "material": "Cotton",
        "gender": "unisex",
    }
    assert published.get("additional_images") == IMAGES
    assert published.get("condition") == "RefurbishedCondition"
    assert published.get("product_id") == {"scheme": "custom", "value": "isbn-less-42"}
    assert published.get("mpn") == {"scheme": "mpn", "value": "MPN-77"}
    assert (published.get("rating"), published.get("review_count")) == ("4.5", 128)


def test_a_property_the_page_does_not_state_is_missing_never_derived() -> None:
    bare = {k: v for k, v in PRODUCT.items() if k not in ("aggregateRating", "color", "description", "image")}
    result = _extract(json.dumps(bare))

    assert result.entity is not None
    for name in ("rating", "review_count", "color", "description", "additional_images"):
        assert (result.entity[name].status, result.entity[name].reason) == ("missing", "no_candidates")


def test_a_block_with_a_raw_newline_inside_a_string_still_publishes_its_fields() -> None:
    # json.dumps escapes the newline as `\n`; the page writes it raw, which RFC 8259 §7 does not allow in a string.
    block = json.dumps(PRODUCT).replace("\\n", "\n")
    published = _published(_extract(block))

    assert published.get("price") == {"amount": "10.00", "currency": "EUR"}
    assert published.get("description") == "First line.\nSecond line."


def test_variant_rows_carry_the_id_size_colour_and_gtin_each_variant_states() -> None:
    group = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Synthetic Shirt",
        "url": PAGE_URL,
        "hasVariant": [
            {
                "@type": "Product",
                "sku": f"S-{size}",
                "productID": f"v{index}",
                "gtin": gtin,
                "size": size,
                "color": "Teal",
                "offers": {"@type": "Offer", "price": "20.00", "priceCurrency": "EUR", "availability": "InStock"},
            }
            for index, (size, gtin) in enumerate([("S", "4006381333931"), ("M", "4006381333948")])
        ],
    }
    published = _published(_extract(json.dumps(group)))

    rows = published.get("variants")
    assert isinstance(rows, list)
    picked = [{k: row.get(k) for k in ("variant_id", "size", "color", "gtin")} for row in rows if isinstance(row, dict)]
    assert picked == [
        {
            "variant_id": {"scheme": "custom", "value": "v0"},
            "size": "S",
            "color": "Teal",
            "gtin": {"scheme": "gtin", "value": "4006381333931"},
        },
        {
            "variant_id": {"scheme": "custom", "value": "v1"},
            "size": "M",
            "color": "Teal",
            "gtin": {"scheme": "gtin", "value": "4006381333948"},
        },
    ]
