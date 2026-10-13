"""Ownership (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3): a candidate belongs to the entity that holds it, and only
the target's own candidates, the page's, and those of an Offer of the target are the target's."""

from pathlib import Path

import pytest

from crawlerai.collect.base import PAGE, Candidate, Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.normalize.base import Ok
from crawlerai.resolve.ownership import EntityGraph

VOCABULARY = Vocabulary.read(Path(__file__).parents[1] / "fixtures" / "synthetic" / "schemaorg_vocabulary.jsonld")

PRODUCT = Entity(id="jsonld:0:$", kind="Product", urls=(), parent=None)
OFFER = Entity(id="jsonld:0:$['offers']", kind="Offer", urls=(), parent=PRODUCT.id, via="offers")
AGGREGATE = Entity(id="jsonld:0:$['offers'][1]", kind="AggregateOffer", urls=(), parent=PRODUCT.id, via="offers")
INNER_OFFER = Entity(id="jsonld:0:$['offers'][1]['offers']", kind="Offer", urls=(), parent=AGGREGATE.id, via="offers")
BRAND = Entity(id="jsonld:0:$['brand']", kind="Brand", urls=(), parent=PRODUCT.id, via="brand")
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", kind="Product", urls=(), parent=PRODUCT.id, via="isRelatedTo")
RELATED_OFFER = Entity(id="jsonld:0:$['isRelatedTo']['offers']", kind="Offer", urls=(), parent=RELATED.id)
OTHER = Entity(id="jsonld:1:$", kind="Product", urls=(), parent=None)
OG_PAGE = Entity(id=PAGE, kind=PAGE, urls=("https://shop.example.test/p/1",), parent=None)

ENTITIES = (PRODUCT, OFFER, AGGREGATE, INNER_OFFER, BRAND, RELATED, RELATED_OFFER, OTHER)


def _candidate(entity: Entity | str) -> Candidate:
    entity_id = entity if isinstance(entity, str) else entity.id
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
    assert graph.page == Entity(id=PAGE, kind=PAGE, urls=(), parent=None)
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
        Entity(id="microdata:/c", kind="Offer", urls=(), parent="microdata:/a"),
        Entity(id="microdata:/a", kind="Product", urls=(), parent="microdata:/b"),
        Entity(id="microdata:/b", kind="Product", urls=(), parent="microdata:/a"),
    )
    with pytest.raises(ValueError, match="its own ancestor"):
        EntityGraph.of(entities, VOCABULARY)
