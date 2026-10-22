"""What every collector shares (extraction spec): the entities it finds, the candidates it
proposes for schema fields, and the `Collector` protocol.

A collector proposes; it never chooses. Ownership, intent and preference are `crawlerai.resolve`'s.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from crawlerai.collect.locator import LocatorText
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, NormalizeResult, Ok, Raw
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# The page itself, as an entity: what page-level values (Open Graph, meta, cleaned text) belong to (§4.6).
PAGE = "page"
# An object item of a JSON array holding two or more objects, in JSON without standard keys (`js_state`, `xhr`): one of
# a set of items, not its document's subject (`collect.admission`). It is no schema.org type.
ARRAY_ROW = "array_row"
# A block of the page's repeated item group that holds one item's link: a listing row the item layer read from the DOM
# (`collect.items.align`). It is no schema.org type.
ITEM_BLOCK = "item_block"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(_Model):
    """A thing on the page that fields belong to: a structured-data node (`jsonld:0:$['@graph'][2]`,
    `microdata:/html[1]/body[1]/div[3]`), an adapter's object (`adapter:job`), or the page itself (`page`)."""

    id: str
    # The schema.org type names when known (`Product`, `Offer`, `ItemList`), most specific first, else (`page`): a
    # node is an instance of each of its types (JSON-LD 1.1 §3.5 `@type`; HTML microdata: an `itemtype` list).
    types: tuple[str, ...] = Field(min_length=1)
    urls: tuple[str, ...]  # canonicalized url, @id, mainEntityOfPage and offers.url values found on the entity
    parent: str | None
    # The schema.org property of the parent whose value holds this entity (`offers`, `isRelatedTo`); None for a root,
    # or when the source names no schema.org property. Intent reads it (§4.6 step 1).
    via: str | None = None
    # What identifies the item (`schema_org_map.identity`): its IRI and its schema.org identifier values, as
    # (property, value) pairs; resolution merges the entities that share one (`resolve.identity`).
    identity: tuple[tuple[str, str], ...] = ()
    # The canonical URLs naming the item itself (`schema_org_map.item_urls`), not its offers'.
    item_urls: tuple[str, ...] = ()
    # schema.org `inProductGroupWithID`: the `productGroupID` of the ProductGroup this product is a variant of.
    group_ids: tuple[str, ...] = ()
    # schema.org `isVariantOf`: the IRIs (`@id`, `itemid`) of the nodes this product names as what it is a variant of.
    variant_of: tuple[str, ...] = ()
    # Whether its source already checked that it states the requested item: the root of an identity-checked data
    # call's answer (acquisition spec "Data calls"). Identity merges it into the page's own item (`resolve.identity`).
    requested: bool = False
    # A schema.org AggregateOffer's price range: its `lowPrice` and `highPrice` when they differ, with its
    # `priceCurrency` (None: unknown). The item's offers' prices span it; resolution reads its bounds
    # (`resolve.preference`, range bounds).
    price_range: tuple[Decimal, Decimal, str | None] | None = None


class Candidate(_Model):
    """One value a collector proposed for one field of one entity (the `candidate` row)."""

    field: str
    entity_id: str
    source_kind: SourceKind
    raw: Raw  # as the source holds it: a DOM string, or a JSON value from structured data
    normalized: NormalizeResult
    locator: LocatorText
    independent: bool  # False for js_state/xhr values admitted only by equality to another candidate (§8.1)


def is_visible_amount(c: Candidate, spec: FieldSpec) -> bool:
    """Whether `c` is an amount the page shows of a money field (resolution spec, "the visible price"): a rendered `dom`
    value read as an amount, on its own evidence (not admitted by equality to another candidate, §8.1)."""
    item = spec.item.type if spec.type is FieldType.LIST and spec.item is not None else spec.type
    return item is FieldType.MONEY and c.source_kind == "dom" and c.independent and isinstance(c.normalized, Ok)


class CollectResult(_Model):
    entities: tuple[Entity, ...]
    candidates: tuple[Candidate, ...]
    # What the collector skipped and why (an invalid JSON block); a collector never raises on page content (§4.5).
    diagnostics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        # Ownership walks entity ids and parents (§8.2 rule 3), so each one must name an entity of this result.
        ids = {entity.id for entity in self.entities}
        if len(ids) != len(self.entities):
            raise ValueError("duplicate entity id")
        for entity in self.entities:
            if entity.parent is not None and entity.parent not in ids:
                raise ValueError(f"entity {entity.id!r} has unknown parent {entity.parent!r}")
        _check_tree(self.entities)
        # The page entity is always present (`EntityGraph.of` adds it), so a page-level candidate needs no entity here.
        for candidate in self.candidates:
            if candidate.entity_id != PAGE and candidate.entity_id not in ids:
                raise ValueError(f"candidate for {candidate.field!r} names unknown entity {candidate.entity_id!r}")
        return self


def _check_tree(entities: Sequence[Entity]) -> None:
    # Entities form a tree (§4.6): walking up the parents from any entity ends at a root.
    parents = {entity.id: entity.parent for entity in entities}
    for entity in entities:
        if descends(entity.parent, entity.id, parents):
            raise ValueError(f"entity {entity.id!r} is its own ancestor")


class Collector(Protocol):
    """One source kind's collector. It reads the page's parsed trees and script blocks, never the raw body (INV-26),
    and normalizes each raw value with `ctx` (schemas spec)."""

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult: ...


def descends(entity: str | None, ancestor: str, parents: Mapping[str, str | None]) -> bool:
    """Whether `entity` is `ancestor` or below it in `parents`; a collector checks it before giving a node a parent, so
    that entities stay a tree (§4.6)."""
    seen: set[str] = set()
    while entity is not None and entity not in seen:  # a walk into a cycle without `ancestor` ends
        if entity == ancestor:
            return True
        seen.add(entity)
        entity = parents[entity]
    return False
