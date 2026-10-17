"""Captured network calls as a data source (Appendix A #58): which calls are readable, how they group into endpoints,
and which array of a call holds the rows a page shows. Synthetic pages and bodies under RFC 2606 names (C9)."""

import hashlib
import json

from hypothesis import given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.collect.network_match import data_calls, endpoint_key, row_series, url_shape
from crawlerai.content.page import ParsedPage
from crawlerai.storage.capture_bundle import NetworkBody, network_file

API = "https://api.example.test"
_segment = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=8)
_names = st.lists(_segment, min_size=3, max_size=8, unique=True)


def _page(shown: list[str], *bodies: tuple[str, JsonValue], status: int = 200) -> ParsedPage:
    html = "<html><body><ul>" + "".join(f"<li>{text}</li>" for text in shown) + "</ul></body></html>"
    data = tuple(json.dumps(body).encode() for _, body in bodies)
    entries = tuple(
        NetworkBody(
            url=url,
            status=status,
            content_type="application/json",
            sha256=hashlib.sha256(raw).hexdigest(),
            file=network_file(i),
            method="GET",
        )
        for i, ((url, _), raw) in enumerate(zip(bodies, data, strict=True))
    )
    return ParsedPage(html, data, entries)


def _items(names: list[str]) -> list[JsonValue]:
    return [{"name": f"Item {name}", "kind": "same for all"} for name in names]


@given(_names, _segment, _segment)
def test_urls_of_one_endpoint_share_a_shape_whatever_their_segment_and_query_values(
    path: list[str], first: str, second: str
) -> None:
    one = f"{API}/{'/'.join(path)}/{first}?page={first}&q=x"
    other = f"{API}/{'/'.join(path)}/{second}?page={second}&q=y"

    assert url_shape(one) == url_shape(other)
    assert endpoint_key("get", one, None) == endpoint_key("GET", other, None)


@given(_segment)
def test_query_names_segment_counts_and_request_body_shapes_tell_endpoints_apart(value: str) -> None:
    base = f"{API}/items?page={value}"

    assert url_shape(base) != url_shape(f"{API}/items?offset={value}")
    assert url_shape(base) != url_shape(f"{API}/items/{value}?page={value}")
    body = json.dumps({"query": "q", "variables": {"first": 10}})
    other = json.dumps({"query": "q", "variables": {"after": "c1"}})
    assert endpoint_key("POST", base, body) != endpoint_key("POST", base, other)


@given(_names)
def test_the_array_whose_items_each_show_a_string_of_their_own_is_the_rows(names: list[str]) -> None:
    body: JsonValue = {"meta": {"title": "Listing"}, "data": {"results": _items(names)}}
    page = _page([f"Item {name}" for name in names], (f"{API}/items?page=1", body))

    (call,) = data_calls(page)

    assert (call.rows, call.row_hits) == ("$['data']['results'][*]", len(names))


@given(_names)
def test_items_the_page_does_not_show_are_no_rows(names: list[str]) -> None:
    page = _page(["Something else entirely"], (f"{API}/items", {"results": _items(names)}))

    assert data_calls(page) == []


@given(_names)
def test_a_string_every_item_repeats_does_not_make_them_rows(names: list[str]) -> None:
    # Each item holds the visible "same for all" and its own unshown name: nothing of its own is shown.
    page = _page(["same for all", "Listing"], (f"{API}/items", {"title": "Listing", "results": _items(names)}))

    (call,) = data_calls(page)

    assert (call.rows, call.row_hits, call.visible) == (None, 0, 1 + len(names))


@given(_names)
def test_fewer_items_than_a_listing_shows_are_no_rows(names: list[str]) -> None:
    two = names[:2]
    page = _page([f"Item {name}" for name in two], (f"{API}/items", {"results": _items(two)}))

    (call,) = data_calls(page)

    assert (call.rows, call.row_hits) == (None, 0)


@given(_names, st.integers(300, 599))
def test_a_call_that_did_not_succeed_carries_no_data(names: list[str], status: int) -> None:
    page = _page([f"Item {name}" for name in names], (f"{API}/items", {"results": _items(names)}), status=status)

    assert data_calls(page) == []


@given(_names, _names)
def test_calls_of_one_endpoint_group_into_one_series_in_capture_order(first: list[str], second: list[str]) -> None:
    other = [f"o{name}" for name in second]
    shown = [f"Item {name}" for name in [*first, *other]]
    page = _page(
        shown,
        (f"{API}/config", {"groups": _items(["x", "y"])}),
        (f"{API}/items?page=1", {"results": _items(first)}),
        (f"{API}/items?page=2", {"results": _items(other)}),
    )

    series = row_series(data_calls(page))

    assert [[data.call.index for data in group] for group in series] == [[1, 2]]


@given(_names)
def test_a_request_sent_again_counts_once_in_its_series(names: list[str]) -> None:
    url = f"{API}/items?page=1"
    page = _page(
        [f"Item {name}" for name in names], (url, {"results": _items(names)}), (url, {"results": _items(names)})
    )

    assert [[data.call.index for data in group] for group in row_series(data_calls(page))] == [[0]]


@given(_names, _names)
def test_calls_to_two_paths_of_one_shape_are_two_series(first: list[str], second: list[str]) -> None:
    other = [f"o{name}" for name in second]
    page = _page(
        [f"Item {name}" for name in [*first, *other]],
        (f"{API}/products?page=1", {"results": _items(first)}),
        (f"{API}/categories?page=1", {"results": _items(other)}),
    )

    series = row_series(data_calls(page))

    assert sorted([data.call.index for data in group] for group in series) == [[0], [1]]
