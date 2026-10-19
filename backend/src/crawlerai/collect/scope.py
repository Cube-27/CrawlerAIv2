"""Another item's scope (resolution spec, "Candidate score": scope match): the structured-data entities that belong to
another thing than the product a page is about, whatever page it is.

A thing that is the value of a relation property of another (schema.org `isRelatedTo`, `isSimilarTo`) is another thing
than its holder, and a thing in a list (an `ItemList` and its `ListItem`s) is one of many; whatever such a thing holds
(its Offers, their prices) is in its scope. So is a root item every one of whose URLs names another document than the
page (RFC 3986 §3: scheme, authority and path; a query may select within the page) while another root item names the
page: an item described here and sold elsewhere, as recommendations and bundles are. Where no root item names the
page, none is set apart by its URLs (the page's own may state only a URL the request did not use). Collection reads it
to know the page product's stated prices (`collect.dom.product_apart`); resolution's ownership and intent apply the same
relations.
"""

from collections.abc import Iterable, Sequence
from typing import Final
from urllib.parse import urlsplit

from crawlerai.collect.base import Entity
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.normalize.url import canonical_url

# schema.org relation properties of a Product: a thing that is the value of one is another thing than its holder.
RELATIONS: Final = frozenset({"isRelatedTo", "isSimilarTo"})
# schema.org: an ItemList (with its ListItems) lists things, so a thing in it is one of many, not the page's own.
LISTS: Final = ("ItemList", "ListItem")


def other_items(entities: Sequence[Entity], vocabulary: Vocabulary, page_urls: Iterable[str]) -> frozenset[str]:
    """The ids of the entities in another item's scope (module docstring)."""
    by_id = {e.id: e for e in entities}
    documents = {document(url) for url in page_urls} - {None}
    if not any(e.parent is None and _names(e, documents) for e in entities):
        documents = set()
    return frozenset(e.id for e in entities if any(_another(n, vocabulary, documents) for n in _chain(e, by_id)))


def _names(entity: Entity, documents: set[tuple[str, str, str] | None]) -> bool:
    return not documents.isdisjoint(map(document, entity.item_urls or entity.urls))


def _chain(entity: Entity, by_id: dict[str, Entity]) -> Iterable[Entity]:
    """The entity and its ancestors, up to the root (`CollectResult` keeps entities a tree)."""
    node: Entity | None = entity
    while node is not None:
        yield node
        node = by_id.get(node.parent) if node.parent is not None else None


def _another(entity: Entity, vocabulary: Vocabulary, documents: set[tuple[str, str, str] | None]) -> bool:
    if entity.via in RELATIONS or any(vocabulary.is_a(t, list_type) for t in entity.types for list_type in LISTS):
        return True
    return (
        entity.parent is None
        and bool(documents)
        and bool(entity.item_urls or entity.urls)
        and not _names(entity, documents)
    )


def document(url: str) -> tuple[str, str, str] | None:
    """The document a URL names: RFC 3986 §3 scheme, authority and path. The query may select within it (a variant of
    the same page), so it is left out: two URLs differing only there are not taken for other documents."""
    canonical = canonical_url(url, None)
    if canonical is None:
        return None
    parts = urlsplit(canonical)
    return parts.scheme, parts.netloc, parts.path
