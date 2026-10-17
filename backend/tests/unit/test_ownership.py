"""Ownership (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3): a candidate belongs to the entity that holds it, and only
the target's own candidates, the page's, and those of an Offer of the target are the target's."""

from pathlib import Path

import pytest

from crawlerai.collect.base import ARRAY_ROW, PAGE, Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.normalize.base import Ok
from crawlerai.resolve.ownership import EntityGraph

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")

PRODUCT = Entity(id="jsonld:0:$", types=("Product",), urls=(), parent=None)
OFFER = Entity(id="jsonld:0:$['offers']", types=("Offer",), urls=(), parent=PRODUCT.id, via="offers")
AGGREGATE = Entity(id="jsonld:0:$['offers'][1]", types=("AggregateOffer",), urls=(), parent=PRODUCT.id, via="offers")
INNER_OFFER = Entity(
    id="jsonld:0:$['offers'][1]['offers']", types=("Offer",), urls=(), parent=AGGREGATE.id, via="offers"
)
BRAND = Entity(id="jsonld:0:$['brand']", types=("Brand",), urls=(), parent=PRODUCT.id, via="brand")
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", types=("Product",), urls=(), parent=PRODUCT.id, via="isRelatedTo")
RELATED_OFFER = Entity(id="jsonld:0:$['isRelatedTo']['offers']", types=("Offer",), urls=(), parent=RELATED.id)
OTHER = Entity(id="jsonld:1:$", types=("Product",), urls=(), parent=None)
GROUP = Entity(id="jsonld:2:$", types=("ProductGroup",), urls=(), parent=None)
VARIANT = Entity(id="jsonld:2:$['hasVariant'][0]", types=("Product",), urls=(), parent=GROUP.id, via="hasVariant")
VARIANT_OFFER = Entity(
    id="jsonld:2:$['hasVariant'][0]['offers']", types=("Offer",), urls=(), parent=VARIANT.id, via="offers"
)
VARIANT_BRAND = Entity(id="jsonld:2:$['hasVariant'][0]['brand']", types=("Brand",), urls=(), parent=VARIANT.id)
GROUP_OFFER = Entity(id="jsonld:2:$['offers']", types=("Offer",), urls=(), parent=GROUP.id, via="offers")
OG_PAGE = Entity(id=PAGE, types=(PAGE,), urls=("https://shop.example.test/p/1",), parent=None)

ENTITIES = (PRODUCT, OFFER, AGGREGATE, INNER_OFFER, BRAND, RELATED, RELATED_OFFER, OTHER)
GROUP_ENTITIES = (GROUP, VARIANT, VARIANT_OFFER, VARIANT_BRAND, GROUP_OFFER)


def _candidate(entity: Entity | str) -> Candidate:
    entity_id = entity if isinstance(entity, str) else entity.id
    if entity_id.startswith("js_state:"):  # a state row's value: its locator addresses the script, not the row's id
        return Candidate(
            field="price",
            entity_id=entity_id,
            source_kind="js_state",
            raw="x",
            normalized=Ok("x"),
            locator="js_state:/html[1]/head[1]/script[1]:$['items'][0]['cost']",
            independent=True,
        )
    return Candidate(
        field="title",
        entity_id=entity_id,
        source_kind="og" if entity_id == PAGE else "jsonld",
        raw="x",
        normalized=Ok("x"),
        locator="meta:og:title" if entity_id == PAGE else f"{entity_id}['name']",
        independent=True,
    )


def test_the_owner_is_the_candidates_entity() -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert graph.owner_of(_candidate(OFFER)) == OFFER
    assert graph.owner_of(_candidate(RELATED)) == RELATED


def test_a_page_entity_is_there_without_a_collector_stating_it() -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert graph.page == Entity(id=PAGE, types=(PAGE,), urls=(), parent=None)
    assert graph.owner_of(_candidate(PAGE)) == graph.page


def test_a_collectors_page_entity_is_kept() -> None:
    graph = EntityGraph.of((*ENTITIES, OG_PAGE), VOCABULARY)
    assert graph.page == OG_PAGE


def test_ancestors_run_from_the_parent_to_the_root() -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert list(graph.ancestors(RELATED_OFFER)) == [RELATED, PRODUCT]
    assert list(graph.ancestors(PRODUCT)) == []


@pytest.mark.parametrize(
    ("owner", "owned"),
    [
        (PRODUCT, True),  # the target's own value
        (PAGE, True),  # page-level values describe the target (§4.6 step 4)
        (OFFER, True),  # an Offer of the target (atomic offers, §4.8)
        (AGGREGATE, True),  # AggregateOffer is an Offer (rdfs:subClassOf)
        (INNER_OFFER, False),  # an Offer of an Offer is not the target's child
        (BRAND, False),  # another thing the target names
        (RELATED, False),  # a related product
        (RELATED_OFFER, False),  # a related product's Offer
        (OTHER, False),  # another top-level product
    ],
)
def test_owned_by_the_target(owner: Entity | str, owned: bool) -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert graph.owned_by(_candidate(owner), PRODUCT) is owned


@pytest.mark.parametrize(
    ("owner", "owned"),
    [
        (GROUP, True),  # the group's own value
        (GROUP_OFFER, True),  # an Offer of the group
        (VARIANT_OFFER, True),  # an Offer of a variant: schema.org `hasVariant` makes the variant a member
        (VARIANT, False),  # the variant's own values (its sku, its name) are the variant's, not the group's
        (VARIANT_BRAND, False),  # another thing a variant names
    ],
)
def test_owned_by_a_product_group(owner: Entity, owned: bool) -> None:
    graph = EntityGraph.of(GROUP_ENTITIES, VOCABULARY)
    assert graph.owned_by(_candidate(owner), GROUP) is owned


def test_a_variants_offer_is_not_owned_by_a_product_that_holds_it_another_way() -> None:
    # Only `hasVariant` makes a nested product a member; under any other property its Offer stays its own.
    nested = RELATED.model_copy(update={"via": "isAccessoryOrSparePartFor"})
    nested_offer = RELATED_OFFER.model_copy(update={"via": "offers"})
    graph = EntityGraph.of((PRODUCT, nested, nested_offer), VOCABULARY)
    assert not graph.owned_by(_candidate(nested_offer), PRODUCT)


def test_when_the_page_is_the_target_only_page_values_are_owned() -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert graph.owned_by(_candidate(PAGE), graph.page)
    assert not graph.owned_by(_candidate(PRODUCT), graph.page)


def test_entity_ids_are_unique_across_collectors() -> None:
    entities = (PRODUCT, PRODUCT.model_copy(update={"kind": "Offer"}))
    with pytest.raises(ValueError, match="duplicate entity id"):
        EntityGraph.of(entities, VOCABULARY)


def test_a_parent_names_an_entity() -> None:
    entities = (OFFER,)
    with pytest.raises(ValueError, match="unknown parent"):
        EntityGraph.of(entities, VOCABULARY)


def test_parents_form_a_tree() -> None:
    # The entity below the cycle comes first, so the check walks into a cycle it is not part of.
    entities = (
        Entity(id="microdata:/c", types=("Offer",), urls=(), parent="microdata:/a"),
        Entity(id="microdata:/a", types=("Product",), urls=(), parent="microdata:/b"),
        Entity(id="microdata:/b", types=("Product",), urls=(), parent="microdata:/a"),
    )
    with pytest.raises(ValueError, match="its own ancestor"):
        EntityGraph.of(entities, VOCABULARY)


def test_an_offer_of_an_entity_of_several_types_is_its_offer() -> None:
    # JSON-LD 1.1 §3.5: a node typed ["CreativeWork", "Product"] is a Product, and its Offer offers it.
    work = Entity(id="jsonld:3:$", types=("CreativeWork", "Product"), urls=(), parent=None)
    offer = Entity(id="jsonld:3:$['offers']", types=("Offer",), urls=(), parent=work.id, via="offers")
    graph = EntityGraph.of((work, offer), VOCABULARY)
    assert graph.offers(work) == (offer,)
    assert graph.owned_by(_candidate(offer), work)


# State array rows (`collect.admission`, Appendix A #55).
PAGE_URL = "https://shop.example.test/p/1"
OTHER_URL = "https://shop.example.test/p/2"


def _row(path: str, *urls: str, parent: str = PAGE) -> Entity:
    return Entity(id=f"js_state:0:$['items']{path}", types=(ARRAY_ROW,), urls=urls, parent=parent)


SELF_ROW = _row("[0]", PAGE_URL)
OTHER_ROW = _row("[1]", OTHER_URL)
BARE_ROW = _row("[2]")
SELF_ROW_PART = _row("[0]['sizes'][0]", f"{PAGE_URL}?size=s", PAGE_URL, parent=SELF_ROW.id)
OTHER_ROW_PART = _row("[1]['sizes'][0]", PAGE_URL, parent=OTHER_ROW.id)
TARGET_ROW = _row("[3]", "https://shop.example.test/w-1")
ROWS = (SELF_ROW, OTHER_ROW, BARE_ROW, SELF_ROW_PART, OTHER_ROW_PART, TARGET_ROW)


@pytest.mark.parametrize(
    ("owner", "owned"),
    [
        (SELF_ROW, True),  # it names the page URL
        (OTHER_ROW, False),  # it names another document only
        (BARE_ROW, False),  # it names nothing: one item among others
        (SELF_ROW_PART, True),  # it and its enclosing row name the page
        (OTHER_ROW_PART, False),  # inside another page's item, whatever it names
        (TARGET_ROW, True),  # it names the target's own URL
    ],
)
def test_a_state_row_is_the_targets_when_it_and_its_enclosing_rows_name_the_target(owner: Entity, owned: bool) -> None:
    target = PRODUCT.model_copy(update={"urls": ("https://shop.example.test/w-1",)})
    graph = EntityGraph.of((target, *ROWS), VOCABULARY, (PAGE_URL,))
    assert graph.owned_by(_candidate(owner), target) is owned


def test_a_state_row_is_never_a_listing_rows() -> None:
    # A listing's rows take no page values (§4.7), so no state row is theirs, even one naming the page.
    graph = EntityGraph.of((PRODUCT, SELF_ROW), VOCABULARY, (PAGE_URL,))
    assert not graph.owned_by(_candidate(SELF_ROW), PRODUCT, page_values=False)
