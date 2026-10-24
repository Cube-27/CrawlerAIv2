"""A JSON array of objects read as rows (RFC 8259 §5, §4): each object is a row, its strings and numbers keyed by their
normalized path relative to it (RFC 9535 §2.7, `json_doc.scalars`); each row field reads one path, induced across the
rows (`collect.induce`, quorum `MIN_ITEMS`) from the paths each row proposes for it. Shared by the captured-call row
reader (`collect.xhr`) and the state row reader (`collect.items.state_rows`); what proves a path is each reader's."""

from collections.abc import Callable, Iterable, Sequence

from pydantic import JsonValue

from snowcrawl.acquire.items import MIN_ITEMS
from snowcrawl.collect import json_doc
from snowcrawl.collect.induce import induced

Scalar = str | int | float
# One row: the scalars it holds by path relative to the row, in document order.
Row = dict[str, Scalar]


def row_of(item: JsonValue) -> Row:
    """The row an array's object is."""
    return dict(json_doc.scalars(item))


def row_paths[N](rows: Sequence[Row], fields: Iterable[N], reads: Callable[[N, str, Scalar], bool]) -> dict[N, str]:
    """Each field's path in the rows: of the paths that are JSON queries (`is_query` of `collect.json_doc`) holding a
    value `reads` accepts for the field, the one induced across the rows; a field none is induced for is left out."""
    found: dict[N, str] = {}
    for name in fields:
        proposals = [
            [path for path, raw in row.items() if json_doc.is_query(path) and reads(name, path, raw)] for row in rows
        ]
        if (path := induced(proposals, MIN_ITEMS)) is not None:
            found[name] = path
    return found
