"""The adapter collector (SPEC-05 §4.5, ARCHITECTURE §8.1): a platform API's JSON, read through its adapter.

An adapter capture's body is the JSON the platform's documented API serves for the page (SPEC-02 §4.9). The adapter's
`map` gives an RFC 9535 query into that JSON for each schema field whose schema.org path the platform documents; the
values it selects are `adapter` candidates, located as `adapter:<name>:<normalized path>`. Nothing here interprets a
value: the field's normalizer is the only filter (C7).

The entity is the JSON object the values belong to: the node a query selects up to its last wildcard, one per item of a
listing's array, or the document itself when the query has no wildcard (a detail response). A list field's query may
reach its items through a wildcard of its own (`$['locations'][*]['name']`): its entity is then the longest entity the
other queries of the map select that starts its query, and the values its rest selects in one entity are one candidate,
the list, located by that rest with its wildcards (RFC 9535 §2.5.1.2). Its kind is the schema.org type the mapped paths
start at, and its URL is the value the adapter maps that type's `url` property to.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from crawlerai.adapters.base import Adapter
from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.json_doc import ROOT, parse, select, split_at_last_wildcard
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, canonical_urls, parse_paths
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldType, SchemaDef

_URL_FIELD = "url"  # the projection's one field, asking the adapter where the entity's URL is


class AdapterCollector:
    """The collector of a capture `adapter` fetched, for a page whose kind the adapter detected as `page_kind`."""

    def __init__(self, adapter: Adapter, page_kind: PageKind) -> None:
        self._adapter = adapter
        self._page_kind = page_kind

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        adapter = self._adapter.name
        try:
            document = parse(page.html)
        except ValueError as e:
            return CollectResult(entities=(), candidates=(), diagnostics=(f"adapter:{adapter}: not JSON ({e})",))
        paths = {
            name: spec.schema_org
            for name, spec in schema.fields.items()
            # A listing's page-scoped fields describe the page, not a row (SPEC-05 §4.7); the API's rows hold none.
            # A row-mapped field's path names rows, not values (SPEC-13 §4.2); an adapter reads no rows of rows.
            if spec.schema_org is not None
            and not spec.row_mapped
            and (self._page_kind == "detail" or spec.scope == "row")
        }
        queries = self._adapter.map(paths, self._page_kind)
        kinds = sorted({path.root for name in queries for path in parse_paths(paths[name])})
        if len(kinds) != 1:
            diagnostics = (f"adapter:{adapter}: maps fields of several types {kinds}",) if kinds else ()
            return CollectResult(entities=(), candidates=(), diagnostics=diagnostics)
        url_query = self._adapter.map({_URL_FIELD: f"{kinds[0]}.url"}, self._page_kind).get(_URL_FIELD)
        return _Reading(adapter, document, schema, ctx).result(queries, kinds[0], url_query)


@dataclass
class _Reading:
    """One adapter document read for one schema."""

    adapter: str
    document: JsonValue
    schema: SchemaDef
    ctx: Context
    diagnostics: list[str] = field(default_factory=list)
    _rows: dict[str, dict[str, JsonValue]] = field(default_factory=dict)  # entity query -> object by path

    def result(self, queries: Mapping[str, str], kind: str, url_query: str | None) -> CollectResult:
        rows: dict[str, JsonValue] = {}
        candidates: list[Candidate] = []
        hints = [q for name, q in queries.items() if self.schema.fields[name].type is not FieldType.LIST]
        entity_queries = {split_at_last_wildcard(q)[0] for q in [*hints, *([url_query] if url_query else [])]}
        for name, query in queries.items():
            entity_query = self._entity_query(name, query, entity_queries)
            rest = ROOT + query[len(entity_query) :]
            for path, data in self._entities(entity_query).items():
                rows.setdefault(path, data)
                candidates.extend(self._candidates(name, path, data, rest))
        url_rest = None if url_query is None else split_at_last_wildcard(url_query)[1]
        entities = tuple(
            Entity(id=self._id(path), kind=kind, urls=self._urls(path, data, url_rest), parent=None)
            for path, data in rows.items()
        )
        return CollectResult(entities=entities, candidates=tuple(candidates), diagnostics=tuple(self.diagnostics))

    def _entity_query(self, name: str, query: str, entity_queries: set[str]) -> str:
        """The query of the entities `query` selects values of: up to its last wildcard, or, for a list field whose
        items that wildcard selects, the longest of the other queries' entities that starts it."""
        own = split_at_last_wildcard(query)[0]
        if self.schema.fields[name].type is not FieldType.LIST or own in entity_queries:
            return own
        starting = [e for e in entity_queries if query.startswith(e) and query[len(e) :].startswith("[")]
        return max(starting, key=len, default=own)

    def _entities(self, query: str) -> dict[str, JsonValue]:
        if query not in self._rows:
            # The entity is a JSON object (RFC 8259 §4); an array item of another kind holds no fields.
            selected = self._select(query, self.document, ROOT)
            self._rows[query] = {path: data for path, data in selected if isinstance(data, dict)}
        return self._rows[query]

    def _candidates(self, name: str, path: str, data: JsonValue, query: str) -> list[Candidate]:
        spec = self.schema.fields[name]
        if spec.type is FieldType.LIST and split_at_last_wildcard(query)[0] != ROOT:
            return self._list_candidate(name, path, data, query)
        found = (
            candidate(
                name,
                spec,
                self._id(path),
                "adapter",
                raw,
                format_locator("adapter", self.adapter, at),
                self.ctx,
                self.diagnostics,
            )
            for at, raw in self._select(query, data, path)
            if raw is not None  # RFC 8259 `null`: the API states no value
        )
        return [c for c in found if c is not None]

    def _list_candidate(self, name: str, path: str, data: JsonValue, query: str) -> list[Candidate]:
        """The one candidate of a list field whose query selects its items through a wildcard: the items' values."""
        items: list[JsonValue] = [raw for _, raw in self._select(query, data, path) if raw is not None]
        if not items:
            return []
        locator = format_locator("adapter", self.adapter, path + query[len(ROOT) :])
        found = candidate(
            name, self.schema.fields[name], self._id(path), "adapter", items, locator, self.ctx, self.diagnostics
        )
        return [] if found is None else [found]

    def _urls(self, path: str, data: JsonValue, query: str | None) -> tuple[str, ...]:
        found = () if query is None else self._select(query, data, path)
        return canonical_urls((raw for _, raw in found), self.ctx)

    def _select(self, query: str, data: JsonValue, at: str) -> Sequence[tuple[str, JsonValue]]:
        try:
            return select(query, data, at)
        except ValueError as e:  # a query outside the subset the adapter maps are written in
            self.diagnostics.append(f"adapter:{self.adapter}: {e}")
            return ()

    def _id(self, path: str) -> str:
        return f"adapter:{self.adapter}:{path}"
