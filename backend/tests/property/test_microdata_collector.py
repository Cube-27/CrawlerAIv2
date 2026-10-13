"""Microdata collector properties (SPEC-05 §4.5, INV-22): any markup is collected without raising, entities stay a
tree, every entity names an item element, and every candidate's locator names the property element it came from."""

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from selectolax.lexbor import LexborNode

from crawlerai.collect.locator import parse_locator
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url="https://shop.example.test/p/1")
SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    version=1,
    page_kind="detail",
    fields={
        "title": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.name"),
        "brand": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.brand.name"),
        "offer": FieldSpec(type=FieldType.TEXT, description="d", schema_org="Product.offers"),
    },
)

TAGS = st.sampled_from(["div", "span", "a", "img", "meta", "link", "time", "p"])
TYPES = st.sampled_from(["https://schema.org/Product", "http://schema.org/Offer", "https://vocab.example.test/T", ""])
TERMS = st.sampled_from(["name", "brand", "offers", "url", "schema:name", "https://schema.org/brand", "og:x", ""])
IDS = st.sampled_from(["a", "b", "c"])
ATTRIBUTES = st.fixed_dictionaries(
    {},
    optional={
        "itemscope": st.just(""),
        "itemtype": TYPES,
        "itemprop": TERMS,
        "itemref": st.lists(IDS, max_size=3).map(" ".join),
        "itemid": st.sampled_from(["#x", "/p/2", "http://[x", ""]),
        "id": IDS,
        "vocab": st.sampled_from(["https://schema.org/", ""]),
        "typeof": st.sampled_from(["Product", "Brand", "schema:Offer", ""]),
        "property": TERMS,
        "resource": st.sampled_from(["/p/3", "#y"]),
        "content": st.text(max_size=4),
        "href": st.text(max_size=4),
    },
)


@dataclass(frozen=True)
class Element:
    tag: str
    attributes: dict[str, str]
    children: tuple["Element | str", ...]

    def html(self) -> str:
        attributes = "".join(f' {name}="{escape(value)}"' for name, value in self.attributes.items())
        inner = "".join(c if isinstance(c, str) else c.html() for c in self.children)
        return f"<{self.tag}{attributes}>{inner}</{self.tag}>"


ELEMENTS: st.SearchStrategy[Element] = st.recursive(
    st.builds(Element, TAGS, ATTRIBUTES, st.just(())),
    lambda inner: st.builds(
        Element, TAGS, ATTRIBUTES, st.lists(st.one_of(inner, st.text(max_size=4).map(escape)), max_size=4).map(tuple)
    ),
    max_leaves=25,
)


def _resolve(page: ParsedPage, xpath: str) -> LexborNode:
    """The element at an XPath of `tag[n]` steps from the root."""
    root = page.tree.root
    assert root is not None
    first, *steps = xpath.removeprefix("/").split("/")
    assert first == "html[1]"
    node = root
    for step in steps:
        tag, index = step.removesuffix("]").split("[")
        node = [c for c in node.iter() if c.is_element_node and c.tag == tag][int(index) - 1]
    return node


@given(st.lists(ELEMENTS, min_size=1, max_size=3))
def test_entities_and_locators_name_their_elements(elements: list[Element]) -> None:
    page = ParsedPage("<html><body>" + "".join(e.html() for e in elements) + "</body></html>")
    result = MicrodataCollector(VOCABULARY).collect(page, SCHEMA, CTX)
    parents = {entity.id: entity.parent for entity in result.entities}
    for entity in result.entities:
        attributes = _resolve(page, parse_locator(entity.id).parts[0]).attributes
        assert "itemscope" in attributes or "typeof" in attributes
        seen: set[str] = set()
        current: str | None = entity.id
        while current is not None:  # entities form a tree (SPEC-05 §4.6)
            assert current not in seen
            seen.add(current)
            current = parents[current]
    for candidate in result.candidates:
        attributes = _resolve(page, parse_locator(candidate.locator).parts[0]).attributes
        assert "itemprop" in attributes or "property" in attributes
