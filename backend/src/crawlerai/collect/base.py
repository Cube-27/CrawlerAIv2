"""What every collector shares (SPEC-05 §4.1, §4.2, ARCHITECTURE §8.1): the entities it finds, the candidates it
proposes for schema fields, and the `Collector` protocol.

A collector proposes; it never chooses. Ownership, intent and preference are `crawlerai.resolve`'s.
"""

from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, model_validator

from crawlerai.collect.locator import LocatorText
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import SourceKind
from crawlerai.normalize.base import Context, NormalizeResult, Raw
from crawlerai.schemas.types import SchemaDef


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Entity(_Model):
    """A thing on the page that fields belong to: a structured-data node (`jsonld:0:$['@graph'][2]`,
    `microdata:/html[1]/body[1]/div[3]`), an adapter's object (`adapter:job`), or the page itself (`page`)."""

    id: str
    kind: str  # the schema.org type name when known (`Product`, `Offer`, `ItemList`), else `page`
    urls: tuple[str, ...]  # canonicalized url, @id, mainEntityOfPage and offers.url values found on the entity
    parent: str | None


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
        for candidate in self.candidates:
            if candidate.entity_id not in ids:
                raise ValueError(f"candidate for {candidate.field!r} names unknown entity {candidate.entity_id!r}")
        return self


class Collector(Protocol):
    """One source kind's collector. It reads the page's parsed trees and script blocks, never the raw body (INV-26),
    and normalizes each raw value with `ctx` (SPEC-04)."""

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult: ...
