"""The schema.org map (SPEC-05 §4.1, §4.5): the type hierarchy from the pinned vocabulary file, and `schema_org` paths
read against a node's properties."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import JsonValue

from crawlerai.collect.schema_org_map import (
    MappedPath,
    Selected,
    Value,
    Vocabulary,
    VocabularyMissing,
    parse_path,
    select,
)

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
        ("AggregateOffer", "Offer", True),
        ("Offer", "AggregateOffer", False),
        ("Offer", "Product", False),
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


def test_a_missing_file_says_how_to_fetch_it(tmp_path: Path) -> None:
    with pytest.raises(VocabularyMissing, match="crawlerai data fetch"):
        Vocabulary.read(tmp_path / "absent.jsonld")


@pytest.mark.parametrize(
    ("path", "parsed"),
    [
        ("Product.name", MappedPath("Product", ("name",), None)),
        ("Product.brand.name", MappedPath("Product", ("brand", "name"), None)),
        ("Offer.price+priceCurrency", MappedPath("Offer", ("price",), "priceCurrency")),
    ],
)
def test_parse_path(path: str, parsed: MappedPath) -> None:
    assert parse_path(path) == parsed


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
    assert select(PRODUCT, parse_path("Product.name"), as_list=False) == [Selected("Widget 9", "product/name/0")]


def test_each_value_of_a_property_is_its_own_candidate() -> None:
    assert select(PRODUCT, parse_path("Product.image"), as_list=False) == [
        Selected("a.png", "product/image/0"),
        Selected("b.png", "product/image/1"),
    ]


def test_a_list_takes_every_value_and_the_first_value_s_locator() -> None:
    assert select(PRODUCT, parse_path("Product.image"), as_list=True) == [
        Selected(["a.png", "b.png"], "product/image/0")
    ]


def test_a_path_follows_nodes_and_text_stands_for_a_thing_s_name() -> None:
    # schema.org data model: where a Thing is expected, a text value is accepted, and it names that thing.
    assert select(PRODUCT, parse_path("Product.brand.name"), as_list=False) == [
        Selected("Acme 7", "brand/name/0"),
        Selected("Other 3", "product/brand/1"),
    ]


def test_text_does_not_stand_for_other_properties() -> None:
    assert select(PRODUCT, parse_path("Product.brand.logo"), as_list=False) == []


def test_a_joined_path_gives_one_object_from_one_node() -> None:
    offer = PRODUCT.properties["offers"][0]
    assert isinstance(offer, _Node)
    assert select(offer, parse_path("Offer.price+priceCurrency"), as_list=False) == [
        Selected({"price": "10.50", "priceCurrency": "EUR"}, "offer/price/0")
    ]


def test_a_joined_path_without_its_second_property_keeps_the_first_only() -> None:
    offer = _Node("offer", {"price": ["10.50"]})
    assert select(offer, parse_path("Offer.price+priceCurrency"), as_list=False) == [
        Selected({"price": "10.50"}, "offer/price/0")
    ]


def test_a_joined_path_with_two_second_values_keeps_both() -> None:
    offer = _Node("offer", {"price": [10], "priceCurrency": ["EUR", "USD"]})
    assert select(offer, parse_path("Offer.price+priceCurrency"), as_list=False) == [
        Selected({"price": 10, "priceCurrency": ["EUR", "USD"]}, "offer/price/0")
    ]


def test_a_node_value_is_its_json_object() -> None:
    assert select(PRODUCT, parse_path("Product.brand"), as_list=False) == [
        Selected({"@id": "brand"}, "product/brand/0"),
        Selected("Other 3", "product/brand/1"),
    ]
