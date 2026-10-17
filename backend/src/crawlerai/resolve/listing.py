"""Cold listings (SPEC-05 §4.7 "Listings", ARCHITECTURE §8.6): which of a listing page's entities are its rows.

Rows come from structured data. The entities of the schema's primary types that an `ItemList` lists (directly or
through a `ListItem`) are the rows; an entity inside another primary entity (a row's related item, an item it offers)
is part of that entity, not a row. A page with no listed entity takes its top-level primary entities as rows when there
are at least three and the page URLs single none of them out as the page's own (§4.6): fewer, or one the page names,
is what a detail page looks like. Each row resolves its row-scoped fields like a detail target; page-scoped fields
resolve against the page entity.

A page often states its items in two syntaxes (JSON-LD and microdata): the entity graph has already merged them into
one entity (`resolve.identity`), so the item is one row with the values of both.

A list may state its entries as ListItems with their own `name` and `url` and no `item`: schema.org types `item` as a
Thing and gives a ListItem a Thing's properties, so an entry without an item stands for the thing it lists. When the
page lists no entity of a primary type and has too few top-level ones, the entries the collectors read as items
(`schema_org_map.field_candidates`: a listing's row fields) are the rows. A BreadcrumbList's entries are never rows:
schema.org defines it as "a chain of linked Web pages" leading to the current page, its navigation, not its items.
"""

from typing import Final

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect.base import Entity
from crawlerai.collect.schema_org_map import ENTRY
from crawlerai.resolve.identity import LISTS
from crawlerai.resolve.intent import AmbiguousTarget, is_primary
from crawlerai.resolve.ownership import EntityGraph

# SPEC-05 §4.7: without an ItemList, at least this many top-level primary entities make a listing's rows; the same
# count of repeated items makes a page show a listing's grid (`acquire.items`).
MIN_TOP_LEVEL_ROWS: Final = MIN_ITEMS
# schema.org BreadcrumbList: "an ItemList consisting of a chain of linked Web pages ... typically ending with the
# current page".
_TRAIL: Final = "BreadcrumbList"


def listing_rows(
    graph: EntityGraph,
    primary: frozenset[str],
    target: Entity | AmbiguousTarget,
    holders: frozenset[str] = frozenset(),
) -> tuple[Entity, ...]:
    """The rows (module docstring), in collector order. `target` is intent's answer for the page (§4.6); `holders` are
    the entities holding a candidate of a row field."""
    primaries = [entity for entity in graph.entities.values() if is_primary(graph, entity, primary)]
    rows = [entity for entity in primaries if _listed(graph, entity, primary)]
    top_level = [entity for entity in primaries if entity.parent is None]
    if not rows and isinstance(target, AmbiguousTarget) and len(top_level) >= MIN_TOP_LEVEL_ROWS:
        rows = top_level
    if not rows:
        rows = [entity for entity in graph.entities.values() if entity.id in holders and _entry(graph, entity)]
    return tuple(rows)


def _entry(graph: EntityGraph, entity: Entity) -> bool:
    """Whether the entity is a list's entry (schema.org ListItem) outside a breadcrumb trail."""
    return graph.is_a(entity, ENTRY) and not any(graph.is_a(a, _TRAIL) for a in graph.ancestors(entity))


def _listed(graph: EntityGraph, entity: Entity, primary: frozenset[str]) -> bool:
    """Whether the nearest list or primary entity above `entity` is a list (schema.org ItemList, ListItem)."""
    for ancestor in graph.ancestors(entity):
        if any(graph.is_a(ancestor, type_) for type_ in LISTS):
            return True
        if is_primary(graph, ancestor, primary):
            return False
    return False
