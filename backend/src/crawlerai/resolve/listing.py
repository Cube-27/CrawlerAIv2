"""Cold listings (resolution): which of a listing page's entities are its rows.

Rows come from structured data. The entities of the schema's primary types that an `ItemList` lists (directly or through
a `ListItem`) are the rows; an entity inside another primary entity (a row's related item, an item it offers) is part of
that entity, not a row. A page with no listed entity takes its top-level primary entities as rows when there are at
least three and the page URLs single none of them out as the page's own: fewer, or one the page names, is what a
detail page looks like. When the page singles none out, a top-level primary entity that no list holds is a row beside
the listed ones too: a list that grew after its script was written (a load-more, a scroll) states its later items in the
grown document only, as microdata, while the script keeps the first batch. Each row resolves its row-scoped fields like
a detail target; page-scoped fields resolve against the page entity.

A page often states its items in two syntaxes (JSON-LD and microdata): the entity graph has already merged them into
one entity (`resolve.identity`), so the item is one row with the values of both.

A list may state its entries as ListItems with their own `name` and `url` and no `item`: schema.org types `item` as a
Thing and gives a ListItem a Thing's properties, so an entry without an item stands for the thing it lists. When the
page lists no entity of a primary type and has too few top-level ones, the entries the collectors read as items
(`schema_org_map.field_candidates`: a listing's row fields) are the rows. A BreadcrumbList's entries are never rows:
schema.org defines it as "a chain of linked Web pages" leading to the current page, its navigation, not its items.
"""

from collections.abc import Sequence
from typing import Final

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect.base import Entity
from crawlerai.collect.schema_org_map import ENTRY
from crawlerai.collect.scope import LISTS
from crawlerai.resolve.intent import AmbiguousTarget, is_primary
from crawlerai.resolve.ownership import EntityGraph

# without an ItemList, at least this many top-level primary entities make a listing's rows; the same
# count of repeated items makes a page show a listing's grid (`acquire.items`).
MIN_TOP_LEVEL_ROWS: Final = MIN_ITEMS
# schema.org BreadcrumbList: "an ItemList consisting of a chain of linked Web pages ... typically ending with the
# current page".
_TRAIL: Final = "BreadcrumbList"
_LIST: Final = "ItemList"
# schema.org WebPage.mainEntity: "Indicates the primary entity described in some page or other CreativeWork".
_MAIN_ENTITY: Final = "mainEntity"


def listing_rows(
    graph: EntityGraph,
    primary: frozenset[str],
    target: Entity | AmbiguousTarget,
    holders: frozenset[str] = frozenset(),
) -> tuple[Entity, ...]:
    """The rows (module docstring), in collector order. `target` is intent's answer for the page; `holders` are
    the entities holding a candidate of a row field."""
    primaries = [entity for entity in graph.entities.values() if is_primary(graph, entity, primary)]
    rows = _main_list(graph, [entity for entity in primaries if _listed(graph, entity, primary)])
    if isinstance(target, AmbiguousTarget):
        rows += _unlisted(primaries, rows)
    if not rows:
        entries = [entity for entity in graph.entities.values() if entity.id in holders and _entry(graph, entity)]
        rows = _main_list(graph, entries)
    return tuple(rows)


def row_lists(graph: EntityGraph, rows: Sequence[Entity]) -> dict[str, str]:
    """Each listed row's list: the nearest ItemList holding it."""
    lists = {row.id: next((a.id for a in graph.ancestors(row) if graph.is_a(a, _LIST)), None) for row in rows}
    return {row: found for row, found in lists.items() if found is not None}


def _main_list(graph: EntityGraph, rows: list[Entity]) -> list[Entity]:
    """With rows in lists, those of the one list that is the page's main entity (schema.org `mainEntity`: "the primary
    entity described in some page", a CollectionPage's list of items; a related or recently viewed list beside it is
    not the page's), none when it lists none of them; all of them when the page names no one main list
    (`collect.items.bind` keeps the lists the page's grid shows)."""
    main = {e.id for e in graph.entities.values() if graph.is_a(e, _LIST) and e.via == _MAIN_ENTITY}
    if len(main) != 1:
        return rows
    lists = row_lists(graph, rows)
    return [row for row in rows if row.id not in lists or any(a.id in main for a in graph.ancestors(row))]


def _unlisted(primaries: list[Entity], listed: list[Entity]) -> list[Entity]:
    """The top-level primary entities no list holds that are rows of a page whose target is ambiguous: beside listed
    rows, every one; without any, all of them when there are at least `MIN_TOP_LEVEL_ROWS` (module docstring)."""
    top_level = [entity for entity in primaries if entity.parent is None and entity not in listed]
    return top_level if listed or len(top_level) >= MIN_TOP_LEVEL_ROWS else []


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
