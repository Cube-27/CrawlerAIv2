"""The adapter collector (SPEC-05 §4.5, ARCHITECTURE §8.1): a platform API's JSON, read through its adapter.

An adapter capture's body is the JSON the platform's documented API serves for the page (SPEC-02 §4.9). The adapter's
`map` gives an RFC 9535 query into that JSON for each schema field whose schema.org path the platform documents; the
values it selects are `adapter` candidates, located as `adapter:<name>:<normalized path>`. Nothing here interprets a
value: the field's normalizer is the only filter (C7).

The entity is the JSON object the values belong to: the node a query selects up to its last wildcard, one per item of a
listing's array, or the document itself when the query has no wildcard (a detail response). Its kind is the schema.org
type the mapped paths start at, and its URL is the value the adapter maps that type's `url` property to.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue

from crawlerai.adapters.base import Adapter
from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.json_doc import ROOT, parse, select, split_at_last_wildcard
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import candidate, canonical_urls, parse_path
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

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
            if spec.schema_org is not None and (self._page_kind == "detail" or spec.scope == "row")
        }
        queries = self._adapter.map(paths, self._page_kind)
        kinds = sorted({parse_path(paths[name]).root for name in queries})
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
        for name, query in queries.items():
            entity_query, rest = split_at_last_wildcard(query)
            for path, data in self._entities(entity_query).items():
                rows.setdefault(path, data)
                candidates.extend(self._candidates(name, path, data, rest))
        url_rest = None if url_query is None else split_at_last_wildcard(url_query)[1]
        entities = tuple(
            Entity(id=self._id(path), kind=kind, urls=self._urls(path, data, url_rest), parent=None)
            for path, data in rows.items()
        )
        return CollectResult(entities=entities, candidates=tuple(candidates), diagnostics=tuple(self.diagnostics))

    def _entities(self, query: str) -> dict[str, JsonValue]:
        if query not in self._rows:
            # The entity is a JSON object (RFC 8259 §4); an array item of another kind holds no fields.
            selected = self._select(query, self.document, ROOT)
            self._rows[query] = {path: data for path, data in selected if isinstance(data, dict)}
        return self._rows[query]

    def _candidates(self, name: str, path: str, data: JsonValue, query: str) -> list[Candidate]:
        spec = self.schema.fields[name]
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
