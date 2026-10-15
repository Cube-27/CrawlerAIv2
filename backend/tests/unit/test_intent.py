"""Intent (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3, §10): which entity the page is about, or `intent_ambiguous`."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from crawlerai.collect.base import PAGE, Entity
from crawlerai.collect.jsonld import JsonLdCollector
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.content.page import ParsedPage
from crawlerai.core.ids import uuid7
from crawlerai.db.models import PageKind, SchemaId
from crawlerai.normalize.base import Context
from crawlerai.resolve.intent import AmbiguousTarget, primary_types, select_target
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")
PAGE_URL = "https://shop.example.test/p/1"
OTHER_URL = "https://shop.example.test/p/2"


def _field(path: str | None, *, required: bool = True) -> FieldSpec:
    return FieldSpec(type=FieldType.TEXT, description="d", required=required, schema_org=path)


def _schema(page_kind: PageKind = "detail", **fields: FieldSpec) -> SchemaDef:
    return SchemaDef(
        id=SchemaId(uuid7()),
        origin="user",
        status="active",
        name="synthetic",
        version=1,
        page_kind=page_kind,
        fields=fields,
    )


PRODUCT_SCHEMA = _schema(
    title=_field("Product.name"),
    price=_field("Offer.price+priceCurrency"),
    brand=_field("Product.brand.name"),
    seller=_field("Organization.legalName", required=False),
)


def _entity(id_: str, kind: str = "Product", *urls: str, parent: str | None = None, via: str | None = None) -> Entity:
    return Entity(id=id_, kind=kind, urls=urls, parent=parent, via=via)


def _select(
    *entities: Entity,
    request_url: str = PAGE_URL,
    final_url: str = PAGE_URL,
    canonical_url: str | None = None,
    schema: SchemaDef = PRODUCT_SCHEMA,
) -> Entity | AmbiguousTarget:
    graph = EntityGraph.of(entities, VOCABULARY)
    return select_target(request_url, final_url, canonical_url, graph, primary_types(schema, VOCABULARY))


def test_primary_types_are_the_required_fields_roots_except_offer() -> None:
    assert primary_types(PRODUCT_SCHEMA, VOCABULARY) == frozenset({"Product"})


def test_a_schema_whose_required_fields_are_all_offers_targets_the_offer() -> None:
    schema = _schema(price=_field("Offer.price+priceCurrency"), title=_field("Product.name", required=False))
    assert primary_types(schema, VOCABULARY) == frozenset({"Offer"})


def test_a_listings_page_fields_name_no_primary_type() -> None:
    # §5.2: a page field describes the listing page, so its path's type is not what the rows are.
    heading = FieldSpec(type=FieldType.TEXT, description="d", required=True, scope="page", schema_org="Product.name")
    schema = _schema("listing", title=_field("JobPosting.title"), heading=heading)
    assert primary_types(schema, VOCABULARY) == frozenset({"JobPosting"})


def test_required_fields_without_a_path_name_no_type() -> None:
    assert primary_types(_schema(note=_field(None), title=_field("Product.name")), VOCABULARY) == frozenset({"Product"})


def test_the_one_primary_entity_is_the_target_whatever_its_urls() -> None:
    product = _entity("jsonld:0:$", "Product", OTHER_URL)
    assert _select(product, _entity("jsonld:1:$", "Organization")) == product


def test_a_subtype_of_the_primary_type_is_a_primary_entity() -> None:
    product = _entity("jsonld:0:$", "IndividualProduct")
    assert _select(product) == product


def test_related_products_are_not_candidates() -> None:
    main = _entity("jsonld:0:$")
    related = _entity("jsonld:0:$['isRelatedTo']", "Product", PAGE_URL, parent=main.id, via="isRelatedTo")
    similar = _entity("jsonld:0:$['isSimilarTo'][0]", "Product", parent=main.id, via="isSimilarTo")
    nested_deeper = _entity("jsonld:0:$['isSimilarTo'][0]['x']", "Product", parent=similar.id, via="x")
    assert _select(main, related, similar, nested_deeper) == main


def test_the_variants_of_a_product_group_are_its_members_not_candidates() -> None:
    # schema.org `hasVariant`: a member of the group. Variants that repeat the group's URL do not compete with it.
    group = _entity("jsonld:0:$", "ProductGroup", PAGE_URL)
    variants = [
        _entity(f"jsonld:0:$['hasVariant'][{i}]", "Product", PAGE_URL, parent=group.id, via="hasVariant")
        for i in range(2)
    ]
    assert _select(group, *variants) == group


def test_a_variant_under_an_entity_that_is_not_primary_stays_a_candidate() -> None:
    # Only a primary entity's members are excluded, as with the relation properties.
    holder = _entity("jsonld:0:$", "Organization")
    variant = _entity("jsonld:0:$['hasVariant']", "Product", PAGE_URL, parent=holder.id, via="hasVariant")
    assert _select(holder, variant) == variant


def test_products_in_a_list_are_not_candidates() -> None:
    main = _entity("jsonld:0:$", "Product")
    listing = _entity("jsonld:1:$", "ItemList")
    item = _entity("jsonld:1:$['itemListElement'][0]", "ListItem", parent=listing.id, via="itemListElement")
    in_item = _entity("jsonld:1:$['itemListElement'][0]['item']", "Product", PAGE_URL, parent=item.id, via="item")
    in_list = _entity("jsonld:1:$['itemListElement'][1]", "Product", PAGE_URL, parent=listing.id)
    assert _select(main, listing, item, in_item, in_list) == main


def test_a_product_nested_through_another_property_stays_a_candidate() -> None:
    # Only ItemList/ListItem and the relation properties exclude (§4.6 step 1); the URL then decides.
    main = _entity("jsonld:0:$", "Product", OTHER_URL)
    accessory = _entity("jsonld:0:$['x']", "Product", PAGE_URL, parent=main.id, via="x")
    assert _select(main, accessory) == accessory


@pytest.mark.parametrize("which", ["request_url", "final_url", "canonical_url"])
def test_several_candidates_are_settled_by_one_page_url(which: str) -> None:
    urls = {"request_url": OTHER_URL, "final_url": OTHER_URL, "canonical_url": None} | {which: PAGE_URL}
    first = _entity("jsonld:0:$", "Product", PAGE_URL)
    second = _entity("jsonld:1:$", "Product", "https://shop.example.test/p/3")
    assert _select(first, second, **urls) == first  # type: ignore[arg-type]


def test_urls_match_after_canonicalization() -> None:
    first = _entity("jsonld:0:$", "Product", PAGE_URL)
    second = _entity("jsonld:1:$", "Product", OTHER_URL)
    assert _select(first, second, request_url="HTTPS://Shop.Example.test:443/p/1") == first


def test_several_candidates_and_no_url_match_is_ambiguous() -> None:
    first = _entity("jsonld:0:$", "Product", OTHER_URL)
    second = _entity("jsonld:1:$", "Product")
    assert _select(first, second) == AmbiguousTarget(candidates=(first.id, second.id))


def test_several_candidates_matching_the_url_is_ambiguous() -> None:
    first = _entity("jsonld:0:$", "Product", PAGE_URL)
    second = _entity("microdata:/html[1]/body[1]/div[1]", "Product", PAGE_URL)
    assert _select(first, second) == AmbiguousTarget(candidates=(first.id, second.id))


def test_primary_entities_that_are_all_excluded_are_ambiguous() -> None:
    # A list of products is not a page about one of them (§4.6 step 3: no candidate matches).
    listing = _entity("jsonld:0:$", "ItemList")
    in_list = _entity("jsonld:0:$['itemListElement'][0]", "Product", PAGE_URL, parent=listing.id)
    assert _select(listing, in_list) == AmbiguousTarget(candidates=())


def test_without_a_primary_entity_the_page_is_the_target() -> None:
    page = _entity(PAGE, PAGE, PAGE_URL)
    assert _select(page, _entity("jsonld:0:$", "Organization")) == page
    assert _select() == Entity(id=PAGE, kind=PAGE, urls=(), parent=None)


def _jsonld_target(*blocks: Any, request_url: str = PAGE_URL) -> Entity | AmbiguousTarget:
    scripts = "".join(f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks)
    page = ParsedPage(f"<html><head>{scripts}</head><body></body></html>")
    ctx = Context(captured_at=datetime(2026, 10, 1, tzinfo=UTC), base_url=request_url, page_url=request_url)
    result = JsonLdCollector(VOCABULARY).collect(page, PRODUCT_SCHEMA, ctx)
    graph = EntityGraph.of(result.entities, VOCABULARY)
    return select_target(request_url, request_url, None, graph, primary_types(PRODUCT_SCHEMA, VOCABULARY))


def _product(url: str, **members: Any) -> dict[str, Any]:
    return {"@context": "https://schema.org", "@type": "Product", "url": url} | members


def test_a_product_page_with_recommendations_targets_its_product() -> None:
    recommended = {"@type": "Product", "url": OTHER_URL}
    target = _jsonld_target(
        _product(PAGE_URL, isRelatedTo=[recommended], isSimilarTo={"@id": "#similar"}),
        {"@context": "https://schema.org", "@type": "Product", "@id": "#similar", "url": OTHER_URL},
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [{"@type": "ListItem", "item": {"@type": "Product", "url": PAGE_URL}}],
        },
    )
    assert isinstance(target, Entity)
    assert target.id == "jsonld:0:$"


def test_a_product_group_page_targets_its_group_when_the_variants_repeat_its_url() -> None:
    variant = {"@type": "Product", "url": PAGE_URL, "offers": {"@type": "Offer", "price": "5", "priceCurrency": "EUR"}}
    group = {"@context": "https://schema.org", "@type": "ProductGroup", "url": PAGE_URL, "hasVariant": [variant] * 3}
    target = _jsonld_target(group)
    assert isinstance(target, Entity)
    assert target.id == "jsonld:0:$"


def test_two_top_level_products_are_settled_by_the_request_url() -> None:
    blocks = (_product(OTHER_URL), _product(PAGE_URL))
    target = _jsonld_target(*blocks)
    assert isinstance(target, Entity)
    assert target.id == "jsonld:1:$"
    assert _jsonld_target(*blocks, request_url="https://shop.example.test/p/3") == AmbiguousTarget(
        candidates=("jsonld:0:$", "jsonld:1:$")
    )


def test_primary_types_are_the_roots_of_every_alternative() -> None:
    schema = _schema(title=_field("ProductGroup.sku|Product.sku"), price=_field("Offer.price+priceCurrency"))

    assert primary_types(schema, VOCABULARY) == frozenset({"ProductGroup", "Product"})
