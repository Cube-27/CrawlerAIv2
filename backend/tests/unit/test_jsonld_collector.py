"""The JSON-LD collector (SPEC-05 §4.5): every `application/ld+json` block, `@graph` expanded, `@id` references
resolved within the page, schema.org nodes as entities, and a candidate for each `schema_org` path."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA_ORG = "https://schema.org"


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
        page_kind="detail",
        fields=fields,
    )


def _text(path: str) -> FieldSpec:
    return FieldSpec(type=FieldType.TEXT, description="d", schema_org=path)


SCHEMA = _schema(
    title=_text("Product.name"),
    brand=_text("Product.brand.name"),
    price=FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    images=FieldSpec(
        type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.IMAGE_URL), schema_org="Product.image"
    ),
    note=FieldSpec(type=FieldType.TEXT, description="d"),  # no schema_org path: no JSON-LD candidates
)


def _page(*blocks: Any) -> ParsedPage:
    scripts = "".join(
        f'<script type="application/ld+json">{b if isinstance(b, str) else json.dumps(b)}</script>' for b in blocks
    )
    return ParsedPage(f"<html><head>{scripts}</head><body></body></html>")


def _collect(*blocks: Any, schema: SchemaDef = SCHEMA) -> CollectResult:
    return JsonLdCollector(VOCABULARY).collect(_page(*blocks), schema, CTX)


def _candidate(field: str, entity_id: str, raw: Any, normalized: Any, locator: str) -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind="jsonld",
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=True,
    )


def test_a_product_with_a_nested_offer() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@type": "Product",
            "name": "Widget 9",
            "url": PAGE_URL,
            "brand": {"@type": "Brand", "name": "Acme 7"},
            "image": ["https://shop.example.test/a.png", "/b.png"],
            "offers": {"@type": "Offer", "price": "10.50", "priceCurrency": "EUR"},
        }
    )
    product = Entity(id="jsonld:0:$", kind="Product", urls=(PAGE_URL,), parent=None)
    assert result.entities == (
        product,
        Entity(id="jsonld:0:$['brand']", kind="Brand", urls=(), parent=product.id, via="brand"),
        Entity(id="jsonld:0:$['offers']", kind="Offer", urls=(), parent=product.id, via="offers"),
    )
    assert result.candidates == (
        _candidate("title", product.id, "Widget 9", Ok("Widget 9"), "jsonld:0:$['name']"),
        _candidate("brand", product.id, "Acme 7", Ok("Acme 7"), "jsonld:0:$['brand']['name']"),
        _candidate(
            "price",
            "jsonld:0:$['offers']",
            {"price": "10.50", "priceCurrency": "EUR"},
            Ok({"amount": "10.50", "currency": "EUR"}),
            "jsonld:0:$['offers']['price']",
        ),
        _candidate(
            "images",
            product.id,
            ["https://shop.example.test/a.png", "/b.png"],
            Ok(["https://shop.example.test/a.png", "https://shop.example.test/b.png"]),
            "jsonld:0:$['image'][0]",
        ),
    )
    assert result.diagnostics == ()


def test_graph_nodes_and_id_references() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@graph": [
                {"@type": "Product", "@id": "#product", "name": "Widget 9", "offers": {"@id": "#offer"}},
                {"@type": "Offer", "@id": "#offer", "price": 5, "priceCurrency": "USD"},
            ],
        }
    )
    product_id, offer_id = "jsonld:0:$['@graph'][0]", "jsonld:0:$['@graph'][1]"
    assert [(e.id, e.kind, e.parent, e.via) for e in result.entities] == [
        (product_id, "Product", None, None),
        (offer_id, "Offer", product_id, "offers"),
    ]
    assert [(c.field, c.entity_id, c.locator) for c in result.candidates] == [
        ("title", product_id, f"{product_id}['name']"),
        ("price", offer_id, f"{offer_id}['price']"),
    ]


def test_references_resolve_across_blocks() -> None:
    result = _collect(
        {"@context": SCHEMA_ORG, "@type": "Product", "@id": "#product", "offers": {"@id": "#offer"}},
        "not json",
        {"@context": SCHEMA_ORG, "@type": "Offer", "@id": "#offer", "price": "5", "priceCurrency": "USD"},
    )
    assert [(e.id, e.parent, e.via) for e in result.entities] == [
        ("jsonld:0:$", None, None),
        ("jsonld:2:$", "jsonld:0:$", "offers"),
    ]
    assert [(c.field, c.entity_id, c.locator) for c in result.candidates] == [
        ("price", "jsonld:2:$", "jsonld:2:$['price']")
    ]


@pytest.mark.parametrize("block", ['{"price": NaN}', "[" * 100_000, ""], ids=["nan", "deep", "empty"])
def test_text_that_is_not_json_is_a_diagnostic(block: str) -> None:
    result = _collect(block)
    assert (result.entities, result.candidates) == ((), ())
    assert [d.split(" (")[0] for d in result.diagnostics] == ["jsonld:0: invalid JSON"]


def test_deep_nesting_is_walked_without_the_call_stack() -> None:
    depth = 400
    block = "[" * depth + json.dumps({"@context": SCHEMA_ORG, "@type": "Product", "name": "Widget 9"}) + "]" * depth
    result = _collect(block)
    assert [(c.raw, c.locator) for c in result.candidates] == [("Widget 9", "jsonld:0:$" + "[0]" * depth + "['name']")]


def test_a_value_the_candidate_model_refuses_is_skipped_with_a_diagnostic() -> None:
    deep: Any = "x"
    for _ in range(300):
        deep = {"a": deep}
    result = _collect(
        {"@context": SCHEMA_ORG, "@type": "Product", "name": deep},
        {"@context": SCHEMA_ORG, "@type": "Product", "name": "Widget 9"},
    )
    assert [(c.raw, c.locator) for c in result.candidates] == [("Widget 9", "jsonld:1:$['name']")]
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].startswith("value at jsonld:0:$['name'] skipped")


def test_an_invalid_block_is_skipped_with_a_diagnostic() -> None:
    result = _collect('{"@type": "Product", "name": "x",}', {"@context": SCHEMA_ORG, "@type": "Product", "name": "y"})
    assert [(c.locator, c.raw) for c in result.candidates] == [("jsonld:1:$['name']", "y")]
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].startswith("jsonld:0: invalid JSON")


@pytest.mark.parametrize(
    "block",
    [
        {"@context": "http://schema.org", "@type": "Product", "name": "Widget 9"},
        {"@context": "https://schema.org/", "@type": "Product", "name": "Widget 9"},
        {"@context": {"@vocab": "http://schema.org/"}, "@type": "Product", "name": "Widget 9"},
        {"@context": [{"@language": "en"}, SCHEMA_ORG], "@type": "Product", "name": "Widget 9"},
        {"@type": "http://schema.org/Product", "http://schema.org/name": "Widget 9"},
        {"@context": SCHEMA_ORG, "@type": "Product", "name": {"@value": "Widget 9", "@language": "en"}},
        [{"@context": SCHEMA_ORG, "@type": "Product", "name": "Widget 9"}],
    ],
)
def test_schema_org_spellings(block: Any) -> None:
    result = _collect(block)
    assert [e.kind for e in result.entities] == ["Product"]
    assert [(c.field, c.raw) for c in result.candidates] == [("title", "Widget 9")]


@pytest.mark.parametrize(
    "block",
    [
        {"@type": "Product", "name": "Widget 9"},  # no context: `Product` is not a schema.org IRI
        {"@context": "https://vocab.example.test/", "@type": "Product", "name": "Widget 9"},
        {"@context": SCHEMA_ORG, "@type": "Widget", "name": "Widget 9"},  # not a schema.org type
    ],
)
def test_nodes_outside_schema_org_are_not_entities(block: Any) -> None:
    result = _collect(block)
    assert result.entities == ()
    assert result.candidates == ()


def test_a_null_context_ends_the_schema_org_scope() -> None:
    result = _collect(
        {"@context": SCHEMA_ORG, "@type": "Product", "isRelatedTo": {"@context": None, "@type": "Product"}}
    )
    assert [e.id for e in result.entities] == ["jsonld:0:$"]


def test_a_subtype_matches_its_supertype_s_paths() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@type": ["Thing", "IndividualProduct"],
            "name": "Widget 9",
            "offers": [
                {"@type": "AggregateOffer", "price": "5", "priceCurrency": "USD"},
                {"@type": "Offer", "price": "6", "priceCurrency": "USD"},
            ],
        }
    )
    assert [e.kind for e in result.entities] == ["IndividualProduct", "AggregateOffer", "Offer"]
    assert [(c.field, c.entity_id) for c in result.candidates] == [
        ("title", "jsonld:0:$"),
        ("price", "jsonld:0:$['offers'][0]"),
        ("price", "jsonld:0:$['offers'][1]"),
    ]


def test_an_unknown_type_between_entities_is_skipped_for_the_parent() -> None:
    result = _collect(
        {"@context": SCHEMA_ORG, "@type": "Product", "x": {"@type": "Widget", "offers": {"@type": "Offer"}}}
    )
    # The parent's property that holds the Offer is `x`, the one on the Product.
    assert [(e.id, e.parent, e.via) for e in result.entities] == [
        ("jsonld:0:$", None, None),
        ("jsonld:0:$['x']['offers']", "jsonld:0:$", "x"),
    ]


def test_via_names_the_schema_org_property_holding_the_entity() -> None:
    product = SCHEMA_ORG + "/Product"
    result = _collect(
        {"@context": SCHEMA_ORG, "@type": "Product", "isSimilarTo": {"@type": "Product"}},
        {"@type": product, SCHEMA_ORG + "/isRelatedTo": [{"@type": product}], "related": {"@type": product}},
    )
    # Without a schema.org context, only a full IRI names a schema.org property (JSON-LD 1.1 §4.1.2).
    assert [(e.id, e.via) for e in result.entities] == [
        ("jsonld:0:$", None),
        ("jsonld:0:$['isSimilarTo']", "isSimilarTo"),
        ("jsonld:1:$", None),
        ("jsonld:1:$['https://schema.org/isRelatedTo'][0]", "isRelatedTo"),
        ("jsonld:1:$['related']", None),
    ]


def test_entity_urls_are_canonical_and_name_pages() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@type": "Product",
            "@id": "HTTPS://Shop.Example.test/p/2",
            "url": "/p/1?x=1#reviews",
            "mainEntityOfPage": {"@type": "WebPage", "@id": "https://shop.example.test/p/3"},
            "offers": [{"@type": "Offer", "url": "https://shop.example.test/p/4"}, {"@id": "#offer"}],
            "sameAs": "https://shop.example.test/p/5",
        },
        {"@context": SCHEMA_ORG, "@type": "Offer", "@id": "#offer", "url": "https://shop.example.test/p/6"},
        {"@context": SCHEMA_ORG, "@type": "Product", "@id": "#second", "mainEntityOfPage": PAGE_URL},
    )
    by_id = {e.id: e.urls for e in result.entities}
    assert by_id["jsonld:0:$"] == (
        "https://shop.example.test/p/1?x=1",
        "https://shop.example.test/p/2",
        "https://shop.example.test/p/3",
        "https://shop.example.test/p/4",
        "https://shop.example.test/p/6",
    )
    # An `@id` with a fragment names a part of the document, not a page (RFC 3986 §3.5).
    assert by_id["jsonld:2:$"] == (PAGE_URL,)


def test_an_unresolved_reference_gives_no_value() -> None:
    result = _collect({"@context": SCHEMA_ORG, "@type": "Product", "brand": {"@id": "#nowhere"}})
    assert result.candidates == ()


def test_reference_cycles_end() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@graph": [
                {"@type": "Product", "@id": "#a", "isRelatedTo": {"@id": "#b"}, "name": "A"},
                {"@type": "Product", "@id": "#b", "isRelatedTo": {"@id": "#a"}, "name": "B"},
            ],
        }
    )
    assert [(e.id, e.parent, e.via) for e in result.entities] == [
        ("jsonld:0:$['@graph'][0]", "jsonld:0:$['@graph'][1]", "isRelatedTo"),
        ("jsonld:0:$['@graph'][1]", None, None),
    ]


def test_a_node_referenced_from_two_entities_has_no_parent() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@graph": [
                {"@type": "Product", "offers": {"@id": "#o"}},
                {"@type": "Product", "offers": {"@id": "#o"}},
                {"@type": "Offer", "@id": "#o"},
            ],
        }
    )
    assert [(e.parent, e.via) for e in result.entities] == [(None, None)] * 3


def test_null_and_nested_arrays_are_no_values() -> None:
    result = _collect({"@context": SCHEMA_ORG, "@type": "Product", "name": [None, ["x"], {"@value": None}, "Widget 9"]})
    assert [(c.raw, c.locator) for c in result.candidates] == [("Widget 9", "jsonld:0:$['name'][3]")]


def test_values_that_do_not_normalize_are_still_candidates() -> None:
    result = _collect({"@context": SCHEMA_ORG, "@type": "Product", "name": {"@type": "Thing"}})
    assert [(c.field, c.normalized) for c in result.candidates] == [("title", Invalid("not_a_string"))]


def test_member_names_are_escaped_as_normalized_paths() -> None:
    # RFC 9535 §2.7: a normalized path writes member names in single quotes, escaping `'` and `\`.
    result = _collect({"a'b\\": {"@context": SCHEMA_ORG, "@type": "Product"}})
    assert [e.id for e in result.entities] == ["jsonld:0:$['a\\'b\\\\']"]


def test_a_node_referenced_under_two_properties_of_its_parent_names_neither() -> None:
    result = _collect(
        {
            "@context": SCHEMA_ORG,
            "@graph": [
                {"@type": "Product", "isRelatedTo": {"@id": "#p"}, "isSimilarTo": {"@id": "#p"}},
                {"@type": "Product", "@id": "#p", "offers": {"@id": "#p"}},
            ],
        }
    )
    assert [(e.parent, e.via) for e in result.entities] == [(None, None), ("jsonld:0:$['@graph'][0]", None)]
