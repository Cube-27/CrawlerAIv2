"""The microdata collector (SPEC-05 §4.5): HTML Standard microdata items and RDFa Lite resources as entities, nested
scopes as nested entities, and a candidate for each `schema_org` path."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.microdata import MicrodataCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)
BODY = "/html[1]/body[1]"


def _text(path: str) -> FieldSpec:
    return FieldSpec(type=FieldType.TEXT, description="d", schema_org=path)


SCHEMA = SchemaDef(
    id=SchemaId(uuid7()),
    origin="user",
    status="active",
    name="synthetic",
    version=1,
    page_kind="detail",
    fields={
        "title": _text("Product.name"),
        "brand": _text("Product.brand.name"),
        "price": FieldSpec(type=FieldType.MONEY, description="d", schema_org="Offer.price+priceCurrency"),
        "images": FieldSpec(
            type=FieldType.LIST, description="d", item=FieldSpec(type=FieldType.IMAGE_URL), schema_org="Product.image"
        ),
        "note": FieldSpec(type=FieldType.TEXT, description="d"),  # no schema_org path: no candidates
    },
)


def _collect(body: str, schema: SchemaDef = SCHEMA) -> CollectResult:
    page = ParsedPage(f"<!doctype html><html><head></head><body>{body}</body></html>")
    return MicrodataCollector(VOCABULARY).collect(page, schema, CTX)


def _candidate(field: str, entity_id: str, raw: Any, normalized: Any, locator: str) -> Candidate:
    return Candidate(
        field=field,
        entity_id=entity_id,
        source_kind="microdata",
        raw=raw,
        normalized=normalized,
        locator=locator,
        independent=True,
    )


def _fields(result: CollectResult) -> list[tuple[str, str, Any]]:
    return [(c.field, c.entity_id, c.raw) for c in result.candidates]


def test_a_product_with_nested_items() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">'
        '<h1 itemprop="name">Widget 9</h1>'
        '<link itemprop="url" href="/p/1">'
        '<div itemprop="brand" itemscope itemtype="https://schema.org/Brand"><span itemprop="name">Acme 7</span></div>'
        '<img itemprop="image" src="/a.png"><img itemprop="image" src="https://shop.example.test/b.png">'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<span itemprop="price">10.50</span><meta itemprop="priceCurrency" content="EUR">'
        "</div></div>"
    )
    product, brand, offer = (
        f"microdata:{BODY}/div[1]",
        f"microdata:{BODY}/div[1]/div[1]",
        f"microdata:{BODY}/div[1]/div[2]",
    )
    assert result.entities == (
        Entity(id=product, kind="Product", urls=(PAGE_URL,), parent=None),
        Entity(id=brand, kind="Brand", urls=(), parent=product, via="brand"),
        Entity(id=offer, kind="Offer", urls=(), parent=product, via="offers"),
    )
    assert result.candidates == (
        _candidate("title", product, "Widget 9", Ok("Widget 9"), f"{product}/h1[1]"),
        _candidate("brand", product, "Acme 7", Ok("Acme 7"), f"{brand}/span[1]"),
        _candidate(
            "price",
            offer,
            {"price": "10.50", "priceCurrency": "EUR"},
            Ok({"amount": "10.50", "currency": "EUR"}),
            f"{offer}/span[1]",
        ),
        _candidate(
            "images",
            product,
            ["/a.png", "https://shop.example.test/b.png"],
            Ok(["https://shop.example.test/a.png", "https://shop.example.test/b.png"]),
            f"{product}/img[1]",
        ),
    )
    assert result.diagnostics == ()


@pytest.mark.parametrize(
    ("element", "raw"),
    [
        ('<meta itemprop="name" content="Widget 9">', "Widget 9"),
        ('<img itemprop="name" src="/w.png" alt="x">', "/w.png"),
        ('<a itemprop="name" href="/w">Widget 9</a>', "/w"),
        ('<object itemprop="name" data="/w.bin"></object>', "/w.bin"),
        ('<data itemprop="name" value="9">nine</data>', "9"),
        ('<time itemprop="name" datetime="2026-10-01">1 October</time>', "2026-10-01"),
        ('<time itemprop="name">2026-10-01</time>', "2026-10-01"),
        ('<span itemprop="name">Widget <b>9</b></span>', "Widget 9"),
        ('<img itemprop="name">', ""),  # a missing URL attribute is the empty string
    ],
)
def test_the_value_of_a_property_follows_its_element(element: str, raw: str) -> None:
    # HTML Standard, microdata, "Values": the attribute or text that holds an element's property value.
    result = _collect(f'<div itemscope itemtype="https://schema.org/Product">{element}</div>')
    assert [(c.field, c.raw) for c in result.candidates] == [("title", raw)]


def test_a_nested_item_s_properties_are_not_the_outer_item_s() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">'
        '<div itemprop="isRelatedTo" itemscope itemtype="https://schema.org/Product"><b itemprop="name">B</b></div>'
        '<section itemscope itemtype="https://schema.org/Product"><b itemprop="name">C</b></section>'
        '<b itemprop="name">A</b></div>'
    )
    outer, related, top = (
        f"microdata:{BODY}/div[1]",
        f"microdata:{BODY}/div[1]/div[1]",
        f"microdata:{BODY}/div[1]/section[1]",
    )
    # A nested item (`itemprop` + `itemscope`) is its holder's child; an item without `itemprop` is a top-level item
    # (HTML Standard), so DOM nesting alone makes no parent.
    assert [(e.id, e.parent, e.via) for e in result.entities] == [
        (outer, None, None),
        (related, outer, "isRelatedTo"),
        (top, None, None),
    ]
    assert _fields(result) == [("title", outer, "A"), ("title", related, "B"), ("title", top, "C")]


def test_via_is_the_one_property_name_the_holder_uses() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">'
        '<div itemprop="isSimilarTo" itemscope><div itemprop="https://schema.org/item" itemscope itemtype="https://schema.org/Product"></div>'
        "</div>"
        '<div itemprop="isRelatedTo isSimilarTo" itemscope itemtype="https://schema.org/Product"></div></div>'
    )
    # Through an untyped item, the property is the one on the entity; an element naming two properties names neither.
    assert [(e.parent, e.via) for e in result.entities] == [
        (None, None),
        (f"microdata:{BODY}/div[1]", "isSimilarTo"),
        (f"microdata:{BODY}/div[1]", None),
    ]


def test_itemref_adds_the_referenced_properties() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product" itemref="n o missing"></div>'
        '<p id="n"><b itemprop="name">Widget 9</b><span itemscope><i itemprop="name">not this</i></span></p>'
        '<div id="o" itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<span itemprop="price">5</span><span itemprop="priceCurrency">USD</span></div>'
    )
    product, offer = f"microdata:{BODY}/div[1]", f"microdata:{BODY}/div[2]"
    assert [(e.id, e.parent) for e in result.entities] == [(product, None), (offer, product)]
    assert _fields(result) == [
        ("title", product, "Widget 9"),
        ("price", offer, {"price": "5", "priceCurrency": "USD"}),
    ]


def test_itemref_cycles_end() -> None:
    result = _collect(
        '<div id="a" itemprop="isRelatedTo" itemscope itemtype="https://schema.org/Product" itemref="b">'
        '<b itemprop="name">A</b></div>'
        '<div id="b" itemprop="isRelatedTo" itemscope itemtype="https://schema.org/Product" itemref="a b">'
        '<b itemprop="name">B</b></div>'
    )
    a, b = f"microdata:{BODY}/div[1]", f"microdata:{BODY}/div[2]"
    assert [(e.id, e.parent) for e in result.entities] == [(a, b), (b, None)]
    assert _fields(result) == [("title", a, "A"), ("title", b, "B")]


def test_an_item_two_items_reference_has_no_parent() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product" itemref="o"></div>'
        '<div itemscope itemtype="https://schema.org/Product" itemref="o"></div>'
        '<div id="o" itemprop="offers" itemscope itemtype="https://schema.org/Offer"></div>'
    )
    assert [e.parent for e in result.entities] == [None, None, None]


@pytest.mark.parametrize(
    "markup",
    [
        '<div itemscope itemtype="http://schema.org/Product"><b itemprop="name">Widget 9</b></div>',
        '<div itemscope itemtype="https://schema.org/Product"><b itemprop="https://schema.org/name">Widget 9</b></div>',
        '<div itemscope itemtype="https://schema.org/Product"><b itemprop="sku name">Widget 9</b></div>',
        # HTML tokens are split on ASCII whitespace only: a no-break space is part of the token.
        '<div itemscope itemtype="https://schema.org/Product"><b itemprop="name">Widget 9</b>'
        '<i itemprop="name\u00a0x">y</i></div>',
        '<div itemscope itemtype="https://vocab.example.test/Thing https://schema.org/Product">'
        '<b itemprop="name">Widget 9</b></div>',
        '<div vocab="https://schema.org/" typeof="Product"><b property="name">Widget 9</b></div>',
        '<div vocab="http://schema.org/"><div typeof="Product"><b property="name">Widget 9</b></div></div>',
        '<div typeof="schema:Product"><b property="schema:name">Widget 9</b></div>',
        '<div typeof="https://schema.org/Product"><b property="http://schema.org/name">Widget 9</b></div>',
        '<div vocab="https://schema.org/" typeof="Product"><meta property="name" content="Widget 9"></div>',
    ],
)
def test_schema_org_spellings(markup: str) -> None:
    result = _collect(markup)
    assert [e.kind for e in result.entities] == ["Product"]
    assert [(c.field, c.raw) for c in result.candidates] == [("title", "Widget 9")]


@pytest.mark.parametrize(
    "markup",
    [
        '<div itemscope itemtype="https://vocab.example.test/Product"><b itemprop="name">Widget 9</b></div>',
        '<div itemscope itemtype="https://schema.org/Widget"><b itemprop="name">Widget 9</b></div>',
        '<div itemscope><b itemprop="name">Widget 9</b></div>',  # an untyped item is in no vocabulary
        '<div typeof="Product"><b property="name">Widget 9</b></div>',  # no vocab in scope
        '<div vocab="https://schema.org/"><div vocab="" typeof="Product"><b property="name">x</b></div></div>',
        '<div typeof="og:Product"><b property="og:name">Widget 9</b></div>',  # a prefix RDFa does not define
        '<b itemprop="name">Widget 9</b><b vocab="https://schema.org/" property="name">Widget 9</b>',  # no item
    ],
)
def test_markup_outside_schema_org_gives_no_entities(markup: str) -> None:
    result = _collect(
        markup + '<div itemscope itemtype="https://schema.org/Product"><b itemprop="name">Widget 10</b></div>'
    )
    assert [e.kind for e in result.entities] == ["Product"]
    assert [c.raw for c in result.candidates] == ["Widget 10"]


def test_an_untyped_nested_item_s_names_are_not_schema_org() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">'
        '<div itemprop="brand" itemscope><span itemprop="name">Acme 7</span></div><b itemprop="name">Widget 9</b></div>'
    )
    assert [e.kind for e in result.entities] == ["Product"]
    assert _fields(result) == [("title", f"microdata:{BODY}/div[1]", "Widget 9")]


def test_rdfa_lite_nests_resources() -> None:
    result = _collect(
        '<div vocab="https://schema.org/" typeof="Product" resource="/p/1#it">'
        '<span property="name">Widget 9</span>'
        '<div property="offers" typeof="Offer">'
        '<span property="price" content="10.50">10,50</span><span property="priceCurrency">EUR</span>'
        '<a property="url" href="/p/1">here</a></div></div>'
    )
    product, offer = f"microdata:{BODY}/div[1]", f"microdata:{BODY}/div[1]/div[1]"
    assert result.entities == (
        Entity(id=product, kind="Product", urls=(PAGE_URL,), parent=None),
        Entity(id=offer, kind="Offer", urls=(PAGE_URL,), parent=product, via="offers"),
    )
    assert _fields(result) == [
        ("title", product, "Widget 9"),
        ("price", offer, {"price": "10.50", "priceCurrency": "EUR"}),
    ]


def test_an_element_with_both_syntaxes_is_one_item() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product" vocab="https://schema.org/" typeof="Product">'
        '<b itemprop="name">A</b><i property="name">B</i></div>'
    )
    assert [e.id for e in result.entities] == [f"microdata:{BODY}/div[1]"]
    assert [c.raw for c in result.candidates] == ["A", "B"]


def test_entity_urls_are_canonical_and_name_pages() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product" itemid="HTTPS://Shop.Example.test/p/2">'
        '<a itemprop="url" href="/p/1?x=1#reviews">x</a>'
        '<link itemprop="mainEntityOfPage" href="https://shop.example.test/p/3">'
        '<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
        '<link itemprop="url" href="https://shop.example.test/p/4"></div>'
        '<link itemprop="sameAs" href="https://shop.example.test/p/5"></div>'
        '<div itemscope itemtype="https://schema.org/Product" itemid="#second"></div>'
    )
    assert [e.urls for e in result.entities] == [
        (
            "https://shop.example.test/p/1?x=1",
            "https://shop.example.test/p/2",
            "https://shop.example.test/p/3",
            "https://shop.example.test/p/4",
        ),
        ("https://shop.example.test/p/4",),
        (),  # an itemid with a fragment names a part of the document (RFC 3986 §3.5)
    ]


def test_an_item_value_is_its_json_object() -> None:
    schema = SCHEMA.model_copy(update={"fields": {"brand": _text("Product.brand")}})
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">'
        '<div itemprop="brand" itemscope itemtype="https://schema.org/Brand">'
        '<b itemprop="name">Acme 7</b><i itemprop="name">Acme</i><u itemprop="logo">/l.png</u></div></div>',
        schema,
    )
    brand = {"@type": "Brand", "name": ["Acme 7", "Acme"], "logo": "/l.png"}
    assert [(c.raw, c.normalized) for c in result.candidates] == [(brand, Invalid("not_a_string"))]


def test_subtypes_come_first_and_match_their_supertype_s_paths() -> None:
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Thing https://schema.org/IndividualProduct">'
        '<b itemprop="name">Widget 9</b></div>'
    )
    assert [e.kind for e in result.entities] == ["IndividualProduct"]
    assert [c.field for c in result.candidates] == ["title"]


def test_deep_nesting_is_walked_without_the_call_stack() -> None:
    depth = 1500
    item = '<div itemprop="brand" itemscope itemtype="https://schema.org/Brand">'
    result = _collect(
        '<div itemscope itemtype="https://schema.org/Product">' + item * depth + "</div>" * (depth + 1),
        SCHEMA.model_copy(update={"fields": {"brand": _text("Product.brand")}}),
    )
    assert len(result.entities) == depth + 1
    assert result.entities[-1].parent == result.entities[-2].id
    # The brand's JSON object nests deeper than the candidate model accepts: skipped, never raised (§4.5).
    assert result.candidates == ()
    assert [d.split(" (")[0] for d in result.diagnostics] == [f"value at microdata:{BODY}/div[1]/div[1] skipped"]


@pytest.mark.parametrize("attribute", ['itemscope itemid=" "', 'vocab="https://schema.org/" resource="\t"'])
def test_a_blank_item_id_names_no_page(attribute: str) -> None:
    # A blank id would resolve to the base URL itself and name the page the item is on.
    result = _collect(f'<div {attribute} itemtype="https://schema.org/Product" typeof="Product"></div>')
    assert [e.urls for e in result.entities] == [()]
