"""Row-mapped fields on a detail page (SPEC-13 §4.3 to §4.5, INV-33 to INV-35): each structured-data shape of a
variant set publishes one row per variant, matched by key and never by position, with per-sub-field outcomes. Pages
are synthetic (`example.test`) and the schema is preset `commerce_detail` version 3 (C3, C9)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import JsonValue

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.learning import learnable
from crawlerai.core.ids import uuid7
from crawlerai.db.models import EvalRunId, SchemaId, SourceKind
from crawlerai.resolve import pipeline
from crawlerai.resolve.evidence import Bucket, Calibration
from crawlerai.resolve.pipeline import EngineData, extract_page
from crawlerai.resolve.preference import PRECEDENCE_TYPES
from crawlerai.resolve.records import FieldMeta
from crawlerai.resolve.types import FieldOutcome
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
DATA = EngineData(vocabulary=VOCABULARY, orders={t: ORDER for t in PRECEDENCE_TYPES}, calibration=None)
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


def _variants(*nodes: dict[str, Any], body: str = "", data: EngineData = DATA) -> FieldOutcome:
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
        extract_page(CaptureBundle(manifest=manifest, body=raw, network=()), SCHEMA, None, None, data=data)
    )
    assert result.entity is not None
    return result.entity["variants"]


def _rows(outcome: FieldOutcome) -> list[dict[str, JsonValue]]:
    assert outcome.status == "published", (outcome.status, outcome.reason)
    assert isinstance(outcome.value, list)
    return [row for row in outcome.value if isinstance(row, dict)]


def _skus(outcome: FieldOutcome) -> list[JsonValue]:
    return [row["sku"] for row in _rows(outcome)]


def _sku(value: str) -> JsonValue:
    return {"scheme": "sku", "value": value}


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


def test_a_product_with_one_offer_per_variant_has_a_row_per_offer() -> None:
    product: dict[str, Any] = {"@type": "Product", "name": "Synthetic Widget", "url": PAGE_URL}
    product["offers"] = [_offer("10.00", sku="W-11"), _offer("12.00", sku="W-12")]

    assert _skus(_variants(product)) == [_sku("W-11"), _sku("W-12")]


def test_offers_under_an_aggregate_offer_are_rows_and_the_aggregate_is_not() -> None:
    aggregate = {"@type": "AggregateOffer", "lowPrice": "10.00", "priceCurrency": "EUR"}
    product: dict[str, Any] = {"@type": "Product", "name": "Synthetic Widget", "url": PAGE_URL}

    rows = _variants(product | {"offers": aggregate | {"offers": [_offer("10.00", sku="W-11")]}})
    alone = _variants(product | {"offers": aggregate | {"sku": "W-1"}})

    assert _skus(rows) == [_sku("W-11")]
    assert (alone.status, alone.reason) == ("missing", "no_rows")


def test_offers_that_carry_only_a_url_are_one_row_each() -> None:
    product: dict[str, Any] = {"@type": "Product", "name": "Synthetic Widget", "url": PAGE_URL}
    product["offers"] = [_offer("10.00", url=f"{PAGE_URL}?v=11"), _offer("12.00", url=f"{PAGE_URL}?v=12")]

    assert [row["url"] for row in _rows(_variants(product))] == [f"{PAGE_URL}?v=11", f"{PAGE_URL}?v=12"]


def test_a_group_s_direct_offers_and_its_variants_match_by_key() -> None:
    group = _group(_variant("W-11", "10.00", color="Red"), offers=[_offer("10.00", sku="W-11")])

    rows = _rows(_variants(group))

    assert rows == [
        {
            "sku": _sku("W-11"),
            "price": {"amount": "10.00", "currency": "EUR"},
            "availability": "InStock",
            "color": "Red",
        }
    ]


def test_variants_that_repeat_the_group_url_have_no_url_key() -> None:
    outcome = _variants(_group(_variant("W-11", "10.00", url=PAGE_URL), {"@type": "Product", "url": PAGE_URL}))

    assert _skus(outcome) == [_sku("W-11")]
    assert outcome.dropped is not None
    assert [row.reason for row in outcome.dropped] == ["no_row_key"]


def test_a_group_url_that_offers_and_variants_repeat_is_no_key() -> None:
    # The group's own URL, not the page's, repeated by every direct Offer and every variant names the group (§4.4).
    group_url = "https://shop.example.test/g/1"
    first = _variant("W-11", "10.00", url=group_url)
    second = _variant("W-12", "12.00", url=group_url)
    offers = [_offer("10.00", url=group_url), _offer("12.00", url=group_url)]

    outcome = _variants(_group(first, second, url=group_url, offers=offers))

    assert _skus(outcome) == [_sku("W-11"), _sku("W-12")]


def test_one_offer_s_url_that_repeats_the_target_url_stays_its_key() -> None:
    # One-Offer-per-variant: the default variant's Offer may carry the product's own URL; only that row holds it.
    product_url = "https://shop.example.test/g/1"
    product: dict[str, Any] = {"@type": "Product", "name": "Synthetic Widget", "url": product_url}
    product["offers"] = [_offer("10.00", url=product_url), _offer("12.00", url=f"{product_url}?v=12")]

    assert [row["url"] for row in _rows(_variants(product))] == [product_url, f"{product_url}?v=12"]


def test_rows_whose_key_sub_fields_disagree_do_not_publish() -> None:
    # INV-33: both rows say W-11, but name two GTINs: two variants joined, or one source wrong.
    first = _variant("W-11", "10.00", gtin="4006381333931")
    second = _variant("W-11", "10.00", gtin="9780306406157")

    outcome = _variants(_group(first, second))

    assert (outcome.status, outcome.reason) == ("missing", "row_key_conflict")


def test_rows_whose_key_sub_fields_are_all_below_tau_make_the_field_abstain() -> None:
    # §4.5: a key sub-field's row bucket (`list.<type>|<evidence>`) calibrated below τ drops each variant as
    # `key_unpublished`; when every variant went that way the field abstains, it is not missing.
    buckets = {"list.identifier|structured": Bucket(n=40, precision=0.5)}
    calibration = Calibration(eval_run_id=EvalRunId(uuid7()), git_sha="a" * 40, buckets=buckets)
    data = EngineData(VOCABULARY, DATA.orders, calibration)

    outcome = _variants(_group(_variant("W-11", "10.00"), _variant("W-12", "12.00")), data=data)

    assert (outcome.status, outcome.reason) == ("abstained", "below_tau")
    assert outcome.dropped is not None
    assert [row.reason for row in outcome.dropped] == ["key_unpublished", "key_unpublished"]


def test_a_row_s_price_comes_from_one_offer() -> None:
    # INV-35: two Offers in one row that disagree leave the row's price a conflict; the row still publishes its key.
    variant = {"@type": "Product", "sku": "W-11", "offers": [_offer("10.00"), _offer("11.00")]}

    outcome = _variants(_group(variant))

    assert outcome.items is not None
    price = outcome.items[0].fields["price"]
    assert (price.status, price.reason) == ("conflict", "offers_disagree")
    assert _skus(outcome) == [_sku("W-11")]


def test_the_group_s_own_values_are_in_no_row() -> None:
    outcome = _variants(_group(_variant("W-11", "10.00"), sku="W-1"))

    assert _skus(outcome) == [_sku("W-11")]
    assert [(c.raw, reason) for c, reason in outcome.rejected if c.field == "variants.sku"] == [("W-1", "not_in_row")]


def test_the_record_meta_holds_one_item_per_row_and_the_dropped_rows() -> None:
    meta = FieldMeta.of(_variants(_group(_variant("W-11", "10.00"), {"@type": "Product", "url": PAGE_URL})))

    dumped = meta.model_dump(mode="json")
    item = SCHEMA.fields["variants"].item
    assert item is not None
    assert [set(row["fields"]) for row in dumped["items"]] == [set(item.fields or {})]
    assert dumped["dropped"] == [{"locators": ["jsonld:0:$['hasVariant'][1]"], "reason": "no_row_key"}]
    plain = FieldMeta.of(_variants(_group()))
    assert "items" not in plain.model_dump(mode="json")


def test_role_c_is_never_asked_for_a_row_mapped_field() -> None:
    # SPEC-13 §4.9: a claim is one verbatim span, which cannot hold a row of typed sub-fields.
    fields = {name: _missing() for name in SCHEMA.fields}

    assert "variants" not in pipeline._gaps(SCHEMA, fields, frozenset())
    assert "title" in pipeline._gaps(SCHEMA, fields, frozenset())


def test_learning_gives_a_row_mapped_field_no_steps_and_says_why() -> None:
    schema, reasons = learnable(SCHEMA)

    assert reasons == {"variants": "row_field"}
    assert list(schema.fields) == [name for name in SCHEMA.fields if name != "variants"]
    assert (schema.name, schema.version) == (SCHEMA.name, SCHEMA.version)


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
