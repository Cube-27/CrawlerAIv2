"""The selected variant and variant fill (SPEC-13 §4.6, INV-36): a detail page's Offer fields come from one variant
only when a page URL names exactly that variant by its own URL; otherwise every Offer must agree. An identifier the
group states nothing for takes its variants' value only from the selected variant, or when every variant agrees."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crawlerai.collect.base import Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId, SourceKind
from crawlerai.normalize.base import Context
from crawlerai.resolve.intent import primary_types, select_target, select_variant
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    PageFacts,
    Preference,
    Resolver,
    Unpublished,
    Variants,
)
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
ORDER: tuple[SourceKind, ...] = ("adapter", "api", "jsonld", "microdata", "og", "config", "llm")
GROUP_URL = "https://shop.example.test/p/1"
VARIANT_URLS = ("https://shop.example.test/p/1?variant=11", "https://shop.example.test/p/1?variant=12")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
        "sku": FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku"),
        "gtin": FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.gtin"),
    },
)


def _variant(url: str, price: str, **values: Any) -> dict[str, Any]:
    offer = {"@type": "Offer", "price": price, "priceCurrency": "EUR", "url": url}
    return {"@type": "Product", "name": "Synthetic Widget", "url": url, "offers": offer} | values


def _group(*variants: dict[str, Any], **values: Any) -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Synthetic Widget",
        "url": GROUP_URL,
        "hasVariant": list(variants),
    } | values


def _resolve(document: dict[str, Any], request_url: str = GROUP_URL, *, rules: bool = True) -> dict[str, Preference]:
    page = ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(document)}</script></head></html>')
    ctx = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=request_url, page_url=request_url)
    collected = JsonLdCollector(VOCABULARY).collect(page, SCHEMA, ctx)
    graph = EntityGraph.of(collected.entities, VOCABULARY)
    target = select_target(request_url, request_url, GROUP_URL, graph, primary_types(SCHEMA, VOCABULARY))
    assert isinstance(target, Entity)
    variants = Variants(select_variant(request_url, request_url, GROUP_URL, graph, target)) if rules else None
    facts = PageFacts.of(request_url, lambda value: False)
    resolver = Resolver(graph, target, facts, dict.fromkeys(PRECEDENCE_TYPES, ORDER), variants=variants)
    return resolver.prefer(SCHEMA, collected.candidates)


def _value(preference: Preference) -> object:
    assert isinstance(preference, Chosen), preference
    return preference.candidate.normalized.value  # type: ignore[union-attr]


def _why(preference: Preference) -> tuple[str, str]:
    assert isinstance(preference, Unpublished), preference
    return preference.status, preference.reason


TWO_PRICES = _group(_variant(VARIANT_URLS[0], "10.00", sku="W-11"), _variant(VARIANT_URLS[1], "12.00", sku="W-12"))


def test_the_variant_the_request_url_names_is_the_one_source_of_the_offer_fields() -> None:
    result = _resolve(TWO_PRICES, VARIANT_URLS[1])

    assert _value(result["price"]) == {"amount": "12.00", "currency": "EUR"}
    assert [reason for _, reason in result["price"].rejected] == ["other_variant"]


def test_without_a_url_naming_one_variant_disagreeing_offers_stay_a_conflict() -> None:
    assert _resolve(TWO_PRICES)["price"] == _resolve(TWO_PRICES, rules=False)["price"]
    assert isinstance(conflict := _resolve(TWO_PRICES)["price"], Unpublished)
    assert (conflict.status, conflict.reason) == ("conflict", "offers_disagree")


def test_variants_that_repeat_the_group_url_select_none() -> None:
    repeated = _group(_variant(GROUP_URL, "10.00"), _variant(GROUP_URL, "12.00"))

    assert isinstance(conflict := _resolve(repeated)["price"], Unpublished)
    assert conflict.reason == "offers_disagree"


def test_an_aggregate_offer_is_no_variant_holder() -> None:
    aggregate = {"@type": "AggregateOffer", "lowPrice": "10.00", "priceCurrency": "EUR", "url": VARIANT_URLS[0]}
    document = _group(_variant(VARIANT_URLS[1], "12.00"), offers=aggregate)
    page = ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(document)}</script></head></html>')
    ctx = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=GROUP_URL)
    graph = EntityGraph.of(JsonLdCollector(VOCABULARY).collect(page, SCHEMA, ctx).entities, VOCABULARY)

    assert [h.kind for h in graph.holders(graph.entities["jsonld:0:$"])] == ["Product"]
    assert select_variant(VARIANT_URLS[0], VARIANT_URLS[0], None, graph, graph.entities["jsonld:0:$"]) is None


def test_a_selected_variant_s_aggregate_offer_gives_no_offer_field() -> None:
    # SPEC-13 §4.3: an AggregateOffer summarizes several offers and is no offer of one item, so it is none of the
    # selected variant's Offers (§4.6).
    aggregate = {"@type": "AggregateOffer", "price": "9.00", "lowPrice": "9.00", "priceCurrency": "EUR"}
    selected = {"@type": "Product", "name": "Synthetic Widget", "url": VARIANT_URLS[0], "offers": aggregate}

    result = _resolve(_group(selected, _variant(VARIANT_URLS[1], "12.00")), VARIANT_URLS[0])

    assert _why(result["price"]) == ("missing", "other_variant")
    assert {reason for _, reason in result["price"].rejected} == {"other_variant"}


def test_the_selected_variant_fills_an_identifier_the_group_does_not_state() -> None:
    result = _resolve(TWO_PRICES, VARIANT_URLS[0])

    assert _value(result["sku"]) == {"scheme": "sku", "value": "W-11"}
    assert _why(result["gtin"]) == ("missing", "no_candidates")  # no variant states one


def test_without_a_selection_an_identifier_fills_only_when_every_variant_agrees() -> None:
    agreeing = _group(
        _variant(VARIANT_URLS[0], "10.00", sku="W-11", gtin="4006381333931"),
        _variant(VARIANT_URLS[1], "12.00", sku="W-12", gtin="4006381333931"),
    )
    one_missing = _group(_variant(VARIANT_URLS[0], "10.00", gtin="4006381333931"), _variant(VARIANT_URLS[1], "12.00"))

    result = _resolve(agreeing)
    assert _value(result["gtin"]) == {"scheme": "gtin", "value": "4006381333931"}
    assert _why(result["sku"]) == ("missing", "not_owned")  # the variants disagree
    assert result["sku"] == _resolve(agreeing, rules=False)["sku"]
    assert _why(_resolve(one_missing)["gtin"]) == ("missing", "not_owned")


def test_variant_fill_never_replaces_the_group_s_own_value_or_fills_another_field() -> None:
    document = _group(_variant(VARIANT_URLS[0], "10.00", sku="W-11"), sku="W-1")
    nameless = _group(_variant(VARIANT_URLS[0], "10.00"))
    del nameless["name"]

    assert _value(_resolve(document, VARIANT_URLS[0])["sku"]) == {"scheme": "sku", "value": "W-1"}
    assert _why(_resolve(nameless, VARIANT_URLS[0])["title"]) == ("missing", "not_owned")
