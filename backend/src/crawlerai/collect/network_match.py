"""Captured network calls as a data source (Appendix A #58, ARCHITECTURE §7.2, §8.1): the one reader of a browser
capture's network bodies that the `xhr` collector and API discovery share (C8).

A call is readable when its response was a success (RFC 9110 §15.3) and its body is JSON (`network_json`, RFC 8259).
Calls group into endpoints by request method, URL shape (the origin, whether there is a path, its segment count and the
query names in order: the parts that vary are what a recipe binds) and request body shape (the paths of a JSON body's
values, array indices written `[*]`, or the body itself when it is not JSON: one GraphQL URL serves many queries).

A call carries data for the page when one of its strings is visible in the page text (`VisibleIndex`): the page shows
what the call loaded. Its rows are the object items of the one array whose items show the most of their own: an item
counts when it holds a visible string no other item of the array holds (a value every item repeats, a currency or a
category, says nothing of which item is shown). JSON numbers are not counted: a page shows a number formatted (a
currency sign, grouping), and a short number matches any counter on the page. An array whose items show fewer than
`MIN_ITEMS` is no listing's rows (`acquire.items`).
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Final
from urllib.parse import urlsplit

from pydantic import JsonValue

from crawlerai.acquire.items import MIN_ITEMS
from crawlerai.collect import json_doc
from crawlerai.content.page import ParsedPage
from crawlerai.storage.capture_bundle import NetworkBody, network_json

# RFC 9110 §15.3: the 2xx class.
SUCCESS: Final = range(200, 300)
# What the URLs of one endpoint's requests share: the origin, whether there is a path, its segment count, and the
# query names in order.
UrlShape = tuple[str, bool, int, tuple[str, ...]]
# RFC 9535 §2.5.1.2: the wildcard selector, which a row query ends with.
_EVERY_ITEM: Final = "[*]"


@dataclass(frozen=True)
class EndpointKey:
    """What the requests of one endpoint share across calls and pages. `method` is None in bundles written before
    the request method was kept."""

    method: str | None
    url: UrlShape
    body: tuple[str, ...] | None


def endpoint_key(method: str | None, url: str, body: str | None) -> EndpointKey:
    return EndpointKey(None if method is None else method.upper(), url_shape(url), body_shape(body))


def url_shape(url: str) -> UrlShape:
    parts = urlsplit(url)
    names = tuple(item.partition("=")[0] for item in parts.query.split("&")) if parts.query else ()
    segments = len(parts.path[1:].split("/")) if parts.path else 0
    return f"{parts.scheme}://{parts.netloc}", bool(parts.path), segments, names


def body_shape(body: str | None) -> tuple[str, ...] | None:
    if body is None:
        return None
    try:
        document = json_doc.parse(body)
    except ValueError:
        return (body,)
    leaves = {path for path, value in json_doc.nodes(document, wildcard=True) if not isinstance(value, (dict, list))}
    return tuple(sorted(leaves))


@dataclass(frozen=True)
class Call:
    """One readable captured call: its index among the bundle's network bodies, its manifest entry and its body."""

    index: int
    entry: NetworkBody
    document: JsonValue

    @cached_property
    def endpoint(self) -> EndpointKey:
        return endpoint_key(self.entry.method, self.entry.url, self.entry.request_body)


def read_calls(entries: Sequence[NetworkBody], bodies: Sequence[bytes]) -> Iterator[Call]:
    """The readable calls of a capture, in capture order."""
    for index, (entry, data) in enumerate(zip(entries, bodies, strict=True)):
        if entry.status not in SUCCESS:
            continue
        try:
            document = network_json(data)
        except ValueError:
            continue
        yield Call(index, entry, document)


def visible_paths(document: JsonValue, page: ParsedPage, memo: dict[str, bool] | None = None) -> set[str]:
    """The paths of the strings and numbers of `document` the page shows; `memo` keeps the answers for texts already
    looked up on this page."""
    memo = {} if memo is None else memo
    return {path for path, value in json_doc.scalars(document) if _shown(str(value), page, memo)}


def _shown(text: str, page: ParsedPage, memo: dict[str, bool]) -> bool:
    if text not in memo:
        memo[text] = page.visible_values.visible(text)
    return memo[text]


@dataclass(frozen=True)
class DataCall:
    """A call that carries data for the page: how many of its strings and numbers the page shows, and its row query
    (`$…[*]`, selecting the items of its rows array) with how many of those items show a string of their own."""

    call: Call
    visible: int
    rows: str | None
    row_hits: int


def data_calls(page: ParsedPage) -> list[DataCall]:
    """The page's calls that carry data, best first: by row hits, then visible values; ties keep capture order. Empty
    when the page does not hold its bodies' manifest entries."""
    if len(page.network_entries) != len(page.network):
        return []
    found: list[DataCall] = []
    memo: dict[str, bool] = {}
    for call in read_calls(page.network_entries, page.network):
        visible = len(visible_paths(call.document, page, memo))
        if visible:
            rows, hits = _rows(call.document, page, memo)
            found.append(DataCall(call, visible, rows, hits))
    return sorted(found, key=lambda data: (-data.row_hits, -data.visible))


def row_series(calls: Sequence[DataCall]) -> list[tuple[DataCall, ...]]:
    """The calls with rows grouped by endpoint and row query, each group in capture order: the pages of one listing a
    page loaded (a first batch, then more on scrolling). A request sent again (same method, URL and body) answers with
    the same items, so only its first call counts. Groups come in the order of their best call in `calls`."""
    best: dict[tuple[EndpointKey, str], int] = {}  # each group's best rank in `calls`
    for rank, data in enumerate(calls):
        if data.rows is not None:
            best.setdefault((data.call.endpoint, data.rows), rank)
    groups: dict[tuple[EndpointKey, str], dict[tuple[str | None, str, str | None], DataCall]] = {}
    for data in sorted(calls, key=lambda data: data.call.index):
        if data.rows is not None:
            entry = data.call.entry
            group = groups.setdefault((data.call.endpoint, data.rows), {})
            group.setdefault((entry.method, entry.url, entry.request_body), data)
    return [tuple(groups[key].values()) for key in sorted(groups, key=best.__getitem__)]


def _rows(document: JsonValue, page: ParsedPage, memo: dict[str, bool]) -> tuple[str | None, int]:
    best: tuple[str | None, int] = (None, 0)
    for path, value in json_doc.nodes(document):
        if isinstance(value, list) and json_doc.is_query(query := path + _EVERY_ITEM):
            hits = _own_hits(value, page, memo)
            if hits >= MIN_ITEMS and hits > best[1]:
                best = (query, hits)
    return best


def _own_hits(items: list[JsonValue], page: ParsedPage, memo: dict[str, bool]) -> int:
    """How many object items of `items` hold a visible string no other item holds."""
    strings = [_strings(item) for item in items if isinstance(item, dict)]
    if len(strings) < MIN_ITEMS:
        return 0
    holders: dict[str, int] = {}
    for own in strings:
        for text in own:
            holders[text] = holders.get(text, 0) + 1
    return sum(any(holders[text] == 1 and _shown(text, page, memo) for text in own) for own in strings)


def _strings(item: JsonValue) -> set[str]:
    return {value for _, value in json_doc.scalars(item) if isinstance(value, str)}
