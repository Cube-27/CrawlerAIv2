"""Intent (SPEC-05 §4.6, ARCHITECTURE §8.2 rule 3, §10): the one entity a detail page is about, or `intent_ambiguous`.

The candidates are the entities of the schema's primary types, without those inside a list or inside another
primary entity's relation properties. One candidate is the target. Of several, the one whose URLs name the
request, final or canonical URL is; if none or several do, the page is ambiguous and nothing is guessed. A page
with no entity of a primary type at all is about itself, the `page` entity.
"""

from dataclasses import dataclass
from typing import Literal

from crawlerai.collect.base import Entity
from crawlerai.collect.schema_org_map import Vocabulary, parse_path
from crawlerai.normalize.dispatch import equal
from crawlerai.resolve.ownership import OFFER, EntityGraph
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

# schema.org: an ItemList (with its ListItems) lists things, so a thing in it is one of many, not the page's own.
_LISTS = ("ItemList", "ListItem")
# schema.org relation properties of a Product: a thing that is the value of one is another thing than its holder.
_RELATIONS = frozenset({"isRelatedTo", "isSimilarTo"})
_URL = FieldSpec(type=FieldType.URL)


@dataclass(frozen=True, slots=True)
class AmbiguousTarget:
    """No single entity is the target: `candidates` are the entities the page URLs did not settle between."""

    candidates: tuple[str, ...]
    reason: Literal["intent_ambiguous"] = "intent_ambiguous"


def primary_types(schema: SchemaDef, vocabulary: Vocabulary) -> frozenset[str]:
    """The types the schema's required fields' `schema_org` paths start at, without Offer when another type remains:
    an Offer belongs to the item it offers (`OFFER`)."""
    roots = {parse_path(spec.schema_org).root for spec in schema.fields.values() if spec.required and spec.schema_org}
    items = frozenset(root for root in roots if not vocabulary.is_a(root, OFFER))
    return items or frozenset(roots)


def select_target(
    request_url: str,
    final_url: str,
    canonical_url: str | None,
    graph: EntityGraph,
    primary: frozenset[str],
) -> Entity | AmbiguousTarget:
    primaries = [e for e in graph.entities.values() if _is_primary(graph, e, primary)]
    if not primaries:
        return graph.page
    candidates = [e for e in primaries if not _excluded(graph, e, primary)]
    if len(candidates) == 1:
        return candidates[0]
    page_urls = [url for url in (request_url, final_url, canonical_url) if url is not None]
    named = [e for e in candidates if _names_any(e, page_urls)]
    if len(named) == 1:
        return named[0]
    return AmbiguousTarget(tuple(e.id for e in named or candidates))


def _is_primary(graph: EntityGraph, entity: Entity, primary: frozenset[str]) -> bool:
    return any(graph.is_a(entity, type_) for type_ in primary)


def _names_any(entity: Entity, page_urls: list[str]) -> bool:
    # URL equality is the url type's (SPEC-04 §4.5): equal after canonicalization.
    return any(equal(own, url, _URL) for own in entity.urls for url in page_urls)


def _excluded(graph: EntityGraph, entity: Entity, primary: frozenset[str]) -> bool:
    """Whether the entity is inside a list, or inside a relation property of a primary entity (§4.6 step 1)."""
    child = entity
    for ancestor in graph.ancestors(entity):
        if any(graph.is_a(ancestor, t) for t in _LISTS):
            return True
        if child.via in _RELATIONS and _is_primary(graph, ancestor, primary):
            return True
        child = ancestor
    return False
