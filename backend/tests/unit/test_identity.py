"""Identity (SPEC-05 §4.5, §4.6): the entities that state one item, from one collector or several, are one entity of
the entity graph, and a standalone variant joins the group whose `productGroupID` it names."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
SCHEMA_ORG = "https://schema.org"
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
    },
)


def _product(**properties: Any) -> dict[str, Any]:
    return {"@context": SCHEMA_ORG, "@type": "Product", **properties}


def _graph(*blocks: dict[str, Any], body: str = "") -> tuple[EntityGraph, tuple[Candidate, ...]]:
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    page = ParsedPage(f"<html><head>{scripts}</head><body>{body}</body></html>")
    results = [c.collect(page, SCHEMA, CTX) for c in (JsonLdCollector(VOCABULARY), MicrodataCollector(VOCABULARY))]
    graph = EntityGraph.of((e for r in results for e in r.entities), VOCABULARY, (PAGE_URL,))
    return graph, graph.adopt(c for r in results for c in r.candidates)


def _roots(graph: EntityGraph) -> list[str]:
    return [e.id for e in graph.entities.values() if e.parent is None and e.id != "page"]


def test_two_definitions_of_one_node_id_are_one_entity() -> None:
    # JSON-LD 1.1 (node map generation): node objects with the same @id, resolved against the document base
    # (RFC 3986 §5), describe one node; the second block's values, and its Offer, are that entity's.
    first = _product(**{"@id": "/p/1#product"}, url=PAGE_URL, name="Widget One")
    second = _product(
        **{"@id": "https://shop.example.test/p/1#product"},
        url="/p/1",
        name="Widget One",
        offers={"@type": "Offer", "price": "10.00", "priceCurrency": "EUR"},
    )

    graph, candidates = _graph(first, second)

    assert [(e.id, e.parent) for e in graph.entities.values()] == [
        ("jsonld:0:$", None),
        ("jsonld:1:$['offers']", "jsonld:0:$"),
        ("page", None),
    ]
    assert [(c.field, c.entity_id) for c in candidates] == [
        ("title", "jsonld:0:$"),
        ("title", "jsonld:0:$"),
        ("price", "jsonld:1:$['offers']"),
    ]
    assert graph.aliases == {"jsonld:1:$": "jsonld:0:$"}


def test_root_nodes_of_one_type_with_one_identifier_value_are_one_entity() -> None:
    # schema.org: `sku` is a sub-property of `identifier`, which identifies the item. The Offer's URL names a variant's
    # page, not another item, so it does not keep them apart.
    first = _product(**{"@id": PAGE_URL}, sku="W-1", name="Widget One")
    second = _product(
        sku="W-1",
        offers={"@type": "Offer", "url": f"{PAGE_URL}?variant=2", "price": "9.00", "priceCurrency": "EUR"},
    )

    graph, _ = _graph(first, second)

    assert _roots(graph) == ["jsonld:0:$"]
    assert graph.entities["jsonld:1:$['offers']"].parent == "jsonld:0:$"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (_product(sku="W-1", name="One"), _product(sku="W-2", name="Two")),  # different identifiers
        (_product(mpn="M-1", name="One"), _product(mpn="M-1", name="Two")),  # mpn is not an identifier property
        (_product(name="One"), _product(name="One")),  # nothing identifies either
        (
            _product(sku="W-1", url="https://shop.example.test/p/1"),
            _product(sku="W-1", url="https://shop.example.test/p/2"),
        ),  # one sku on two items whose URLs name different pages
        (_product(**{"@id": "_:b0"}, name="One"), _product(**{"@id": "_:b0"}, name="Two")),  # a blank node per block
        (
            _product(**{"@id": PAGE_URL}, name="One"),
            {"@context": SCHEMA_ORG, "@type": "Organization", "@id": PAGE_URL, "name": "Two"},
        ),  # another type
        (
            _product(url="https://shop.example.test/p/2"),
            _product(url="https://shop.example.test/p/2"),
        ),  # one collector stating a URL twice: an item URL alone joins only two collectors' entities
    ],
)
def test_root_nodes_without_a_shared_identity_stay_apart(first: dict[str, Any], second: dict[str, Any]) -> None:
    graph, _ = _graph(first, second)
    assert _roots(graph) == ["jsonld:0:$", "jsonld:1:$"]


def test_nested_nodes_are_not_merged_by_identifier() -> None:
    # An Offer nested in another node is that node's part, even when it repeats the holder's sku.
    group = _product(
        sku="W-1",
        offers=[
            {"@type": "Offer", "sku": "W-1", "price": "10.00", "priceCurrency": "EUR"},
            {"@type": "Offer", "sku": "W-1", "price": "12.00", "priceCurrency": "EUR"},
        ],
    )

    graph, _ = _graph(group)

    assert len(graph.entities) == 4
    assert graph.aliases == {}


def test_two_later_nodes_that_agree_join_although_the_first_stays_apart() -> None:
    # The first node's URL names another item than the two later ones, which agree with each other on sku and URL.
    first = _product(sku="W-1", url="https://shop.example.test/p/1")
    later = _product(sku="W-1", url="https://shop.example.test/p/2")

    graph, _ = _graph(first, later, later)

    assert _roots(graph) == ["jsonld:0:$", "jsonld:1:$"]
    assert graph.aliases == {"jsonld:2:$": "jsonld:1:$"}


def test_one_item_in_json_ld_and_microdata_is_one_entity() -> None:
    # The microdata item states the JSON-LD node's sku: one product, its Offer the merged entity's.
    body = (
        '<div itemscope itemtype="https://schema.org/Product"><meta itemprop="sku" content="W-1">'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<meta itemprop="price" content="10.00"><meta itemprop="priceCurrency" content="EUR"></div></div>'
    )

    graph, candidates = _graph(_product(sku="W-1", name="Widget One"), body=body)

    assert _roots(graph) == ["jsonld:0:$"]
    offer = "microdata:/html[1]/body[1]/div[1]/div[1]"
    assert graph.entities[offer].parent == "jsonld:0:$"
    assert {c.entity_id for c in candidates} == {"jsonld:0:$", offer}


def test_microdata_items_with_one_itemid_are_one_entity() -> None:
    # HTML Standard: `itemid` is the item's global identifier, so two items stating one are one item.
    item = '<div itemscope itemtype="https://schema.org/Product" itemid="/p/1#it"><b itemprop="name">W</b></div>'

    graph, _ = _graph(body=item * 2)

    assert _roots(graph) == ["microdata:/html[1]/body[1]/div[1]"]


def test_two_variants_sharing_a_sku_stay_two() -> None:
    # SPEC-13 INV-33: two sizes of one sku are two rows, so a group's two members never merge.
    group = {
        "@context": SCHEMA_ORG,
        "@type": "ProductGroup",
        "hasVariant": [{"@type": "Product", "sku": "W-1", "size": "S"}, {"@type": "Product", "sku": "W-1"}],
    }

    graph, _ = _graph(group)

    assert graph.aliases == {}


def test_a_standalone_product_stating_a_variant_s_sku_is_that_variant() -> None:
    # The group lists its variants by sku; the page's own Product states the second one's sku, so it is that variant
    # (schema.org `identifier`), and its values join the group's member.
    group = {
        "@context": SCHEMA_ORG,
        "@type": "ProductGroup",
        "hasVariant": [{"@type": "Product", "sku": "W-1"}, {"@type": "Product", "sku": "W-2"}],
    }
    product = _product(sku="W-2", name="Widget Two")

    graph, candidates = _graph(group, product)

    member = "jsonld:0:$['hasVariant'][1]"
    assert graph.aliases == {"jsonld:1:$": member}
    assert graph.entities[member].parent == "jsonld:0:$"
    assert [(c.field, c.entity_id) for c in candidates] == [("title", member)]


def test_a_standalone_product_at_a_variant_s_url_is_that_variant() -> None:
    group = {
        "@context": SCHEMA_ORG,
        "@type": "ProductGroup",
        "hasVariant": [{"@type": "Product", "url": "/p/1?v=1"}, {"@type": "Product", "url": "/p/1?v=2"}],
    }

    graph, _ = _graph(group, _product(url="/p/1?v=2", name="Widget Two"))

    assert graph.aliases == {"jsonld:1:$": "jsonld:0:$['hasVariant'][1]"}


def test_a_product_naming_its_group_s_id_is_its_variant() -> None:
    # schema.org `inProductGroupWithID`: "the productGroupID for a ProductGroup that this product isVariantOf".
    group = {"@context": SCHEMA_ORG, "@type": "ProductGroup", "productGroupID": "G-1", "name": "Widget"}
    product = _product(sku="W-2", inProductGroupWithID="G-1")
    other = _product(sku="W-3", inProductGroupWithID="G-9")

    graph, _ = _graph(group, product, other)

    assert (graph.entities["jsonld:1:$"].parent, graph.entities["jsonld:1:$"].via) == ("jsonld:0:$", "hasVariant")
    assert graph.entities["jsonld:2:$"].parent is None


# `isVariantOf` (D-1344): the inverse of `hasVariant`, so the group stands beside the page's Product.


def test_a_product_naming_its_group_by_is_variant_of_is_the_group_s_member_it_states() -> None:
    group = {
        "@type": "ProductGroup",
        "name": "Widget",
        "hasVariant": [{"@type": "Product", "sku": "W-1"}, {"@type": "Product", "sku": "W-2"}],
    }
    product = _product(sku="W-2", name="Widget Two", isVariantOf=group)

    graph, candidates = _graph(product)

    group_id, member = "jsonld:0:$['isVariantOf']", "jsonld:0:$['isVariantOf']['hasVariant'][1]"
    assert _roots(graph) == [group_id]
    assert graph.aliases == {"jsonld:0:$": member}
    assert (graph.entities[member].parent, graph.entities[member].via) == (group_id, "hasVariant")
    assert ("title", member) in [(c.field, c.entity_id) for c in candidates]


def test_a_product_naming_its_group_by_is_variant_of_and_no_member_becomes_one() -> None:
    product = _product(sku="W-2", isVariantOf={"@type": "ProductGroup", "name": "Widget"})

    graph, _ = _graph(product)

    group_id = "jsonld:0:$['isVariantOf']"
    assert _roots(graph) == [group_id]
    assert (graph.entities["jsonld:0:$"].parent, graph.entities["jsonld:0:$"].via) == (group_id, "hasVariant")


def test_products_naming_their_group_by_its_iri_are_its_variants() -> None:
    # One block lists the group and its variants as sibling nodes, each variant referencing the group by `@id`.
    group = {"@type": "ProductGroup", "@id": "/p/1#group", "name": "Widget"}
    variants = [{"@type": "Product", "sku": f"W-{n}", "isVariantOf": {"@id": "/p/1#group"}} for n in (1, 2)]

    graph, _ = _graph({"@context": SCHEMA_ORG, "@graph": [group, *variants]})

    group_id = "jsonld:0:$['@graph'][0]"
    assert _roots(graph) == [group_id]
    assert [(e.id, e.via) for e in graph.entities.values() if e.parent == group_id] == [
        ("jsonld:0:$['@graph'][1]", "hasVariant"),
        ("jsonld:0:$['@graph'][2]", "hasVariant"),
    ]


def test_is_variant_of_a_product_model_is_not_inverted() -> None:
    # schema.org `isVariantOf` also ranges over ProductModel, which has no `hasVariant` members.
    graph, _ = _graph(_product(sku="W-2", isVariantOf={"@type": "ProductModel", "name": "Widget"}))

    assert _roots(graph) == ["jsonld:0:$"]


def test_is_variant_of_on_a_nested_product_is_not_inverted() -> None:
    product = _product(sku="W-2", isVariantOf={"@type": "ProductGroup", "name": "Widget"})
    page = {"@context": SCHEMA_ORG, "@type": "WebPage", "mainEntity": product}

    graph, _ = _graph(page)

    group = graph.entities["jsonld:0:$['mainEntity']['isVariantOf']"]
    assert (group.parent, group.via) == ("jsonld:0:$['mainEntity']", "isVariantOf")


_KEYS = st.sampled_from([("sku", "A"), ("sku", "B"), ("gtin13", "4006381333931"), ("@id", "https://x.example/1")])


@given(st.lists(st.lists(_KEYS, max_size=2, unique=True), max_size=6))
def test_merged_entities_are_the_components_of_shared_identities(identities: list[list[tuple[str, str]]]) -> None:
    # Without URLs or groups, two root entities of one type are one item exactly when a chain of shared identity
    # values links them, whatever order the page states them in.
    entities = [
        Entity(id=f"jsonld:{i}:$", types=("Product",), urls=(), parent=None, identity=tuple(identity))
        for i, identity in enumerate(identities)
    ]
    graph = EntityGraph.of(entities, VOCABULARY)

    expected = list(range(len(entities)))

    def find(i: int) -> int:
        while expected[i] != i:
            i = expected[i]
        return i

    for i in range(len(entities)):
        for j in range(i):
            if set(identities[i]) & set(identities[j]):
                a, b = sorted((find(i), find(j)))
                expected[b] = a
    heads = {e.id: f"jsonld:{find(i)}:$" for i, e in enumerate(entities)}
    assert {e: graph.aliases.get(e, e) for e in heads} == heads
