"""Cold listings (SPEC-05 §4.7 "Listings", ARCHITECTURE §8.6): which of a listing page's entities are its rows.

Rows come from structured data. The entities of the schema's primary types that an `ItemList` lists (directly or
through a `ListItem`) are the rows; an entity inside another primary entity (a row's related item, an item it offers)
is part of that entity, not a row. A page with no listed entity takes its top-level primary entities as rows when there
are at least three and the page URLs single none of them out as the page's own (§4.6): fewer, or one the page names,
is what a detail page looks like. Each row resolves its row-scoped fields like a detail target; page-scoped fields
resolve against the page entity.
"""

from typing import Final

from crawlerai.collect.base import Entity
from crawlerai.resolve.intent import LISTS, AmbiguousTarget, is_primary
from crawlerai.resolve.ownership import EntityGraph

# SPEC-05 §4.7: without an ItemList, at least this many top-level primary entities make a listing's rows.
MIN_TOP_LEVEL_ROWS: Final = 3


def listing_rows(graph: EntityGraph, primary: frozenset[str], target: Entity | AmbiguousTarget) -> tuple[Entity, ...]:
    """The rows (module docstring), in collector order. `target` is intent's answer for the page (§4.6)."""
    primaries = [entity for entity in graph.entities.values() if is_primary(graph, entity, primary)]
    listed = tuple(entity for entity in primaries if _listed(graph, entity, primary))
    if listed:
        return listed
    top_level = tuple(entity for entity in primaries if entity.parent is None)
    if isinstance(target, AmbiguousTarget) and len(top_level) >= MIN_TOP_LEVEL_ROWS:
        return top_level
    return ()


def _listed(graph: EntityGraph, entity: Entity, primary: frozenset[str]) -> bool:
    """Whether the nearest list or primary entity above `entity` is a list (schema.org ItemList, ListItem)."""
    for ancestor in graph.ancestors(entity):
        if any(graph.is_a(ancestor, type_) for type_ in LISTS):
            return True
        if is_primary(graph, ancestor, primary):
            return False
    return False
