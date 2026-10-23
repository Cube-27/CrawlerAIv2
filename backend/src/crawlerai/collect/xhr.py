"""The captured network body collector: the bodies a browser capture
kept.

Each body is one document, read as `network_json` reads it (RFC 8259 §8.1, a guard prefix stripped), or, labelled a
Flight payload (`is_flight`), as the RSC Flight reader reads it (`content.rsc`: its JSON rows by row id); an HTML body
is a fragment the page tree reads (`content.fragments`), not read here; a body that is none of them is skipped with a
diagnostic. Values are admitted by `admission`; locators are `xhr:<n>:<path>`, `n` the body's
index in the bundle.

On a listing, the calls of one rows endpoint (`network_match.row_series`) give rows: the first series, best first, in
which some row field is proved. A row field takes the path, relative to a row, whose values the admission rule admits in
the most rows, at least `MIN_ITEMS` of them; for a url field, a value that is the target of a hyperlink of one of the
page's repeated item groups (`ParsedPage.item_groups`; HTML Standard §4.6.1: a hyperlink states the document it leads
to) counts as admitted too, so a call whose items the page links to proves its item URL path even when the field's other
candidates name other items (a load-more's later batch); a path proved so on the page is read in every row of the series
through the API recipe row reader (`collect.api`), as a recipe's map is. Those calls are then read as rows only, not
admitted value by value as well. Where the site has a learned listing recipe, the calls of its endpoint are read with
the recipe's map instead (`network_match.LearnedCalls`): learning proved those paths by equality with published row
values, so text fields are read too."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from crawlerai.collect import json_doc
from crawlerai.collect.admission import Admitted, Document, FieldAnchors, admit, admits, field_anchors
from crawlerai.collect.api import read_rows
from crawlerai.collect.array_rows import Row, Scalar, row_of, row_paths
from crawlerai.collect.base import Candidate
from crawlerai.collect.network_match import DataCall, LearnedCalls, data_calls, row_series
from crawlerai.collect.platform_json import data_call_bodies
from crawlerai.content import rsc
from crawlerai.content.page import ParsedPage
from crawlerai.content.segment import group_links
from crawlerai.normalize.base import Context
from crawlerai.normalize.url import canonical_url
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef
from crawlerai.storage.capture_bundle import is_flight, is_html, network_json


@dataclass(frozen=True)
class XhrCollector:
    """`learned`: the calls of the site's learned listing recipe, read with its map where the page made them."""

    learned: LearnedCalls | None = None

    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        # A platform's identity-checked product JSON is read as the platform documents it (`collect.platform_json`).
        verified = data_call_bodies(page)
        documents = [d for d in network_documents(page, diagnostics) if int(d.address) not in verified]
        found = None
        if schema.page_kind == "listing":
            found = _learned(page, schema, self.learned) or _proved(page, schema, ctx, others)
        if found is None:
            return admit("xhr", documents, diagnostics, page, schema, ctx, others)
        series, fields = found
        read = [read_rows("xhr", str(d.call.index), _query(d), fields, d.call.document, schema, ctx) for d in series]
        listed = frozenset(d.call.index for d in series)
        admitted = admit("xhr", _aligned(documents, len(page.network), listed), diagnostics, page, schema, ctx, others)
        rows = tuple(row for executed in read for row in executed.rows)
        return Admitted(
            candidates=(*admitted.candidates, *(c for executed in read for c in executed.candidates)),
            entities=(*admitted.entities, *rows),
            rows=rows,
            diagnostics=(*admitted.diagnostics, *(d for executed in read for d in executed.diagnostics)),
        )


def network_documents(page: ParsedPage, diagnostics: list[str]) -> list[Document]:
    """The page's captured network bodies that are JSON or Flight payloads, each addressed by its index in the
    bundle."""
    documents: list[Document] = []
    for index, body in enumerate(page.network):
        entries = page.network_entries
        if index < len(entries) and is_html(entries[index].content_type):
            continue
        if index < len(entries) and is_flight(entries[index].content_type):
            if (rows := rsc.model_rows(rsc.read_rows(body, f"xhr:{index}", diagnostics))) is not None:
                documents.append(Document(rows, str(index)))
            continue
        try:
            documents.append(Document(network_json(body), str(index)))
        except ValueError as e:  # UnicodeDecodeError is a ValueError
            diagnostics.append(f"xhr:{index}: not UTF-8 JSON ({e})")
    return documents


def _aligned(documents: Sequence[Document], count: int, listed: frozenset[int]) -> list[Document]:
    """One document per network body, in bundle order, so that admission's row entities (`xhr:<position>:<row>`) are
    numbered as the bundle is and never meet the rows read here (`xhr:<index>:<row>`); a body read as rows, or not
    JSON, holds nothing."""
    by_index = {int(document.address): document for document in documents}
    return [
        by_index[index] if index in by_index and index not in listed else Document(None, str(index))
        for index in range(count)
    ]


def _query(data: DataCall) -> str:
    if data.rows is None:  # `row_series` keeps only calls with rows
        raise ValueError("a call of a row series has a row query")
    return data.rows


def _learned(
    page: ParsedPage, schema: SchemaDef, learned: LearnedCalls | None
) -> tuple[tuple[DataCall, ...], dict[str, str]] | None:
    """The first row series whose calls the learned recipe's endpoint made, with the recipe's map of the schema's row
    fields."""
    if learned is None:
        return None
    fields = {
        name: path for name, path in learned.map.items() if name in schema.fields and schema.fields[name].scope == "row"
    }
    for series in row_series(data_calls(page)):
        if fields and all(learned.matches(data) for data in series):
            return series, fields
    return None


def _proved(
    page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]
) -> tuple[tuple[DataCall, ...], dict[str, str]] | None:
    """The first row series in which some row field is proved, with its map."""
    anchors = field_anchors(others, "xhr", schema)
    series_found = row_series(data_calls(page))
    if not series_found:
        return None
    reads_urls = any(spec.scope == "row" and spec.type is FieldType.URL for spec in schema.fields.values())
    links = frozenset[str]().union(*group_links(page.item_groups, ctx.base_url)) if reads_urls else frozenset[str]()
    for series in series_found:
        if fields := _row_map(series, page, schema, ctx, anchors, links):
            return series, fields
    return None


def _row_map(
    series: Sequence[DataCall],
    page: ParsedPage,
    schema: SchemaDef,
    ctx: Context,
    anchors: Mapping[str, FieldAnchors],
    links: frozenset[str],
) -> dict[str, str]:
    """Each row field's path in the series' rows (`collect.array_rows`): a path proposed by a row when its value is
    admitted by the admission rule for the field with its `anchors`, or, for a url field, when one of the item groups'
    `links` leads to it."""
    specs = {name: spec for name, spec in schema.fields.items() if spec.scope == "row"}
    memo: dict[tuple[str, type, Scalar], bool] = {}

    def reads(name: str, _path: str, raw: Scalar) -> bool:
        key = (name, type(raw), raw)
        if key not in memo:
            spec = specs[name]
            memo[key] = admits(raw, spec, page, ctx, anchors.get(name)) or _linked(raw, spec, ctx, links)
        return memo[key]

    return row_paths(list(_rows(series)), specs, reads)


def _linked(raw: Scalar, spec: FieldSpec, ctx: Context, links: frozenset[str]) -> bool:
    return spec.type is FieldType.URL and isinstance(raw, str) and canonical_url(raw, ctx.base_url) in links


def _rows(series: Sequence[DataCall]) -> Iterator[Row]:
    for data in series:
        for _, row in json_doc.select(_query(data), data.call.document):
            if isinstance(row, dict):
                yield row_of(row)
