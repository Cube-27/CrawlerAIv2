"""INV-38 over generated URL sets (SPEC-13 §4.6): a detail page's price publishes only when every
variant's Offer agrees, whatever variant the request URL names; a URL never selects a default variant."""

import json
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.resolve.intent import primary_types, select_target
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
    PageFacts,
    Resolver,
    Unpublished,
)
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
GROUP_URL = "https://shop.example.test/p/1"
URLS = (GROUP_URL, *(f"{GROUP_URL}?variant={i}" for i in range(1, 4)))
PRICES = ("10.00", "12.00")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", required=True, schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)


def _price(variants: list[tuple[str, str]], request_url: str) -> Chosen | Unpublished:
    group = {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Synthetic Widget",
        "url": GROUP_URL,
        "hasVariant": [
            {"@type": "Product", "url": url, "offers": {"@type": "Offer", "price": p, "priceCurrency": "EUR"}}
            for url, p in variants
        ],
    }
    page = ParsedPage(f'<html><head><script type="application/ld+json">{json.dumps(group)}</script></head></html>')
    ctx = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=request_url, page_url=request_url)
    collected = JsonLdCollector(VOCABULARY).collect(page, SCHEMA, ctx)
    graph = EntityGraph.of(collected.entities, VOCABULARY)
    target = select_target(request_url, request_url, GROUP_URL, graph, primary_types(SCHEMA, VOCABULARY))
    assert isinstance(target, Entity)
    orders: Orders = dict.fromkeys(PRECEDENCE_TYPES, ("jsonld",))
    resolver = Resolver(graph, target, PageFacts.of(request_url, lambda _: False), orders, variant_fill=True)
    return resolver.prefer(SCHEMA, collected.candidates)["price"]


@given(
    st.lists(st.tuples(st.sampled_from(URLS), st.sampled_from(PRICES)), min_size=1, max_size=4),
    st.sampled_from(URLS),
)
def test_the_price_publishes_only_when_every_variant_agrees(variants: list[tuple[str, str]], request_url: str) -> None:
    prices = {p for _, p in variants}
    result = _price(variants, request_url)

    if len(prices) == 1:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized.value == {"amount": prices.pop(), "currency": "EUR"}  # type: ignore[union-attr]
    else:
        assert isinstance(result, Unpublished)
        assert (result.status, result.reason) == ("conflict", "offers_disagree")
