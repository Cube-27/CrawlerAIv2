"""Identity (SPEC-05 §4.5, §4.6): the entities that state one item are one entity, whichever collector found them.

The entities considered are the items that stand on their own (a root, or an item only lists hold) and the members of
a product group (`hasVariant`). Two of them of one most specific type are one item when
- they share an IRI (a JSON-LD `@id`, a microdata `itemid`): JSON-LD 1.1 node map generation merges node objects with
  one `@id`, and the HTML Standard's `itemid` is the item's global identifier;
- they share a value of a schema.org identifier property (`schema_org_map.identity`), unless their own URLs name two
  different items (schema.org `url`, "URL of the item"): a listing's items may repeat an identifier;
- they name one item URL that is not a page URL, stated by two collectors or by a group's member and a standalone
  product: a page often states its items in two syntaxes (JSON-LD and microdata), and a URL naming the page itself
  names no item.
Every pair that agrees joins, so two later entities that agree join even when an earlier one stays apart. Two members
of product groups never join (two variants sharing a sku are two sizes of one sku, SPEC-13 INV-33), nor does an entity
join its own ancestor. The merged entity is the group member when there is one, else the first in collector order; it
takes every member's URLs, identity and children, and their candidates (`EntityGraph.adopt`).

A standalone Product whose `inProductGroupWithID` is the `productGroupID` of one standalone ProductGroup on the page is
that group's variant, as `hasVariant` would state it (schema.org: "the productGroupID for a ProductGroup that this
product isVariantOf"). So is a root Product that names its group by `isVariantOf` (D-1344), by the group's IRI or by
holding it: a held group stands beside the Product as a root first, so the Product joins the group's member it is, or
else becomes a member.
"""

from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Final

from crawlerai.collect.base import ARRAY_ROW, PAGE, Entity
from crawlerai.collect.schema_org_map import Vocabulary

# schema.org: an ItemList (with its ListItems) lists things, so a thing in it is one of many, not the page's own.
LISTS: Final = ("ItemList", "ListItem")
# schema.org `hasVariant`: "Indicates a Product that is a member of this ProductGroup". A variant is part of its group,
# not another thing the page is about, and its Offer offers the group's product too: it joins the group's Offers under
# the atomic-offer rule. The variant's own values (its sku, its name) stay the variant's.
VARIANT: Final = "hasVariant"
# schema.org: a ProductGroup "represents a group of Products that vary only in certain well-described ways".
_GROUP: Final = "ProductGroup"
_PRODUCT: Final = "Product"
_GROUP_ID: Final = "productGroupID"  # `schema_org_map.identity`
# schema.org `isVariantOf`: "Indicates the kind of product that this is a variant of", the inverse of `hasVariant`.
_VARIANT_OF: Final = "isVariantOf"
_IRI: Final = "@id"
_URL: Final = "url"


@dataclass(frozen=True, slots=True)
class Identified:
    """The entities with each item once, and each merged entity's id mapped to the entity it is now part of."""

    entities: tuple[Entity, ...]
    aliases: Mapping[str, str]


def identify(entities: Sequence[Entity], vocabulary: Vocabulary, page_urls: Sequence[str]) -> Identified:
    """The entities with the entities of one item merged, then standalone variants placed in their group."""
    entities, variant_of = _detached_groups(entities, vocabulary)
    by_id = {e.id: e for e in entities}
    eligible = [e for e in entities if _eligible(e, by_id, vocabulary)]
    pages = frozenset(page_urls)
    sets = _Sets.of(eligible, by_id, pages)
    for (_, prop, _), members in _keyed(eligible, pages).items():
        for i, j in combinations(members, 2):
            if prop != _URL or _url_joins(eligible[i], eligible[j]):
                sets.join(i, j, by_iri=prop == _IRI)
    aliases, groups = sets.aliases(), sets.groups()
    merged = [_merged(e, groups.get(e.id, ()), aliases) for e in entities if e.id not in aliases]
    named = {aliases.get(p, p): aliases.get(g, g) for p, g in variant_of.items()}
    return Identified(tuple(_grouped(merged, vocabulary, named)), aliases)


def _detached_groups(entities: Sequence[Entity], vocabulary: Vocabulary) -> tuple[list[Entity], dict[str, str]]:
    """The entities with each ProductGroup a root Product names by `isVariantOf` standing beside it as a root, and the
    Products by the group they named (D-1344). schema.org `isVariantOf` is the inverse of `hasVariant`: the Product is
    one of the group's variants, not the holder of the group, so it is related as a standalone Product beside its
    group is, by its identity (one of the group's members) or else as the group's `hasVariant` member (`_grouped`)."""
    by_id = {e.id: e for e in entities}
    variant_of: dict[str, str] = {}
    detached: list[Entity] = []
    for e in entities:
        holder = by_id.get(e.parent) if e.parent is not None else None
        if e.via == _VARIANT_OF and holder is not None and _inverts(e, holder, vocabulary):
            variant_of.setdefault(holder.id, e.id)
            e = e.model_copy(update={"parent": None, "via": None})
        detached.append(e)
    return detached, variant_of


def _inverts(group: Entity, holder: Entity, vocabulary: Vocabulary) -> bool:
    """Whether `holder`, a root Product, names `group`, a ProductGroup, by `isVariantOf`: only a root, the page's own
    product, as `_grouped` places root Products only."""
    is_product = _is_a(holder, _PRODUCT, vocabulary) and not _is_a(holder, _GROUP, vocabulary)
    return holder.parent is None and is_product and _is_a(group, _GROUP, vocabulary)


def _eligible(entity: Entity, by_id: Mapping[str, Entity], vocabulary: Vocabulary) -> bool:
    if entity.id == PAGE or ARRAY_ROW in entity.types or PAGE in entity.types or _is_list(entity, vocabulary):
        return False
    if _standalone(entity, by_id, vocabulary):
        return True
    return entity.via == VARIANT and entity.parent is not None and _standalone(by_id[entity.parent], by_id, vocabulary)


def _standalone(entity: Entity, by_id: Mapping[str, Entity], vocabulary: Vocabulary) -> bool:
    """Whether only lists hold the entity: it is a root, or one of a list's items."""
    return all(_is_list(a, vocabulary) for a in _ancestors(entity, by_id))


def _ancestors(entity: Entity, by_id: Mapping[str, Entity]) -> Iterator[Entity]:
    while entity.parent is not None:
        entity = by_id[entity.parent]
        yield entity


def _is_list(entity: Entity, vocabulary: Vocabulary) -> bool:
    return any(vocabulary.is_a(t, list_type) for t in entity.types for list_type in LISTS)


def _is_a(entity: Entity, type_: str, vocabulary: Vocabulary) -> bool:
    return any(vocabulary.is_a(t, type_) for t in entity.types)


def _url_joins(a: Entity, b: Entity) -> bool:
    """Whether one item URL makes two entities one: two collectors' statements of an item, or a group's member and a
    standalone product (one collector lists distinct items under one URL, so a URL alone does not join its own)."""
    return _collector(a) != _collector(b) or VARIANT in (a.via, b.via)


def _collector(entity: Entity) -> str:
    # An entity id starts with its collector's locator scheme (`jsonld:`, `microdata:`, SPEC-05 §4.3).
    return entity.id.partition(":")[0]


def _keyed(eligible: Sequence[Entity], page_urls: frozenset[str]) -> dict[tuple[str, str, str], list[int]]:
    """The indexes of the entities stating each (most specific type, property, value): IRI, identifiers, item URLs."""
    keyed: defaultdict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, e in enumerate(eligible):
        for prop, value in e.identity:
            keyed[e.types[0], prop, value].append(i)
        for url in dict.fromkeys(e.item_urls):
            if url not in page_urls:
                keyed[e.types[0], _URL, url].append(i)
    return keyed


@dataclass
class _Sets:
    """Disjoint sets of the eligible entities (union-find), each with its head (the entity the others merge into), its
    members' item URLs and their ids, the ids of their ancestors, and whether a member is a
    group's variant."""

    entities: Sequence[Entity]
    ancestors: list[set[str]]
    pages: frozenset[str]
    parent: list[int] = field(init=False)
    head: list[int] = field(init=False)
    urls: list[set[str]] = field(init=False)
    members: list[list[int]] = field(init=False)
    variant: list[bool] = field(init=False)

    @classmethod
    def of(cls, entities: Sequence[Entity], by_id: Mapping[str, Entity], page_urls: frozenset[str]) -> "_Sets":
        ancestors = [{a.id for a in _ancestors(e, by_id)} for e in entities]
        return cls(entities, ancestors, page_urls)

    def __post_init__(self) -> None:
        n = len(self.entities)
        self.parent, self.head = list(range(n)), list(range(n))
        self.urls = [set(e.item_urls) for e in self.entities]
        self.members = [[i] for i in range(n)]
        self.variant = [e.via == VARIANT for e in self.entities]

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, i: int, j: int, *, by_iri: bool) -> None:
        a, b = self.find(i), self.find(j)
        if a == b or not self._joinable(a, b, by_iri=by_iri):
            return
        keep, drop = (b, a) if self.variant[b] or (not self.variant[a] and self.head[b] < self.head[a]) else (a, b)
        self.parent[drop] = keep
        self.urls[keep] |= self.urls[drop]
        self.members[keep] += self.members[drop]
        self.ancestors[keep] |= self.ancestors[drop]
        self.variant[keep] = self.variant[keep] or self.variant[drop]

    def _joinable(self, a: int, b: int, *, by_iri: bool) -> bool:
        if self.variant[a] and self.variant[b]:
            return False
        ids_a, ids_b = self._ids(a), self._ids(b)
        if ids_a & self.ancestors[b] or ids_b & self.ancestors[a]:
            return False
        return by_iri or self._same_item_urls(self.urls[a], self.urls[b])

    def _same_item_urls(self, a: set[str], b: set[str]) -> bool:
        """Whether two sets' item URLs may name one item: one states none, or they share one. A URL naming the page
        is shared by every item a listing states with `mainEntityOfPage`, so it counts only where one set names
        nothing else."""
        own_a, own_b = a - self.pages, b - self.pages
        if own_a and own_b:
            return bool(own_a & own_b)
        return not (a and b) or bool(a & b)

    def _ids(self, root: int) -> set[str]:
        return {self.entities[m].id for m in self.members[root]}

    def aliases(self) -> dict[str, str]:
        heads = {i: self.entities[self.head[self.find(i)]].id for i in range(len(self.entities))}
        return {self.entities[i].id: head for i, head in heads.items() if head != self.entities[i].id}

    def groups(self) -> dict[str, list[Entity]]:
        """The entities of each set of two or more by its head's id: the head first, then in collector order."""
        found: dict[str, list[Entity]] = {}
        for root, members in enumerate(self.members):
            if self.parent[root] == root and len(members) > 1:
                head = self.head[root]
                found[self.entities[head].id] = [self.entities[m] for m in [head, *sorted(set(members) - {head})]]
        return found


def _merged(entity: Entity, members: Sequence[Entity], aliases: Mapping[str, str]) -> Entity:
    parent = aliases.get(entity.parent, entity.parent) if entity.parent is not None else None
    if len(members) < 2:
        return entity if parent == entity.parent else entity.model_copy(update={"parent": parent})
    return entity.model_copy(
        update={
            "parent": parent,
            "urls": _union(m.urls for m in members),
            "identity": _union(m.identity for m in members),
            "item_urls": _union(m.item_urls for m in members),
            "group_ids": _union(m.group_ids for m in members),
            "variant_of": _union(m.variant_of for m in members),
        }
    )


def _union[T](parts: Iterator[tuple[T, ...]]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(item for part in parts for item in part))


def _grouped(entities: Sequence[Entity], vocabulary: Vocabulary, variant_of: Mapping[str, str]) -> Iterator[Entity]:
    """The entities with each root Product naming one standalone group placed in that group: by its `productGroupID`,
    by its IRI in `isVariantOf`, or as the group `isVariantOf` held (`variant_of`)."""
    by_group_id, by_iri = _groups(entities, vocabulary)
    for e in entities:
        named = {g for value in e.group_ids for g in by_group_id.get(value, ())}
        named |= {g for iri in e.variant_of for g in by_iri.get(iri, ())}
        named = {variant_of[e.id]} if e.id in variant_of else named - {e.id}
        if len(named) == 1 and e.parent is None and _is_a(e, _PRODUCT, vocabulary) and not _is_a(e, _GROUP, vocabulary):
            yield e.model_copy(update={"parent": named.pop(), "via": VARIANT})
        else:
            yield e


def _groups(entities: Sequence[Entity], vocabulary: Vocabulary) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """The standalone ProductGroups' ids by their `productGroupID` values, and by their IRIs."""
    by_id = {e.id: e for e in entities}
    by_group_id: defaultdict[str, set[str]] = defaultdict(set)
    by_iri: defaultdict[str, set[str]] = defaultdict(set)
    for e in entities:
        if _is_a(e, _GROUP, vocabulary) and _standalone(e, by_id, vocabulary):
            for prop, value in e.identity:
                if prop in (_GROUP_ID, _IRI):
                    (by_group_id if prop == _GROUP_ID else by_iri)[value].add(e.id)
    return by_group_id, by_iri
