"""The schema.org map (SPEC-05 §4.1, §4.5): the type hierarchy from the pinned vocabulary file, and `schema_org` paths
read against a node's properties."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect.schema_org_map import (
    MappedPath,
    Selected,
    Typed,
    Value,
    Vocabulary,
    VocabularyMissing,
    field_candidates,
    parse_paths,
    select,
)
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY_FILE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld"


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return Vocabulary.read(VOCABULARY_FILE)


@pytest.mark.parametrize(
    ("type_", "ancestor", "expected"),
    [
        ("Product", "Product", True),
        ("IndividualProduct", "Product", True),
        ("IndividualProduct", "Thing", True),
        ("ProductModel", "CreativeWork", True),  # two parents
        ("Offer", "AggregateOffer", False),
        ("Widget", "Thing", False),  # not in the vocabulary
        ("Product", "Widget", False),
    ],
)
def test_is_a_follows_sub_class_of_transitively(
    vocabulary: Vocabulary, type_: str, ancestor: str, expected: bool
) -> None:
    assert vocabulary.is_a(type_, ancestor) is expected


def test_types_are_the_classes_of_the_file(vocabulary: Vocabulary) -> None:
    assert "Product" in vocabulary
    assert "Text" in vocabulary
    assert "name" not in vocabulary  # a property
    assert "InStock" not in vocabulary  # an enumeration member


def test_identifiers_are_identifier_and_its_sub_properties(vocabulary: Vocabulary) -> None:
    # schema.org `rdfs:subPropertyOf`, transitively: gtin13 is a gtin, a gtin an identifier. mpn is not declared one.
    assert vocabulary.identifiers == frozenset({"identifier", "sku", "gtin", "gtin13"})


def test_sub_properties_are_the_narrower_properties_transitively(vocabulary: Vocabulary) -> None:
    assert vocabulary.sub_properties("identifier") == frozenset({"sku", "gtin", "gtin13"})
    assert vocabulary.sub_properties("gtin") == frozenset({"gtin13"})
    assert vocabulary.sub_properties("gtin13") == frozenset()


def test_a_missing_file_says_how_to_fetch_it(tmp_path: Path) -> None:
    with pytest.raises(VocabularyMissing, match="crawlerai data fetch"):
        Vocabulary.read(tmp_path / "absent.jsonld")


@pytest.mark.parametrize(
    ("path", "parsed"),
    [
        ("Product.name", (MappedPath("Product", ("name",), None),)),
        ("Product.brand.name", (MappedPath("Product", ("brand", "name"), None),)),
        ("Offer.price+priceCurrency", (MappedPath("Offer", ("price",), "priceCurrency"),)),
        (
            "Product.sku|Offer.sku|Product.offers.price+priceCurrency",
            (
                MappedPath("Product", ("sku",), None),
                MappedPath("Offer", ("sku",), None),
                MappedPath("Product", ("offers", "price"), "priceCurrency"),
            ),
        ),
    ],
)
def test_parse_paths(path: str, parsed: tuple[MappedPath, ...]) -> None:
    assert parse_paths(path) == parsed


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


def test_select_a_property_value() -> None:
    assert select(PRODUCT, parse_paths("Product.name")[0], as_list=False) == [Selected("Widget 9", "product/name/0")]


def test_each_value_of_a_property_is_its_own_candidate() -> None:
    assert select(PRODUCT, parse_paths("Product.image")[0], as_list=False) == [
        Selected("a.png", "product/image/0"),
        Selected("b.png", "product/image/1"),
    ]


def test_a_list_takes_every_value_and_the_first_value_s_locator() -> None:
    assert select(PRODUCT, parse_paths("Product.image")[0], as_list=True) == [
        Selected(["a.png", "b.png"], "product/image/0")
    ]


def test_a_path_follows_nodes_and_text_stands_for_a_thing_s_name() -> None:
    # schema.org data model: where a Thing is expected, a text value is accepted, and it names that thing.
    assert select(PRODUCT, parse_paths("Product.brand.name")[0], as_list=False) == [
        Selected("Acme 7", "brand/name/0"),
        Selected("Other 3", "product/brand/1"),
    ]
    # ... and for no other property.
    assert select(PRODUCT, parse_paths("Product.brand.logo")[0], as_list=False) == []


def test_a_joined_path_gives_one_object_from_one_node() -> None:
    offer = PRODUCT.properties["offers"][0]
    assert isinstance(offer, _Node)
    assert select(offer, parse_paths("Offer.price+priceCurrency")[0], as_list=False) == [
        Selected({"price": "10.50", "priceCurrency": "EUR"}, "offer/price/0")
    ]


def test_a_joined_path_without_its_second_property_keeps_the_first_only() -> None:
    offer = _Node("offer", {"price": ["10.50"]})
    assert select(offer, parse_paths("Offer.price+priceCurrency")[0], as_list=False) == [
        Selected({"price": "10.50"}, "offer/price/0")
    ]


def test_a_joined_path_with_two_second_values_keeps_both() -> None:
    offer = _Node("offer", {"price": [10], "priceCurrency": ["EUR", "USD"]})
    assert select(offer, parse_paths("Offer.price+priceCurrency")[0], as_list=False) == [
        Selected({"price": 10, "priceCurrency": ["EUR", "USD"]}, "offer/price/0")
    ]


def test_a_node_value_is_its_json_object() -> None:
    assert select(PRODUCT, parse_paths("Product.brand")[0], as_list=False) == [
        Selected({"@id": "brand"}, "product/brand/0"),
        Selected("Other 3", "product/brand/1"),
    ]


CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://shop.example.test/p/1")
SKU = FieldSpec(type=FieldType.IDENTIFIER, scheme="sku", description="d", schema_org="Product.sku|Offer.sku")
VARIANTS = FieldSpec(
    type=FieldType.LIST,
    description="d",
    schema_org="ProductGroup.hasVariant",
    key=["sku"],
    item=FieldSpec(
        type=FieldType.OBJECT,
        fields={
            "sku": SKU,
            "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
            "note": FieldSpec(type=FieldType.TEXT, description="d"),
        },
    ),
)


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


def test_a_value_two_alternatives_reach_on_one_entity_is_one_candidate() -> None:
    twice = FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.sku|Thing.sku")

    # Thing.sku reaches the variant's sku again, and the offer's for the first time.
    assert _found(ENTITIES, _schema(sku=twice)) == [
        ("sku", "variant-a", "jsonld:0:$.variant-a.sku[0]"),
        ("sku", "offer-a", "jsonld:0:$.offer-a.sku[0]"),
    ]


def test_a_row_mapped_field_gives_its_sub_fields_candidates_and_its_rows_none() -> None:
    assert _found(ENTITIES, _schema(variants=VARIANTS)) == [
        ("variants.sku", "variant-a", "jsonld:0:$.variant-a.sku[0]"),
        ("variants.sku", "offer-a", "jsonld:0:$.offer-a.sku[0]"),
        ("variants.price", "offer-a", "jsonld:0:$.offer-a.price[0]"),
    ]


GTIN = FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.gtin")
IMAGE = FieldSpec(type=FieldType.IMAGE_URL, description="d", schema_org="Product.image")
BRANDED = _JsonNode("item", {"gtin13": ["4006381333931"], "logo": ["https://cdn.example.test/logo.png"]})


def test_an_identifier_field_reaches_its_property_s_sub_properties() -> None:
    # RDF Schema `rdfs:subPropertyOf`: a `gtin13` value is a `gtin` value.
    assert _found((Typed("item", ("Product",), BRANDED),), _schema(gtin=GTIN)) == [
        ("gtin", "item", "jsonld:0:$.item.gtin13[0]"),
    ]


def test_another_field_reaches_only_its_own_property() -> None:
    # A logo is an image of the thing, but not the picture of the item an image field means.
    assert _found((Typed("item", ("Product",), BRANDED),), _schema(image=IMAGE)) == []


BARE_IDENTIFIER = FieldSpec(type=FieldType.IDENTIFIER, scheme="gtin", description="d", schema_org="Product.identifier")
MIXED = _JsonNode("item", {"gtin13": ["4006381333931"], "sku": ["S-1"], "identifier": ["X-1"]})


def test_a_field_mapped_to_identifier_widens_only_to_its_own_scheme() -> None:
    assert _found((Typed("item", ("Product",), MIXED),), _schema(gtin=BARE_IDENTIFIER)) == [
        ("gtin", "item", "jsonld:0:$.item.identifier[0]"),
        ("gtin", "item", "jsonld:0:$.item.gtin13[0]"),
    ]


def test_a_custom_identifier_mapped_to_identifier_reads_that_property_only() -> None:
    custom = BARE_IDENTIFIER.model_copy(update={"scheme": "custom"})

    assert _found((Typed("item", ("Product",), MIXED),), _schema(code=custom)) == [
        ("code", "item", "jsonld:0:$.item.identifier[0]"),
    ]
