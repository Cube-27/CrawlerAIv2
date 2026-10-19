"""The schema.org map (extraction spec): the type hierarchy from the pinned vocabulary file, and `schema_org` paths
read against a node's properties."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect.schema_org_map import (
    Selected,
    Typed,
    Value,
    Vocabulary,
    field_candidates,
    select,
)
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.paths import parse_paths
from crawlerai.schemas.registry import load_presets
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY_FILE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld"


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return Vocabulary.read(VOCABULARY_FILE)


@dataclass(frozen=True)
class _Node:
    """A node with fixed property values; each value's locator is `<node>/<prop>/<i>`."""

    name: str
    properties: Mapping[str, Sequence["JsonValue | _Node"]]
    node_id: str | None = None

    def values(self, prop: str) -> list[Value]:
        found = []
        for i, item in enumerate(self.properties.get(prop, ())):
            locator = f"{self.name}/{prop}/{i}"
            if isinstance(item, _Node):
                found.append(Value(item.raw(), locator, item))
            else:
                found.append(Value(item, locator))
        return found

    def raw(self) -> JsonValue:
        return {"@id": self.name}


BRAND = _Node("brand", {"name": ["Acme 7"]})
PRODUCT = _Node(
    "product",
    {
        "name": ["Widget 9"],
        "image": ["a.png", "b.png"],
        "brand": [BRAND, "Other 3"],
        "offers": [_Node("offer", {"price": ["10.50"], "priceCurrency": ["EUR"]})],
    },
)


def test_a_path_follows_nodes_and_text_stands_for_a_thing_s_name() -> None:
    # schema.org data model: where a Thing is expected, a text value is accepted, and it names that thing.
    assert select(PRODUCT, parse_paths("Product.brand.name")[0], as_list=False) == [
        Selected("Acme 7", "brand/name/0"),
        Selected("Other 3", "product/brand/1"),
    ]
    # ... and for no other property.
    assert select(PRODUCT, parse_paths("Product.brand.logo")[0], as_list=False) == []


CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://shop.example.test/p/1")
SKU = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku|Offer.sku")


def _schema(**fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        page_kind="detail",
        fields=fields,
    )


def _found(entities: Sequence[Typed], schema: SchemaDef) -> list[tuple[str, str, str]]:
    found = field_candidates(entities, schema, CTX, vocabulary=_VOCABULARY, source_kind="jsonld", diagnostics=[])
    return [(c.field, c.entity_id, c.locator) for c in found]


@dataclass(frozen=True)
class _JsonNode(_Node):
    """A node whose values are located as JSON-LD values are: `jsonld:0:$.<node>.<prop>[<i>]`."""

    def values(self, prop: str) -> list[Value]:
        return [Value(v.raw, f"jsonld:0:$.{self.name}.{prop}[{i}]", v.node) for i, v in enumerate(super().values(prop))]


_VOCABULARY = Vocabulary.read(VOCABULARY_FILE)
OFFER_A = _JsonNode("offer-a", {"sku": ["S-1"], "price": ["5"], "priceCurrency": ["EUR"]})
VARIANT_A = _JsonNode("variant-a", {"sku": ["S-1"], "offers": [OFFER_A]})
GROUP = _JsonNode("group", {"hasVariant": [VARIANT_A]})
ENTITIES = (
    Typed("group", ("ProductGroup",), GROUP),
    Typed("variant-a", ("Product",), VARIANT_A),
    Typed("offer-a", ("Offer",), OFFER_A),
)


def test_alternatives_pool_their_candidates() -> None:
    assert _found(ENTITIES, _schema(sku=SKU)) == [
        ("sku", "variant-a", "jsonld:0:$.variant-a.sku[0]"),
        ("sku", "offer-a", "jsonld:0:$.offer-a.sku[0]"),
    ]


@dataclass(frozen=True)
class _BracketNode(_Node):
    """A node whose values are located in JSON path bracket notation: `jsonld:0:$['<node>']['<prop>'][<i>]`."""

    def values(self, prop: str) -> list[Value]:
        return [
            Value(v.raw, f"jsonld:0:$['{self.name}']['{prop}'][{i}]", v.node)
            for i, v in enumerate(super().values(prop))
        ]


def _posting(name: str, **values: list[JsonValue | _Node]) -> Typed:
    return Typed(name, ("JobPosting",), _JsonNode(name, {"url": [f"https://jobs.example.test/{name}"], **values}))


def test_the_job_presets_apply_url_is_the_postings_apply_action_target_only() -> None:
    # Schemas spec, "Stated apply link": the posting's own `url` is not its apply link.
    apply_url = next(p for p in load_presets() if p.name == "job_detail").fields["apply_url"]
    action = _BracketNode("act", {"target": ["https://jobs.example.test/a/apply"]})
    entities = (_posting("a", potentialAction=[action]), _posting("b"))

    assert _found(entities, _schema(apply_url=apply_url)) == [("apply_url", "a", "jsonld:0:$['act']['target'][0]")]


PRESET_PRICE = next(p for p in load_presets() if p.name == "commerce_detail").fields["price"]
LIST_PRICE = FieldSpec(
    type=FieldType.MONEY,
    description="d",
    schema_org="Offer.priceSpecification{priceType=StrikethroughPrice}.price+priceCurrency"
    "|Offer.priceSpecification{priceType=ListPrice}.price+priceCurrency",
)
UNIT_PRICE = FieldSpec(
    type=FieldType.MONEY, description="d", schema_org="Offer.priceSpecification{referenceQuantity}.price+priceCurrency"
)


def test_path_predicates_read_each_price_role_from_its_own_price_specification() -> None:
    # Schemas spec, "schema.org paths": `{name=Value}` matches a term or its IRI, `{name}` presence, `{!name}` absence.
    struck = _JsonNode(
        "struck", {"priceType": ["https://schema.org/StrikethroughPrice"], "price": ["40"], "priceCurrency": ["EUR"]}
    )
    quantity = _JsonNode("quantity", {"value": [1], "unitCode": ["KGM"]})
    per_unit = _JsonNode("per-unit", {"referenceQuantity": [quantity], "price": ["2.50"], "priceCurrency": ["EUR"]})
    offer = _JsonNode("offer", {"price": ["25"], "priceCurrency": ["EUR"], "priceSpecification": [struck, per_unit]})
    schema = _schema(price=PRESET_PRICE, list_price=LIST_PRICE, unit_price=UNIT_PRICE)

    assert _found((Typed("offer", ("Offer",), offer),), schema) == [
        ("price", "offer", "jsonld:0:$.offer.price[0]"),
        ("list_price", "offer", "jsonld:0:$.struck.price[0]"),
        ("unit_price", "offer", "jsonld:0:$.per-unit.price[0]"),
    ]
