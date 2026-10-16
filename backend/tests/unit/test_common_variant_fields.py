"""Common variant fields (SPEC-13 §4.6, INV-36 as amended): a multi-variant product's top-level Offer fields publish
only when every Offer agrees, whatever variant a page URL names; no variant is a default. An identifier the group
states nothing for takes its variants' value only when every variant states it alike."""

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
from crawlerai.resolve.intent import primary_types, select_target
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    PageFacts,
    Preference,
    Resolver,
    Unpublished,
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


def _resolve(document: dict[str, Any], request_url: str = GROUP_URL, *, fill: bool = True) -> dict[str, Preference]:
    page = ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(document)}</script></head></html>')
    ctx = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=request_url, page_url=request_url)
    collected = JsonLdCollector(VOCABULARY).collect(page, SCHEMA, ctx)
    graph = EntityGraph.of(collected.entities, VOCABULARY)
    target = select_target(request_url, request_url, GROUP_URL, graph, primary_types(SCHEMA, VOCABULARY))
    assert isinstance(target, Entity)
    facts = PageFacts.of(request_url, lambda value: False)
    resolver = Resolver(graph, target, facts, dict.fromkeys(PRECEDENCE_TYPES, ORDER), variant_fill=fill)
    return resolver.prefer(SCHEMA, collected.candidates)


def _value(preference: Preference) -> object:
    assert isinstance(preference, Chosen), preference
    return preference.candidate.normalized.value  # type: ignore[union-attr]


def _why(preference: Preference) -> tuple[str, str]:
    assert isinstance(preference, Unpublished), preference
    return preference.status, preference.reason


TWO_PRICES = _group(_variant(VARIANT_URLS[0], "10.00", sku="W-11"), _variant(VARIANT_URLS[1], "12.00", sku="W-12"))


def test_a_variant_the_request_url_names_is_no_default_for_the_offer_fields() -> None:
    result = _resolve(TWO_PRICES, VARIANT_URLS[1])

    assert _why(result["price"]) == ("conflict", "offers_disagree")
    assert [reason for _, reason in result["price"].rejected] == ["offers_disagree", "offers_disagree"]
    assert result["price"] == _resolve(TWO_PRICES)["price"]


def test_a_price_every_variant_states_alike_is_common_and_publishes() -> None:
    same = _group(_variant(VARIANT_URLS[0], "10.00"), _variant(VARIANT_URLS[1], "10.00"))

    assert _value(_resolve(same, VARIANT_URLS[0])["price"]) == {"amount": "10.00", "currency": "EUR"}


def test_a_single_variant_publishes_its_offer_and_identifier_at_the_top_level() -> None:
    result = _resolve(_group(_variant(VARIANT_URLS[0], "10.00", sku="W-11")))

    assert _value(result["price"]) == {"amount": "10.00", "currency": "EUR"}
    assert _value(result["sku"]) == {"scheme": "sku", "value": "W-11"}


def test_an_identifier_that_varies_stays_out_of_the_top_level_even_when_the_url_names_a_variant() -> None:
    result = _resolve(TWO_PRICES, VARIANT_URLS[0])

    assert _why(result["sku"]) == ("missing", "not_owned")
    assert _why(result["gtin"]) == ("missing", "no_candidates")  # no variant states one


def test_an_identifier_fills_only_when_every_variant_agrees() -> None:
    agreeing = _group(
        _variant(VARIANT_URLS[0], "10.00", sku="W-11", gtin="4006381333931"),
        _variant(VARIANT_URLS[1], "12.00", sku="W-12", gtin="4006381333931"),
    )
    one_missing = _group(_variant(VARIANT_URLS[0], "10.00", gtin="4006381333931"), _variant(VARIANT_URLS[1], "12.00"))

    result = _resolve(agreeing)
    assert _value(result["gtin"]) == {"scheme": "gtin", "value": "4006381333931"}
    assert _why(_resolve(agreeing, fill=False)["gtin"]) == ("missing", "not_owned")
    assert _why(result["sku"]) == ("missing", "not_owned")  # the variants disagree
    assert _why(_resolve(one_missing)["gtin"]) == ("missing", "not_owned")


def test_variant_fill_never_replaces_the_group_s_own_value_or_fills_another_field() -> None:
    document = _group(_variant(VARIANT_URLS[0], "10.00", sku="W-11"), _variant(VARIANT_URLS[1], "12.00"), sku="W-1")
    nameless = _group(_variant(VARIANT_URLS[0], "10.00"))
    del nameless["name"]

    assert _value(_resolve(document, VARIANT_URLS[0])["sku"]) == {"scheme": "sku", "value": "W-1"}
    assert _why(_resolve(nameless, VARIANT_URLS[0])["title"]) == ("missing", "not_owned")
