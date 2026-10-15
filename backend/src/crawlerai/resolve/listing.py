"""Cold listings (SPEC-05 §4.7 "Listings", ARCHITECTURE §8.6): which of a listing page's entities are its rows.

Rows come from structured data. The entities of the schema's primary types that an `ItemList` lists (directly or
through a `ListItem`) are the rows; an entity inside another primary entity (a row's related item, an item it offers)
is part of that entity, not a row. A page with no listed entity takes its top-level primary entities as rows when there
are at least three and the page URLs single none of them out as the page's own (§4.6): fewer, or one the page names,
is what a detail page looks like. Each row resolves its row-scoped fields like a detail target; page-scoped fields
resolve against the page entity.

A page often states its items in two syntaxes (JSON-LD and microdata). A row another collector's earlier row shares a
URL with is that item again, not another row (schema.org `url` and `@id` name the item), and is left out; a URL that
names the page names no item. Rows of one collector are never merged here: the records keep a URL listed twice once.
"""

from collections.abc import Sequence
from typing import Final

from crawlerai.collect.base import Entity
from crawlerai.resolve.intent import LISTS, AmbiguousTarget, is_primary
from crawlerai.resolve.ownership import EntityGraph

# SPEC-05 §4.7: without an ItemList, at least this many top-level primary entities make a listing's rows.
MIN_TOP_LEVEL_ROWS: Final = 3


def listing_rows(
    graph: EntityGraph, primary: frozenset[str], target: Entity | AmbiguousTarget, page_urls: Sequence[str]
) -> tuple[Entity, ...]:
    """The rows (module docstring), in collector order. `target` is intent's answer for the page (§4.6); `page_urls`
    are the request, final and canonical URLs, canonicalized."""
    primaries = [entity for entity in graph.entities.values() if is_primary(graph, entity, primary)]
    listed = [entity for entity in primaries if _listed(graph, entity, primary)]
    if listed:
        return _one_per_item(listed, frozenset(page_urls))
    top_level = [entity for entity in primaries if entity.parent is None]
    if isinstance(target, AmbiguousTarget) and len(top_level) >= MIN_TOP_LEVEL_ROWS:
        return _one_per_item(top_level, frozenset(page_urls))
    return ()


def _one_per_item(rows: Sequence[Entity], page_urls: frozenset[str]) -> tuple[Entity, ...]:
    """The rows without those another collector's earlier row shares an item URL with. `Entity.urls` are canonical."""
    kept: list[Entity] = []
    for row in rows:
        urls = set(row.urls) - page_urls
        if not any(_collector(k) != _collector(row) and not urls.isdisjoint(k.urls) for k in kept):
            kept.append(row)
    return tuple(kept)


def _collector(entity: Entity) -> str:
    # An entity id starts with its collector's locator scheme (`jsonld:`, `microdata:`, SPEC-05 §4.3).
    return entity.id.partition(":")[0]


def _listed(graph: EntityGraph, entity: Entity, primary: frozenset[str]) -> bool:
    """Whether the nearest list or primary entity above `entity` is a list (schema.org ItemList, ListItem)."""
    for ancestor in graph.ancestors(entity):
        if any(graph.is_a(ancestor, type_) for type_ in LISTS):
            return True
        if is_primary(graph, ancestor, primary):
            return False
    return False
