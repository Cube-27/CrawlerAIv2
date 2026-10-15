"""The OpenGraph collector (SPEC-05 §4.5): `og:*` and `product:*` meta properties mapped to schema fields through the
fixed OGP table, every candidate owned by the `page` entity."""

from datetime import UTC, datetime
from html import escape

from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.og import OpenGraphCollector
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import SchemaId
from crawlerai.normalize.base import Context, Invalid, Ok
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

PAGE_URL = "https://shop.example.test/p/1"
CTX = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=PAGE_URL, page_url=PAGE_URL)


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


def _field(type_: FieldType, path: str | None, **params: object) -> FieldSpec:
    return FieldSpec.model_validate({"type": type_, "description": "d", "schema_org": path, **params})


SCHEMA = _schema(
    title=_field(FieldType.TEXT, "Product.name"),
    brand=_field(FieldType.TEXT, "Product.brand.name"),
    price=_field(FieldType.MONEY, "Offer.price+priceCurrency"),
    availability=_field(FieldType.ENUM, "Offer.availability", vocab="schema:ItemAvailability"),
    url=_field(FieldType.URL, "Product.url"),
    image_url=_field(FieldType.IMAGE_URL, "Product.image"),
    note=_field(FieldType.TEXT, None),
)


def _page(*metas: tuple[str, str]) -> ParsedPage:
    tags = "".join(f'<meta property="{escape(p)}" content="{escape(c)}">' for p, c in metas)
    return ParsedPage(f"<html><head>{tags}</head><body><p>body</p></body></html>")


def _collect(*metas: tuple[str, str], schema: SchemaDef = SCHEMA) -> CollectResult:
    return OpenGraphCollector().collect(_page(*metas), schema, CTX)


def _og(field: str, raw: object, normalized: object, locator: str) -> Candidate:
    return Candidate.model_validate(
        {
            "field": field,
            "entity_id": "page",
            "source_kind": "og",
            "raw": raw,
            "normalized": normalized,
            "locator": locator,
            "independent": True,
        }
    )


def test_each_ogp_property_maps_to_the_field_of_its_role() -> None:
    result = _collect(
        ("og:title", "Synthetic Widget"),
        ("og:url", "https://shop.example.test/p/1?ref=x"),
        ("og:image", "/img/widget.png"),
        ("product:price:amount", "19.99"),
        ("product:price:currency", "EUR"),
        ("product:availability", "InStock"),
    )

    assert result == CollectResult(
        entities=(Entity(id="page", kind="page", urls=("https://shop.example.test/p/1?ref=x",), parent=None),),
        candidates=(
            _og("title", "Synthetic Widget", Ok("Synthetic Widget"), "meta:og:title"),
            _og(
                "price",
                {"amount": "19.99", "currency": "EUR"},
                Ok({"amount": "19.99", "currency": "EUR"}),
                "meta:product:price:amount",
            ),
            _og("availability", "InStock", Ok("InStock"), "meta:product:availability"),
            _og("url", "https://shop.example.test/p/1?ref=x", Ok("https://shop.example.test/p/1?ref=x"), "meta:og:url"),
            _og("image_url", "/img/widget.png", Ok("https://shop.example.test/img/widget.png"), "meta:og:image"),
        ),
    )


def test_og_title_maps_only_to_the_name_of_the_root_type() -> None:
    # `Product.brand.name` is the brand's name, not the name of the object the page describes (Open Graph protocol,
    # `og:title`).
    result = _collect(("og:title", "Synthetic Widget"))

    assert [c.field for c in result.candidates] == ["title"]


def test_a_field_maps_only_when_its_type_matches_the_role() -> None:
    schema = _schema(
        name_as_url=_field(FieldType.URL, "Product.name"),
        image_as_text=_field(FieldType.TEXT, "Product.image"),
    )

    result = _collect(("og:title", "Synthetic Widget"), ("og:image", "https://shop.example.test/a.png"), schema=schema)

    assert result.candidates == ()


def test_the_first_value_of_a_repeated_property_is_the_value() -> None:
    # Open Graph protocol, "Arrays": the first tag, top to bottom, is preferred in a conflict.
    result = _collect(("og:image", "https://shop.example.test/a.png"), ("og:image", "https://shop.example.test/b.png"))

    assert result.candidates == (
        _og("image_url", "https://shop.example.test/a.png", Ok("https://shop.example.test/a.png"), "meta:og:image"),
    )


def test_og_image_url_is_the_same_property_as_og_image() -> None:
    # Open Graph protocol, "Structured Properties": `og:image:url` is identical to `og:image`.
    result = _collect(("og:image:url", "https://shop.example.test/a.png"))

    assert result.candidates == (
        _og("image_url", "https://shop.example.test/a.png", Ok("https://shop.example.test/a.png"), "meta:og:image:url"),
    )


def test_a_list_field_gets_every_value_in_document_order() -> None:
    schema = _schema(images=_field(FieldType.LIST, "Product.image", item=FieldSpec(type=FieldType.IMAGE_URL)))

    result = _collect(
        ("og:image", "https://shop.example.test/a.png"),
        ("og:image:url", "https://shop.example.test/b.png"),
        schema=schema,
    )

    assert result.candidates == (
        _og(
            "images",
            ["https://shop.example.test/a.png", "https://shop.example.test/b.png"],
            Ok(["https://shop.example.test/a.png", "https://shop.example.test/b.png"]),
            "meta:og:image",
        ),
    )


def test_a_price_without_a_currency_is_a_candidate_that_declines() -> None:
    # C7: no fallback currency; validity (§10) rejects the candidate.
    result = _collect(("product:price:amount", "19.99"))

    assert result.candidates == (
        _og("price", {"amount": "19.99"}, Invalid("no_currency"), "meta:product:price:amount"),
    )


def test_a_currency_without_an_amount_is_no_candidate() -> None:
    assert _collect(("product:price:currency", "EUR")).candidates == ()


def test_the_name_attribute_reads_like_property() -> None:
    page = ParsedPage('<html><head><meta name="og:title" content="Synthetic Widget"></head></html>')

    result = OpenGraphCollector().collect(page, SCHEMA, CTX)

    assert result.candidates == (_og("title", "Synthetic Widget", Ok("Synthetic Widget"), "meta:og:title"),)


def test_a_meta_without_content_is_skipped() -> None:
    page = ParsedPage(
        '<html><head><meta property="og:title"><meta property="og:title" content="Synthetic Widget"></head></html>'
    )

    result = OpenGraphCollector().collect(page, SCHEMA, CTX)

    assert result.candidates == (_og("title", "Synthetic Widget", Ok("Synthetic Widget"), "meta:og:title"),)


def test_og_url_names_the_page_entity_even_without_a_url_field() -> None:
    schema = _schema(title=_field(FieldType.TEXT, "Product.name"))

    result = _collect(("og:url", "HTTPS://Shop.Example.TEST/p/1"), schema=schema)

    assert result == CollectResult(
        entities=(Entity(id="page", kind="page", urls=("https://shop.example.test/p/1",), parent=None),),
        candidates=(),
    )


def test_a_page_without_opengraph_has_no_entity() -> None:
    page = ParsedPage('<html><head><meta name="description" content="Synthetic"></head></html>')

    assert OpenGraphCollector().collect(page, SCHEMA, CTX) == CollectResult(entities=(), candidates=())


def test_alternatives_have_a_role_only_when_each_names_the_same_property_of_its_root() -> None:
    # SPEC-13 §4.1: `ProductGroup.image|Product.image` names the object's image either way;
    # `Product.image|Product.brand.image` may name the brand's.
    schema = _schema(
        image=_field(FieldType.IMAGE_URL, "ProductGroup.image|Product.image"),
        mixed=_field(FieldType.IMAGE_URL, "Product.image|Product.brand.image"),
    )

    found = _collect(("og:image", "https://shop.example.test/a.png"), schema=schema).candidates
    assert [c.field for c in found] == ["image"]
