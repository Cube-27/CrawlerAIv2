"""Identity (extraction spec): the entities that state one item, from one collector or several, are one entity of
the entity graph, and a standalone variant joins the group whose `productGroupID` it names."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def test_one_node_id_merges_related_types_most_specific_first() -> None:
    # JSON-LD 1.1 node map generation merges node objects with one @id whatever their types; a ProductGroup is a
    # Product, which is a Thing, so the Product's values are the group's.
    node = {"@id": "/p/1#product"}
    group = {"@context": SCHEMA_ORG, "@type": "ProductGroup", **node, "url": PAGE_URL}
    thing = {"@context": SCHEMA_ORG, "@type": "Thing", **node}

    graph, candidates = _graph(thing, _product(**node, name="Widget One"), group)

    assert graph.aliases == {"jsonld:1:$": "jsonld:0:$", "jsonld:2:$": "jsonld:0:$"}
    assert graph.entities["jsonld:0:$"].types == ("ProductGroup", "Product", "Thing")
    assert [(c.field, c.entity_id) for c in candidates] == [("title", "jsonld:0:$")]


def test_one_node_id_of_unrelated_types_merges_nothing() -> None:
    # A WebPage and an Organization are no one thing, though each is a Thing: the IRI states several things.
    node = {"@id": "/p/1#site"}
    blocks = [{"@context": SCHEMA_ORG, "@type": kind, **node} for kind in ("WebPage", "Organization", "Thing")]

    graph, _ = _graph(*blocks)

    assert graph.aliases == {}


# `isVariantOf` (D-1344): the inverse of `hasVariant`, so the group stands beside the page's Product.


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
