"""What every collector shares (SPEC-05 §4.1, §4.2, ARCHITECTURE §8.1): the entities it finds, the candidates it
proposes for schema fields, and the `Collector` protocol.

A collector proposes; it never chooses. Ownership, intent and preference are `crawlerai.resolve`'s.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from crawlerai.collect.locator import LocatorText
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, NormalizeResult, Raw
from crawlerai.schemas.types import SchemaDef

# The page itself, as an entity: what page-level values (Open Graph, meta, cleaned text) belong to (§4.6).
PAGE = "page"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(_Model):
    """A thing on the page that fields belong to: a structured-data node (`jsonld:0:$['@graph'][2]`,
    `microdata:/html[1]/body[1]/div[3]`), an adapter's object (`adapter:job`), or the page itself (`page`)."""

    id: str
    kind: str  # the schema.org type name when known (`Product`, `Offer`, `ItemList`), else `page`
    urls: tuple[str, ...]  # canonicalized url, @id, mainEntityOfPage and offers.url values found on the entity
    parent: str | None
    # The schema.org property of the parent whose value holds this entity (`offers`, `isRelatedTo`); None for a root,
    # or when the source names no schema.org property. Intent reads it (§4.6 step 1).
    via: str | None = None


class Candidate(_Model):
    """One value a collector proposed for one field of one entity (the `candidate` row, ARCHITECTURE §6)."""

    field: str
    entity_id: str
    source_kind: SourceKind
    raw: Raw  # as the source holds it: a DOM string, or a JSON value from structured data
    normalized: NormalizeResult
    locator: LocatorText
    independent: bool  # False for js_state/xhr values admitted only by equality to another candidate (§8.1)


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
        for candidate in self.candidates:
            if candidate.entity_id not in ids:
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
    and normalizes each raw value with `ctx` (SPEC-04)."""

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
