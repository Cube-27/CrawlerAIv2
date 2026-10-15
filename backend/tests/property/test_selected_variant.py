"""INV-36 over generated URL sets (SPEC-13 §4.6): a detail page's price comes from a single variant only when the page
URLs name exactly that variant by its own URL; otherwise it publishes only when every variant's Offer agrees."""

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
from crawlerai.resolve.intent import primary_types, select_target, select_variant
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.preference import (
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
    PageFacts,
    Resolver,
    Unpublished,
    Variants,
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
    version=1,
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
    variant_rules = Variants(select_variant(request_url, request_url, GROUP_URL, graph, target))
    orders: Orders = {t: ("jsonld",) for t in PRECEDENCE_TYPES}
    resolver = Resolver(graph, target, PageFacts.of(request_url, lambda _: False), orders, variants=variant_rules)
    return resolver.prefer(SCHEMA, collected.candidates)["price"]


@given(
    st.lists(st.tuples(st.sampled_from(URLS), st.sampled_from(PRICES)), min_size=1, max_size=4),
    st.sampled_from(URLS),
)
def test_the_price_comes_from_one_variant_only_when_the_urls_name_exactly_that_one(
    variants: list[tuple[str, str]], request_url: str
) -> None:
    named = [p for url, p in variants if url in (request_url, GROUP_URL)]
    result = _price(variants, request_url)

    if len(named) == 1:
        expected: str | None = named[0]
    else:
        expected = PRICES[0] if all(p == PRICES[0] for _, p in variants) else None
        expected = PRICES[1] if all(p == PRICES[1] for _, p in variants) else expected
    if expected is None:
        assert isinstance(result, Unpublished)
        assert result.reason == "offers_disagree"
    else:
        assert isinstance(result, Chosen)
        assert result.candidate.normalized.value == {"amount": expected, "currency": "EUR"}  # type: ignore[union-attr]
