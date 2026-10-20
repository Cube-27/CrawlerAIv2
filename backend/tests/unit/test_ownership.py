"""Ownership (extraction spec rule 3): a candidate belongs to the entity that holds it, and only
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
ADD_ON = Entity(  # an Offer an Offer names otherwise (`addOn`): another item's
    id="jsonld:0:$['offers']['addOn']", types=("Offer",), urls=(), parent=OFFER.id, via="addOn"
)
BRAND = Entity(id="jsonld:0:$['brand']", types=("Brand",), urls=(), parent=PRODUCT.id, via="brand")
RELATED = Entity(id="jsonld:0:$['isRelatedTo']", types=("Product",), urls=(), parent=PRODUCT.id, via="isRelatedTo")
RELATED_OFFER = Entity(id="jsonld:0:$['isRelatedTo']['offers']", types=("Offer",), urls=(), parent=RELATED.id)
OTHER = Entity(id="jsonld:1:$", types=("Product",), urls=(), parent=None)

ENTITIES = (PRODUCT, OFFER, AGGREGATE, INNER_OFFER, ADD_ON, BRAND, RELATED, RELATED_OFFER, OTHER)


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


@pytest.mark.parametrize(
    ("owner", "owned"),
    [
        (PRODUCT, True),  # the target's own value
        (PAGE, True),  # page-level values describe the target (§4.6 step 4)
        (OFFER, True),  # an Offer of the target (atomic offers, §4.8)
        (AGGREGATE, True),  # AggregateOffer is an Offer (rdfs:subClassOf)
        (INNER_OFFER, True),  # an AggregateOffer's Offers offer the same item (schema.org `offers`)
        (ADD_ON, False),  # an Offer an Offer holds otherwise than as its `offers`
        (BRAND, False),  # another thing the target names
        (RELATED, False),  # a related product
        (RELATED_OFFER, False),  # a related product's Offer
        (OTHER, False),  # another top-level product
    ],
)
def test_owned_by_the_target(owner: Entity | str, owned: bool) -> None:
    graph = EntityGraph.of(ENTITIES, VOCABULARY)
    assert graph.owned_by(_candidate(owner), PRODUCT) is owned


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
