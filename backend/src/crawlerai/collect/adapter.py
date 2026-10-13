"""The adapter collector (SPEC-05 §4.5, ARCHITECTURE §8.1): a platform API's JSON, read through its adapter.

An adapter capture's body is the JSON the platform's documented API serves for the page (SPEC-02 §4.9). The adapter's
`map` gives an RFC 9535 query into that JSON for each schema field whose schema.org path the platform documents; the
values it selects are `adapter` candidates, located as `adapter:<name>:<normalized path>`. Nothing here interprets a
value: the field's normalizer is the only filter (C7).

The entity is the JSON object the values belong to: the node a query selects up to its last wildcard, one per item of a
listing's array, or the document itself when the query has no wildcard (a detail response). Its kind is the schema.org
type the mapped paths start at, and its URL is the value the adapter maps that type's `url` property to.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue, ValidationError

from crawlerai.adapters.base import Adapter
from crawlerai.collect.base import Candidate, CollectResult, Entity
from crawlerai.collect.json_doc import ROOT, parse, select
from crawlerai.collect.locator import format_locator
from crawlerai.collect.schema_org_map import parse_path
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import PageKind
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import normalize
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef

_WILDCARD = "[*]"  # RFC 9535 §2.5.1: the wildcard segment
_URL = FieldSpec(type=FieldType.URL)
_URL_KEY = "url"  # the one field of the projection that asks the adapter where the entity's URL is


@dataclass(frozen=True, slots=True)
class _Query:
    """A mapped query split at its last wildcard: the query of the entity, and the rest, relative to the entity."""

    entity: str
    rest: str

    @classmethod
    def of(cls, query: str) -> "_Query":
        end = query.rfind(_WILDCARD)
        split = len(ROOT) if end < 0 else end + len(_WILDCARD)
        return cls(query[:split], ROOT + query[split:])


@dataclass(frozen=True, slots=True)
class _Row:
    path: str  # the entity object's normalized path
    data: JsonValue


class AdapterCollector:
    """The collector of a capture `adapter` fetched, for a page whose kind the adapter detected as `page_kind`."""

    def __init__(self, adapter: Adapter, page_kind: PageKind) -> None:
        self._adapter = adapter
        self._page_kind = page_kind

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context) -> CollectResult:
        name = self._adapter.name
        try:
            document = parse(page.html)
        except ValueError as e:
            return CollectResult(entities=(), candidates=(), diagnostics=(f"adapter:{name}: not JSON ({e})",))
        paths = {
            field: spec.schema_org
            for field, spec in schema.fields.items()
            # A listing's page-scoped fields describe the page, not a row (SPEC-05 §4.7); the API's rows hold none.
            if spec.schema_org is not None and (self._page_kind == "detail" or spec.scope == "row")
        }
        queries = self._adapter.map(paths, self._page_kind)
        kinds = sorted({parse_path(paths[field]).root for field in queries})
        if len(kinds) != 1:
            diagnostics = (f"adapter:{name}: maps fields of several types {kinds}",) if kinds else ()
            return CollectResult(entities=(), candidates=(), diagnostics=diagnostics)
        return _Reading(name, document, schema, ctx).result(queries, kinds[0], self._url_query(kinds[0]))

    def _url_query(self, kind: str) -> str | None:
        return self._adapter.map({_URL_KEY: f"{kind}.url"}, self._page_kind).get(_URL_KEY)


@dataclass
class _Reading:
    """One adapter document read for one schema."""

    adapter: str
    document: JsonValue
    schema: SchemaDef
    ctx: Context

    def result(self, queries: Mapping[str, str], kind: str, url_query: str | None) -> CollectResult:
        diagnostics: list[str] = []
        url = None if url_query is None else _Query.of(url_query)
        rows: dict[str, _Row] = {}
        candidates: list[Candidate] = []
        for field, query in queries.items():
            split = _Query.of(query)
            for row in self._rows(split.entity, diagnostics):
                rows.setdefault(row.path, row)
                candidates.extend(self._candidates(field, row, split.rest, diagnostics))
        entities = tuple(
            Entity(id=self._id(row.path), kind=kind, urls=self._urls(row, url), parent=None) for row in rows.values()
        )
        return CollectResult(entities=entities, candidates=tuple(candidates), diagnostics=tuple(diagnostics))

    def _rows(self, query: str, diagnostics: list[str]) -> list[_Row]:
        # The entity is a JSON object (RFC 8259 §4); an array item of another kind holds no fields.
        return [
            _Row(path, data)
            for path, data in self._select(query, self.document, ROOT, diagnostics)
            if isinstance(data, dict)
        ]

    def _candidates(self, field: str, row: _Row, query: str, diagnostics: list[str]) -> Iterator[Candidate]:
        spec = self.schema.fields[field]
        for path, raw in self._select(query, row.data, row.path, diagnostics):
            if raw is None:  # RFC 8259 `null`: the API states no value
                continue
            locator = format_locator("adapter", self.adapter, path)
            try:
                yield Candidate(
                    field=field,
                    entity_id=self._id(row.path),
                    source_kind="adapter",
                    raw=raw,
                    normalized=normalize(raw, spec, self.ctx),
                    locator=locator,
                    independent=True,
                )
            except ValidationError as e:  # nested deeper than the candidate model's validator recurses
                diagnostics.append(f"value at {locator} skipped ({e.errors()[0]['type']})")

    def _urls(self, row: _Row, url: _Query | None) -> tuple[str, ...]:
        found = [] if url is None else self._select(url.rest, row.data, row.path, [])
        results = [normalize(raw, _URL, self.ctx) for _, raw in found]
        return tuple(dict.fromkeys(r.value for r in results if isinstance(r, Ok) and isinstance(r.value, str)))

    def _select(self, query: str, data: JsonValue, at: str, diagnostics: list[str]) -> Sequence[tuple[str, JsonValue]]:
        try:
            return select(query, data, at)
        except ValueError as e:  # a query outside the subset the adapter maps are written in
            diagnostics.append(f"adapter:{self.adapter}: {e}")
            return ()

    def _id(self, path: str) -> str:
        return f"adapter:{self.adapter}:{path}"
