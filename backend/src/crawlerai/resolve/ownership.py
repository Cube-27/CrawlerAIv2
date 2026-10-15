"""Ownership (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3, §10): a candidate belongs to the entity whose JSON object or
DOM subtree holds it, and the page's entities form a tree under their parents.

A candidate is the target's when the target holds it, when the page holds it (page-level values describe what the
page is about), or when an Offer of the target or of one of its variants holds it (atomic offers, §4.8). Any other
candidate is not owned and never publishes.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from crawlerai.collect.base import PAGE, Candidate, CollectResult, Entity
from crawlerai.collect.schema_org_map import Vocabulary

# schema.org: an Offer is the offer of an item (`offers` / `itemOffered`), so its price and availability are the
# item's (§4.5: Offer values are owned by the Offer whose parent is the Product).
OFFER = "Offer"
# schema.org `hasVariant`: "Indicates a Product that is a member of this ProductGroup". A variant is part of its group,
# not another thing the page is about, and its Offer offers the group's product too: it joins the group's Offers under
# the atomic-offer rule. The variant's own values (its sku, its name) stay the variant's.
VARIANT = "hasVariant"
# schema.org: an AggregateOffer is "a summary of all the offers" of an item, not the offer of one variant (SPEC-13
# §4.3), so it is never a variant holder.
AGGREGATE_OFFER = "AggregateOffer"


@dataclass(frozen=True, slots=True)
class EntityGraph:
    """The page's entities from every collector, by id, with the page entity always among them."""

    entities: Mapping[str, Entity]
    vocabulary: Vocabulary

    @classmethod
    def of(cls, entities: Iterable[Entity], vocabulary: Vocabulary) -> "EntityGraph":
        """Every collector's entities as one result: ids unique, parents resolved, a tree (`CollectResult`)."""
        merged = list(entities)
        if all(entity.id != PAGE for entity in merged):
            merged.append(Entity(id=PAGE, kind=PAGE, urls=(), parent=None))
        result = CollectResult(entities=tuple(merged), candidates=())
        return cls({entity.id: entity for entity in result.entities}, vocabulary)

    @property
    def page(self) -> Entity:
        return self.entities[PAGE]

    def owner_of(self, candidate: Candidate) -> Entity:
        return self.entities[candidate.entity_id]

    def ancestors(self, entity: Entity) -> Iterator[Entity]:
        """The entity's parent, its parent's parent, and so on to the root."""
        while entity.parent is not None:
            entity = self.entities[entity.parent]
            yield entity

    def is_a(self, entity: Entity, type_: str) -> bool:
        return self.vocabulary.is_a(entity.kind, type_)

    def owned_by(self, candidate: Candidate, target: Entity, *, page_values: bool = True) -> bool:
        """Whether the candidate is the target's. `page_values`: whether the page's own values are, as they are for
        the one entity a detail page is about, and not for one row among a listing's (§4.7 "Listings")."""
        owner = self.owner_of(candidate)
        if owner.id == target.id or (page_values and owner.id == PAGE):
            return True
        if owner.parent is None or not self.is_a(owner, OFFER):
            return False
        holder = self.entities[owner.parent]
        return holder.id == target.id or (holder.via == VARIANT and holder.parent == target.id)

    def holders(self, target: Entity) -> tuple[Entity, ...]:
        """The target's variant holders (SPEC-13 §4.6): its `hasVariant` members and the Offers directly under it,
        an AggregateOffer excepted."""
        return tuple(
            e for e in self.entities.values() if e.parent == target.id and (e.via == VARIANT or self._single_offer(e))
        )

    def variants(self, target: Entity) -> tuple[Entity, ...]:
        """The target's `hasVariant` members."""
        return tuple(e for e in self.entities.values() if e.parent == target.id and e.via == VARIANT)

    def offers_of(self, holder: Entity) -> frozenset[str]:
        """The Offers a variant holder stands for: itself when it is an Offer, else the Offers directly under it. An
        AggregateOffer is none: it summarizes several offers, not an offer of one item (SPEC-13 §4.3)."""
        if self.is_a(holder, OFFER):
            return frozenset({holder.id})
        return frozenset(e.id for e in self.entities.values() if e.parent == holder.id and self._single_offer(e))

    def _single_offer(self, entity: Entity) -> bool:
        return self.is_a(entity, OFFER) and not self.is_a(entity, AGGREGATE_OFFER)
