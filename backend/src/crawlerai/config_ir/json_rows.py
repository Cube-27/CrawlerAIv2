"""A listing's rows in the page's JSON documents, as config steps (listings spec, "Rows from page state";
learning-configs spec, "Locate run"): the paths `collect.items.state_rows` reads at run time, written into the config
for the rows a render published.

Each published row's item URL (`collect.schema_org_map.item_url_fields`) is searched in every JSON document the HTML
carries (`induction.LOCATED_SOURCES` but captured calls, whose rows are a listing recipe's): a path that holds it
inside an array item proposes the array (`[*]` for the item's index, RFC 9535 §2.5.1.2) and the URL's path relative to
the item. An array that holds `MIN_ITEMS` or more of the rows' URLs is a row source: its row step is a `jsonpath` step
selecting its items, and each row field reads, from every item paired with a row by its URL, the relative path the most
pairs propose among those holding the row's value, when more than half do. Validation (`validation.validate`, both
executors) decides whether the rows hold.
"""

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Final

from pydantic import JsonValue, ValidationError

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect.json_doc import ROOT, segments, select
from crawlerai.collect.schema_org_map import item_url_fields
from crawlerai.config_ir.executor import documents
from crawlerai.config_ir.induction import LOCATED_SOURCES, holding
from crawlerai.config_ir.listing_induction import row_fields
from crawlerai.config_ir.model import FieldSteps, JsonPathStep, JsonSource, ListingSpec
from crawlerai.content.page import ParsedPage
from crawlerai.normalize.base import Context
from crawlerai.schemas.types import SchemaDef

__all__ = ["json_listings"]

# The sources a row array is read from: documents the HTML carries, not captured calls.
ROW_SOURCES: Final[tuple[JsonSource, ...]] = tuple(source for source in LOCATED_SOURCES if source != "xhr")
_MAX_LISTINGS: Final = 3

Row = Mapping[str, JsonValue]


def json_listings(page: ParsedPage, ctx: Context, schema: SchemaDef, rows: Sequence[Row]) -> list[ListingSpec]:
    """The row sources of `page` for its published `rows` (module docstring), the array holding most rows first."""
    # The first item URL field the rows publish identifies them.
    url = next((name for name in item_url_fields(schema) if any(row.get(name) is not None for row in rows)), None)
    if url is None or len(rows) < MIN_ITEMS:
        return []
    found = [
        found
        for source in ROW_SOURCES
        for document in documents(source, page)
        for found in _document_listings(source, document, url, rows, schema, ctx)
    ]
    found.sort(key=lambda item: -item[0])
    return [spec for _, spec in found[:_MAX_LISTINGS]]


def _document_listings(
    source: JsonSource, document: JsonValue, url: str, rows: Sequence[Row], schema: SchemaDef, ctx: Context
) -> Iterator[tuple[int, ListingSpec]]:
    """The listings of `document`'s arrays holding `MIN_ITEMS` or more of the rows' URLs, with how many they hold."""
    for (array, relative), held in _arrays(document, rows, url, schema, ctx).items():
        if len(held) >= MIN_ITEMS and (spec := _listing(source, document, (array, relative, url), rows, schema, ctx)):
            yield len(held), spec


def _arrays(
    document: JsonValue, rows: Sequence[Row], url: str, schema: SchemaDef, ctx: Context
) -> dict[tuple[str, str], set[int]]:
    """Each (array `[*]` query, URL path relative to its item) a row's URL proposes, with the rows that propose it."""
    proposed: dict[tuple[str, str], set[int]] = {}
    for n, row in enumerate(rows):
        value = row.get(url)
        if value is None:
            continue
        for path in holding(document, value, schema.fields[url], ctx):
            if (split := _split(path)) is not None:
                proposed.setdefault(split, set()).add(n)
    return proposed


def _split(path: str) -> tuple[str, str] | None:
    """The path's array (its last index replaced by `[*]`) and the path relative to that array's item; None for a path
    through no array."""
    try:
        parts = segments(path)
    except ValueError:  # a member name holding a quote or a backslash, which the engine's JSONPath reader does not take
        return None
    last = max((i for i, part in enumerate(parts) if part[1:-1].isdigit()), default=None)
    if last is None:
        return None
    return ROOT + "".join(parts[:last]) + "[*]", ROOT + "".join(parts[last + 1 :])


def _listing(
    source: JsonSource,
    document: JsonValue,
    found: tuple[str, str, str],
    rows: Sequence[Row],
    schema: SchemaDef,
    ctx: Context,
) -> ListingSpec | None:
    """The listing of the array, whose items hold the item URL field `url` at `relative` (`found`)."""
    array, relative, url = found
    pairs = list(_pairs(document, array, relative, rows, url, schema, ctx))
    fields = {url: _steps(source, relative)}
    for name in row_fields(schema):
        if name != url and (path := _row_path(pairs, name, schema, ctx)) is not None:
            fields[name] = _steps(source, path)
    try:
        return ListingSpec(row=JsonPathStep(jsonpath=array, source=source), fields=fields)
    except ValidationError:  # a member name outside the RFC 9535 subset the IR accepts
        return None


def _row_path(pairs: Sequence[tuple[JsonValue, Row]], name: str, schema: SchemaDef, ctx: Context) -> str | None:
    """The path relative to the item that the most pairs holding the row's value of `name` propose, when more than half
    of them do."""
    with_value = [(item, row[name]) for item, row in pairs if row.get(name) is not None]
    spec = schema.fields[name]
    proposed = Counter(path for item, value in with_value for path in holding(item, value, spec, ctx))
    if not proposed:
        return None
    path, count = proposed.most_common(1)[0]
    return path if 2 * count > len(with_value) else None


def _pairs(
    document: JsonValue, array: str, relative: str, rows: Sequence[Row], url: str, schema: SchemaDef, ctx: Context
) -> Iterator[tuple[JsonValue, Row]]:
    """Each item of the array paired with the row whose URL it holds at `relative`."""
    by_url = {str(row[url]): row for row in rows if row.get(url) is not None}
    for _, item in select(array, document):
        for value, row in by_url.items():
            if any(path == relative for path in holding(item, value, schema.fields[url], ctx)):
                yield item, row
                break


def _steps(source: JsonSource, path: str) -> FieldSteps:
    # A URL a state document holds publishes as written, relative or not; the url normalizer resolves it to compare.
    return FieldSteps(steps=[JsonPathStep(jsonpath=path, source=source, post=[])], status="uncorroborated")
