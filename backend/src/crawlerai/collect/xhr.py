"""The captured network JSON collector (SPEC-05 §4.5, ARCHITECTURE §8.1, Appendix A #57): the bodies a browser capture
kept.

Each body is one document, read as `network_json` reads it (RFC 8259 §8.1, a guard prefix stripped); a body that is not
JSON is skipped with a diagnostic. Values are admitted by `admission`; locators are `xhr:<n>:<path>`, `n` the body's
index in the bundle.

On a listing, the calls of the page's best rows endpoint (`network_match.row_series`) give rows. Each row field takes
the path, relative to a row, whose values the admission rule admits in the most rows, at least `MIN_ITEMS` of them; a
path proved so on the page is read in every row of the series through the API recipe row reader (`collect.api`), as a
recipe's map is. Those calls are then read as rows only, not admitted value by value as well.
"""

from collections.abc import Iterator, Mapping, Sequence

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect import json_doc
from crawlerai.collect.admission import Admitted, Document, FieldAnchors, admit, admits, field_anchors
from crawlerai.collect.api import read_rows
from crawlerai.collect.base import Candidate
from crawlerai.collect.network_match import DataCall, data_calls, row_series
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import FieldSpec, SchemaDef
from crawlerai.storage.capture_bundle import network_json

Scalar = str | int | float
# One row of a series: the scalars it holds by path relative to the row, in document order.
_Row = dict[str, Scalar]


class XhrCollector:
    def collect(self, page: ParsedPage, schema: SchemaDef, ctx: Context, others: Sequence[Candidate]) -> Admitted:
        diagnostics: list[str] = []
        documents = network_documents(page, diagnostics)
        series = row_series(data_calls(page)) if schema.page_kind == "listing" else ()
        fields = _row_map(series, page, schema, ctx, field_anchors(others, "xhr", schema))
        if not fields:
            return admit("xhr", documents, diagnostics, page, schema, ctx, others)
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
    """The page's captured network bodies that are JSON, each addressed by its index in the bundle."""
    documents: list[Document] = []
    for index, body in enumerate(page.network):
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


def _row_map(
    series: Sequence[DataCall],
    page: ParsedPage,
    schema: SchemaDef,
    ctx: Context,
    anchors: Mapping[str, FieldAnchors],
) -> dict[str, str]:
    """Each row field's path in the series' rows: the one whose values are admitted in the most rows, at least
    `MIN_ITEMS`; ties keep the first row's document order."""
    rows = list(_rows(series))
    paths = list(dict.fromkeys(path for row in rows for path in row if json_doc.is_query(path)))
    found: dict[str, str] = {}
    for name, spec in schema.fields.items():
        if spec.scope == "row" and paths:
            counts = _admitted_rows(rows, paths, spec, page, ctx, anchors.get(name))
            best = max(paths, key=counts.__getitem__)
            if counts[best] >= MIN_ITEMS:
                found[name] = best
    return found


def _admitted_rows(
    rows: Sequence[_Row],
    paths: Sequence[str],
    spec: FieldSpec,
    page: ParsedPage,
    ctx: Context,
    anchors: FieldAnchors | None,
) -> dict[str, int]:
    """For each path, how many rows hold a value there that the admission rule admits for a field of `spec`."""
    memo: dict[tuple[type, Scalar], bool] = {}
    counts = dict.fromkeys(paths, 0)
    for row in rows:
        for path, raw in row.items():
            if path not in counts:
                continue
            key = (type(raw), raw)
            if key not in memo:
                memo[key] = admits(raw, spec, page, ctx, anchors)
            counts[path] += memo[key]
    return counts


def _rows(series: Sequence[DataCall]) -> Iterator[_Row]:
    for data in series:
        for _, row in json_doc.select(_query(data), data.call.document):
            if isinstance(row, dict):
                yield dict(json_doc.scalars(row))
