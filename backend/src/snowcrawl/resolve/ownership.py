"""Ownership: a candidate belongs to the entity whose JSON object or
DOM subtree holds it, and the page's entities form a tree under their parents.

A candidate is the target's when the target holds it, when the page holds it (page-level values describe what the
page is about), or when an Offer of the target or of one of its variants holds it (atomic offers). A state
array row's value (`collect.admission`) is the target's where page values are, when the row and every row enclosing it
names the target: one of its URLs is a page URL or the target's (Appendix A #55). An AggregateRating stated apart
from the item (`collect.schema_org_map.RATING`) is the target's when the target is the page's one primary entity,
states no rating of its own, and every such rating on the page, standing alone or within the target but in no Offer,
states the same values (`EntityGraph.ratings_apart`). Any other candidate is not owned and never publishes.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import takewhile

from snowcrawl.collect.base import ARRAY_ROW, PAGE, Candidate, CollectResult, Entity
from snowcrawl.collect.schema_org_map import AGGREGATE_RATING, RATING
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.normalize.dispatch import equal
from snowcrawl.resolve.identity import VARIANT, identify
from snowcrawl.schemas.types import FieldSpec, FieldType

# schema.org: an Offer is the offer of an item (`offers` / `itemOffered`), so its price and availability are the
# item's (§4.5: Offer values are owned by the Offer whose parent is the Product).
OFFER = "Offer"
# Schema.org: an AggregateOffer is "a summary of all the offers" of an item, not the offer of one variant, so it is
# never a variant holder.
AGGREGATE_OFFER = "AggregateOffer"
_URL = FieldSpec(type=FieldType.URL)
# schema.org `offers`: "An offer to provide this item".
_OFFERS = "offers"


@dataclass(frozen=True, slots=True)
class EntityGraph:
    """The page's entities from every collector, by id, each item once (`resolve.identity`), with the page entity
    always among them."""

    entities: Mapping[str, Entity]
    vocabulary: Vocabulary
    # The URLs naming the page (`collect.run`'s `page_urls`): what a row names to be the page's subject.
    page_urls: tuple[str, ...] = ()
    aliases: Mapping[str, str] = field(default_factory=dict)  # a merged entity's id -> the entity it is part of

    @classmethod
    def of(cls, entities: Iterable[Entity], vocabulary: Vocabulary, page_urls: Sequence[str] = ()) -> "EntityGraph":
        """Every collector's entities as one result: each item once, ids unique, parents resolved, a tree
        (`CollectResult`)."""
        found = list(entities)
        if all(entity.id != PAGE for entity in found):
            found.append(Entity(id=PAGE, types=(PAGE,), urls=(), parent=None))
        checked = CollectResult(entities=tuple(found), candidates=())
        identified = identify(checked.entities, vocabulary, page_urls)
        result = CollectResult(entities=identified.entities, candidates=())
        entities_by_id = {entity.id: entity for entity in result.entities}
        return cls(entities_by_id, vocabulary, tuple(page_urls), identified.aliases)

    def adopt(self, candidates: Iterable[Candidate]) -> tuple[Candidate, ...]:
        """The candidates with those of a merged entity moved to the entity it is part of."""
        return tuple(
            c.model_copy(update={"entity_id": self.aliases[c.entity_id]}) if c.entity_id in self.aliases else c
            for c in candidates
        )

    def ratings_apart(self, target: Entity, candidates: Sequence[Candidate]) -> tuple[Candidate, ...]:
        """The candidates with those of the AggregateRatings stated apart from `target` moved to it, when they are its
        (module docstring); `target` must be the page's one primary entity, which the caller knows. A rating within
        an Offer rates its seller or the offer, and one under another entity rates that entity, so neither counts;
        ratings apart that differ are several things rated, so none is the target's."""
        if any(e.parent == target.id and e.via == RATING for e in self.entities.values()):
            return tuple(candidates)
        apart = {e.id for e in self.entities.values() if self._rates_apart(e, target)}
        stated = {
            entity_id: sorted(repr((c.field, c.normalized)) for c in candidates if c.entity_id == entity_id)
            for entity_id in apart
        }
        if len({tuple(values) for values in stated.values()}) != 1:
            return tuple(candidates)
        return tuple(c.model_copy(update={"entity_id": target.id}) if c.entity_id in apart else c for c in candidates)

    def _rates_apart(self, entity: Entity, target: Entity) -> bool:
        """Whether `entity` is an AggregateRating not held as `target`'s own, standing alone or within `target` but in
        no Offer."""
        if not self.is_a(entity, AGGREGATE_RATING) or entity.parent == target.id:
            return False
        holders = list(self.ancestors(entity))
        if any(self.is_a(holder, OFFER) for holder in holders):
            return False
        return not holders or holders[-1].id == target.id

    def merges(self) -> tuple[str, ...]:
        """A diagnostic per merged entity."""
        return tuple(f"identity: {alias} is the item {head}" for alias, head in self.aliases.items())

    @property
    def page(self) -> Entity:
        return self.entities[PAGE]

    def owner_of(self, candidate: Candidate) -> Entity:
        return self.entities[self.aliases.get(candidate.entity_id, candidate.entity_id)]

    def ancestors(self, entity: Entity) -> Iterator[Entity]:
        """The entity's parent, its parent's parent, and so on to the root."""
        while entity.parent is not None:
            entity = self.entities[entity.parent]
            yield entity

    def is_a(self, entity: Entity, type_: str) -> bool:
        return any(self.vocabulary.is_a(t, type_) for t in entity.types)

    def owned_by(self, candidate: Candidate, target: Entity, *, page_values: bool = True) -> bool:
        """Whether the candidate is the target's. `page_values`: whether the page's own values are, as they are for
        the one entity a detail page is about, and not for one row among a listing's (§4.7 "Listings")."""
        owner = self.owner_of(candidate)
        if owner.id == target.id or (page_values and owner.id == PAGE):
            return True
        if ARRAY_ROW in owner.types:
            return page_values and self._names_target(owner, target)
        holder = self.offered(owner)
        if holder is owner:
            return False
        return holder.id == target.id or (holder.via == VARIANT and holder.parent == target.id)

    def offered(self, entity: Entity) -> Entity:
        """The item an Offer offers: its parent, through the Offers between that hold it as their `offers` (schema.org:
        an AggregateOffer's `offers` are Offers of the same item); `entity` itself when it is no Offer, no item holds
        it, or an Offer holds it otherwise."""
        holder = entity
        while self.is_a(holder, OFFER) and holder.parent is not None:
            parent = self.entities[holder.parent]
            if self.is_a(parent, OFFER) and holder.via != _OFFERS:
                return entity
            holder = parent
        return entity if self.is_a(holder, OFFER) else holder

    def _names_target(self, row: Entity, target: Entity) -> bool:
        """Whether an array row and every row enclosing it names the page's subject: one of its URLs equals a page URL
        or one of the target's. A row naming only other documents, or none, is one item among others, and a row inside
        another page's item belongs to that item."""
        subject = (*self.page_urls, *target.urls)
        rows = [row, *takewhile(lambda e: ARRAY_ROW in e.types, self.ancestors(row))]
        return all(names_any(e, subject) for e in rows)

    def offers(self, target: Entity) -> tuple[Entity, ...]:
        """The Offers directly under the target, an AggregateOffer excepted: it summarizes several offers, not an offer
        of one item."""
        return tuple(e for e in self.entities.values() if e.parent == target.id and self._single_offer(e))

    def variants(self, target: Entity) -> tuple[Entity, ...]:
        """The target's `hasVariant` members."""
        return tuple(e for e in self.entities.values() if e.parent == target.id and e.via == VARIANT)

    def _single_offer(self, entity: Entity) -> bool:
        return self.is_a(entity, OFFER) and not self.is_a(entity, AGGREGATE_OFFER)


def names_any(entity: Entity, urls: Sequence[str]) -> bool:
    """Whether one of the entity's URLs is one of `urls`; URL equality is the url type's: equal after
    canonicalization."""
    return any(equal(own, url, _URL) for own in entity.urls for url in urls)


def names_item(entity: Entity, url: str) -> bool:
    """Whether `url` is one of the URLs naming the item itself (`Entity.item_urls`, not its offers'), by the url type's
    equality."""
    return any(equal(own, url, _URL) for own in entity.item_urls)
