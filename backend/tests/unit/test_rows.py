"""Row-mapped fields on a detail page (variants spec, INV-33 to INV-35): each structured-data shape of a
variant set publishes one row per variant, matched by key and never by position, with per-sub-field outcomes. Pages
are synthetic (`example.test`) and the schema is preset `commerce_detail` (C3, C9)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.resolve import pipeline
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders=dict.fromkeys(PRECEDENCE_TYPES, ORDER), calibration=None)
PAGE_URL = "https://shop.example.test/p/1"
_PRESET = next(p for p in load_presets() if p.name == "commerce_detail")
SCHEMA = SchemaDef(**_PRESET.model_dump(), id=SchemaId(uuid7()), origin="preset", status="active")


def _offer(price: str, **values: Any) -> dict[str, Any]:
    return {"@type": "Offer", "price": price, "priceCurrency": "EUR", "availability": "https://schema.org/InStock"} | (
        values
    )


def _variant(sku: str, price: str, **values: Any) -> dict[str, Any]:
    return {"@type": "Product", "sku": sku, "offers": _offer(price)} | values


def _group(*variants: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {"@type": "ProductGroup", "name": "Synthetic Widget", "url": PAGE_URL, "hasVariant": list(variants)} | values


def _variants(
    *nodes: dict[str, Any], body: str = "", data: EngineData = DATA, schema: SchemaDef = SCHEMA
) -> FieldOutcome:
    blocks = "".join(
        f'<script type="application/ld+json">{json.dumps({"@context": "https://schema.org", **n})}</script>'
        for n in nodes
    )
    raw = f"<html><head>{blocks}</head><body>{body}</body></html>".encode()
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
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), schema, None, None, data=data)
    )
    assert result.entity is not None
    return result.entity["variants"]


def _rows(outcome: FieldOutcome) -> list[dict[str, JsonValue]]:
    assert outcome.status == "published", (outcome.status, outcome.reason)
    assert isinstance(outcome.value, list)
    return [row for row in outcome.value if isinstance(row, dict)]


def _sku(value: str) -> JsonValue:
    return value


def test_a_group_s_variants_with_offers_are_one_row_each() -> None:
    outcome = _variants(_group(_variant("W-11", "10.00", size="S"), _variant("W-12", "12.00", size="M")))

    assert _rows(outcome) == [
        {
            "sku": _sku("W-11"),
            "price": {"amount": "10.00", "currency": "EUR"},
            "availability": "InStock",
            "size": "S",
        },
        {
            "sku": _sku("W-12"),
            "price": {"amount": "12.00", "currency": "EUR"},
            "availability": "InStock",
            "size": "M",
        },
    ]
    # INV-34: every sub-field outcome of a published row carries status and reason; published ones carry provenance.
    assert outcome.items is not None
    assert len(outcome.items) == 2
    gtin = outcome.items[0].fields["gtin"]
    assert (gtin.status, gtin.reason) == ("missing", "no_candidates")
    price = outcome.items[0].fields["price"]
    assert (price.evidence, price.source_kind) == ("structured", "jsonld")
    assert outcome.locator == "jsonld:0:$['hasVariant'][0]"


def test_entries_of_one_list_with_other_skus_are_two_variants_whatever_barcode_they_repeat() -> None:
    # INV-33: one list names each of its items once, so two entries saying W-11 and W-12 are two variants (a sold-out
    # one as well), though both repeat the product's GTIN.
    first = _variant("W-11", "10.00", gtin="4006381333931")
    second = _variant("W-12", "10.00", gtin="4006381333931", offers=_offer("10.00", availability="OutOfStock"))

    assert [(row["sku"], row["availability"]) for row in _rows(_variants(_group(first, second)))] == [
        ("W-11", "InStock"),
        ("W-12", "OutOfStock"),
    ]


def test_role_c_is_never_asked_for_a_row_mapped_field() -> None:
    # variants spec: a claim is one verbatim span, which cannot hold a row of typed sub-fields.
    fields = {name: _missing() for name in SCHEMA.fields}

    assert "variants" not in pipeline._gaps(SCHEMA, fields, frozenset())
    assert "title" in pipeline._gaps(SCHEMA, fields, frozenset())


def _missing() -> FieldOutcome:
    return FieldOutcome(
        status="missing",
        reason="no_candidates",
        value=None,
        evidence=None,
        confidence=None,
        calibrated=False,
        source_kind=None,
        locator=None,
        derived_by=None,
        chosen=None,
        rejected=(),
    )
