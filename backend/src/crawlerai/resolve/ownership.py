"""Ownership (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3, §10): a candidate belongs to the entity whose JSON object or
DOM subtree holds it, and the page's entities form a tree under their parents.

A candidate is the target's when the target holds it, when the page holds it (page-level values describe what the
page is about), or when an Offer of the target holds it (atomic offers, §4.8). Any other candidate is not owned and
never publishes.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from crawlerai.collect.base import PAGE, Candidate, CollectResult, Entity
from crawlerai.collect.schema_org_map import Vocabulary

# schema.org: an Offer is the offer of an item (`offers` / `itemOffered`), so its price and availability are the
# item's (§4.5: Offer values are owned by the Offer whose parent is the Product).
OFFER = "Offer"


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
        return owner.parent == target.id and self.is_a(owner, OFFER)
