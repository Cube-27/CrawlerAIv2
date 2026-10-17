"""A listing's call rows beside its structured rows (Appendix A #59, SPEC-05 §4.7 "Listings"): the rows of the page's
captured calls (`collect.xhr`) join the structured rows that state the same item, and extend them with the items the
structured data does not state.

**Item identity.** A row names its item by its item URLs (schema.org `url`, "URL of the item": a structured row's
`Entity.item_urls`, and the values of the schema's row fields of the url type) and by the values of the schema's row
fields of the identifier type, compared per field. A call row and a structured row are one item when they share one of
these and neither shares one with another row of the other kind: two candidates for one join decline it (C7).

**Joining.** The call row's values for the fields the structured row holds no candidate of become that row's
candidates, so the call's value fills the field and keeps its `xhr` source kind (the `network` evidence bucket, §10);
a field the structured data states keeps its value, and the call's is not added beside it.

**Extending.** A call row that shares no key with a row of the listing (nor with a call row taken before it) is a row of
the listing too when one of its item URLs is a link of the page's listing: the group of repeated item blocks
(`acquire.items.item_groups`) whose links hold the most structured rows' item URLs. A list whose script was written once
and whose later batches came from calls (a load-more, a scroll) shows those batches as blocks of the same group; a call
of related items shows them in another group, or not at all."""

from collections import defaultdict
from collections.abc import Iterable, Sequence

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.item_links import group_links
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Ok
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.schemas.types import FieldType, SchemaDef

# An item's identity: ("url", a canonical item URL), or (an identifier field's name, its value).
_Key = tuple[str, str]
_ITEM_URL = "url"


def with_call_rows(
    graph: EntityGraph,
    schema: SchemaDef,
    rows: Sequence[Entity],
    call_rows: Sequence[Entity],
    candidates: Sequence[Candidate],
    page: ParsedPage,
    base_url: str | None,
) -> tuple[tuple[Entity, ...], tuple[Candidate, ...]]:
    """The listing's rows with the call rows that extend them, and the candidates the joined call rows give the
    structured rows (module docstring). `base_url` resolves the page's links."""
    if not rows or not call_rows:
        return tuple(rows), ()
    keys = _Keys(schema, candidates)
    pairs = _pairs([(row, keys.of(row)) for row in rows], [(row, keys.of(row)) for row in call_rows])
    added = [c for row, call in pairs.items() for c in _filled(graph, schema, candidates, row, call)]
    named = {key for row in rows for key in keys.of(row)}  # the items the listing has a row of
    links = _listing_links(page, base_url, {url for kind, url in named if kind == _ITEM_URL})
    extra: list[Entity] = []
    for row in call_rows:
        own = keys.of(row)
        if own.isdisjoint(named) and any(kind == _ITEM_URL and url in links for kind, url in own):
            extra.append(row)
            named |= own  # a second call row of the item is no further row
    return (*rows, *extra), tuple(added)


class _Keys:
    """Each row's identity keys, from its own URLs and its candidates."""

    def __init__(self, schema: SchemaDef, candidates: Iterable[Candidate]) -> None:
        self._found: dict[str, set[_Key]] = defaultdict(set)
        for candidate in candidates:
            if (key := _key(schema, candidate)) is not None:
                self._found[candidate.entity_id].add(key)

    def of(self, row: Entity) -> frozenset[_Key]:
        return frozenset({(_ITEM_URL, url) for url in row.item_urls} | self._found.get(row.id, set()))


def _key(schema: SchemaDef, candidate: Candidate) -> _Key | None:
    spec = schema.fields.get(candidate.field)
    if spec is None or spec.scope != "row" or not isinstance(candidate.normalized, Ok):
        return None
    value = candidate.normalized.value
    if not isinstance(value, str):
        return None
    if spec.type is FieldType.URL:
        return (_ITEM_URL, value)
    return (candidate.field, value) if spec.type is FieldType.IDENTIFIER else None


def _pairs(
    rows: Sequence[tuple[Entity, frozenset[_Key]]], calls: Sequence[tuple[Entity, frozenset[_Key]]]
) -> dict[Entity, Entity]:
    """Each structured row with the one call row it shares a key with, where neither shares one with another."""
    by_key: dict[_Key, list[Entity]] = defaultdict(list)
    for row, keys in rows:
        for key in keys:
            by_key[key].append(row)
    matches: dict[str, list[Entity]] = defaultdict(list)  # a structured row's id -> the call rows sharing a key
    pairs: dict[Entity, Entity] = {}
    for call, keys in calls:
        found = {row.id: row for key in keys for row in by_key.get(key, ())}
        if len(found) == 1:
            row = next(iter(found.values()))
            matches[row.id].append(call)
            pairs[row] = call
    return {row: call for row, call in pairs.items() if len(matches[row.id]) == 1}


def _filled(
    graph: EntityGraph, schema: SchemaDef, candidates: Sequence[Candidate], row: Entity, call: Entity
) -> list[Candidate]:
    """The call row's candidates of the row fields `row` holds no candidate of, as `row`'s."""
    stated = {c.field for c in candidates if graph.owned_by(c, row, page_values=False)}
    return [
        c.model_copy(update={"entity_id": row.id})
        for c in candidates
        if c.entity_id == call.id and c.field not in stated and schema.fields[c.field].scope == "row"
    ]


def _listing_links(page: ParsedPage, base_url: str | None, item_urls: set[str]) -> frozenset[str]:
    """The links of the group of repeated item blocks whose links hold the most of `item_urls`; none when no group
    holds one."""
    best: frozenset[str] = frozenset()
    hits = 0
    for links in group_links(page, base_url):
        if (found := len(links & item_urls)) > hits:
            best, hits = links, found
    return best
