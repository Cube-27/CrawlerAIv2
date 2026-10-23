"""A listing recipe's pagination (Appendix A #59): the kind a series of calls follows is inferred from
the calls, and the next request of each kind is the one the series made next. Synthetic calls under RFC 2606 names
(C9): a series is made by the same `next_request` serving uses, and inference must give back the pagination."""

import hashlib
import json
from collections.abc import Callable

from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import JsonValue

from crawlerai.acquire.api import JsonRequest
from crawlerai.collect.network_match import Call
from crawlerai.config_ir.api_recipe.model import (
    CursorPagination,
    LinkPagination,
    NextUrlPagination,
    Pagination,
    ParamPagination,
)
from crawlerai.config_ir.api_recipe.pagination import (
    first_request,
    infer,
    next_request,
)
from crawlerai.storage.capture_bundle import HeaderList, NetworkBody, network_file

API = "https://api.example.test/v2/items"
ROWS = "$['items'][*]"
_word = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8)
_token = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=6, max_size=12)
_calls = st.integers(min_value=2, max_value=6)


def _call(index: int, request: JsonRequest, document: JsonValue, headers: HeaderList = ()) -> Call:
    raw = json.dumps(document).encode()
    entry = NetworkBody(
        url=request.url,
        status=200,
        content_type="application/json",
        sha256=hashlib.sha256(raw).hexdigest(),
        file=network_file(index),
        method=request.method,
        request_body=request.body,
        response_headers=headers,
    )
    return Call(index, entry, document)


# A response for page `n` of a series: its rows, plus what the kind under test puts in it.
Respond = Callable[[int], tuple[JsonValue, HeaderList]]


def _series(pagination: Pagination, start: JsonRequest, count: int, respond: Respond) -> list[Call]:
    """The calls a page makes when it follows `pagination` from `start`, each answered by `respond`."""
    calls: list[Call] = []
    request: JsonRequest | None = first_request(pagination, start)
    for number in range(count):
        assert request is not None
        document, headers = respond(number)
        calls.append(_call(number, request, document, headers))
        request = next_request(pagination, request, number + 1, document, headers)
    return calls


def _rows(number: int) -> list[JsonValue]:
    return [{"name": f"item {number}-{i}"} for i in range(3)]


@given(
    start=st.integers(min_value=0, max_value=5),
    step=st.integers(min_value=1, max_value=50),
    count=_calls,
    name=_word,
    in_body=st.booleans(),
    constant=_word,
)
def test_a_page_number_or_offset_is_inferred_from_its_steps(
    start: int, step: int, count: int, name: str, in_body: bool, constant: str
) -> None:
    assume(name != "q")
    if in_body:
        body = json.dumps({"query": constant, "variables": {name: 0}})
        paging = ParamPagination(
            kind="param", where="body", name=f"$['variables']['{name}']", start=start, step=step, rows=ROWS
        )
        request = JsonRequest(API, API, "POST", body=body)
    else:
        paging = ParamPagination(kind="param", where="query", name=name, start=start, step=step, rows=ROWS)
        request = JsonRequest(f"{API}?q={constant}", API)

    calls = _series(paging, request, count, lambda n: ({"items": _rows(n)}, ()))

    assert infer(calls, ROWS) == paging


@given(tokens=st.lists(_token, min_size=2, max_size=6, unique=True), in_body=st.booleans())
def test_a_cursor_is_the_value_the_previous_answer_holds(tokens: list[str], in_body: bool) -> None:
    if in_body:
        paging = CursorPagination(
            kind="cursor", where="body", name="$['variables']['after']", cursor="$['page']['end']", rows=ROWS
        )
        request = JsonRequest(API, API, "POST", body=json.dumps({"query": "q", "variables": {"after": None}}))
    else:
        paging = CursorPagination(kind="cursor", where="query", name="after", cursor="$['page']['end']", rows=ROWS)
        request = JsonRequest(f"{API}?size=3", API)

    calls = _series(paging, request, len(tokens), lambda n: ({"items": _rows(n), "page": {"end": tokens[n]}}, ()))

    assert infer(calls, ROWS) == paging


@given(count=_calls, extra=st.sampled_from(["", " prev", " last"]), quoted=st.booleans(), upper=st.booleans())
def test_an_rfc_8288_next_link_is_followed(count: int, extra: str, quoted: bool, upper: bool) -> None:
    paging = LinkPagination(kind="link", rows=ROWS)

    def respond(n: int) -> tuple[JsonValue, HeaderList]:
        relation = ("NEXT" if upper else "next") + extra
        rel = f'"{relation}"' if quoted or extra else relation
        link = f'<{API}?cursor=c{n}>; title="page, {n}"; rel={rel}, <{API}?cursor=first>; rel="first"'
        return {"items": _rows(n)}, (("Content-Type", "application/json"), ("Link", link))

    calls = _series(paging, JsonRequest(API, API), count, respond)

    assert infer(calls, ROWS) == paging
    assert [call.entry.url for call in calls[1:]] == [f"{API}?cursor=c{n}" for n in range(count - 1)]


@given(token=_token)
def test_an_answer_without_a_cursor_or_next_url_ends_the_listing(token: str) -> None:
    request = JsonRequest(f"{API}?after={token}", API)
    cursor = CursorPagination(kind="cursor", where="query", name="after", cursor="$['end']", rows=ROWS)
    url = NextUrlPagination(kind="next_url", next="$['next']", rows=ROWS)

    assert next_request(cursor, request, 1, {"items": [], "end": None}, ()) is None
    assert next_request(cursor, request, 1, {"items": [], "end": ""}, ()) is None
    assert next_request(url, request, 1, {"items": []}, ()) is None
    assert next_request(LinkPagination(kind="link", rows=ROWS), request, 1, {}, (("Link", '<x>; rel="prev"'),)) is None


@given(host=_word)
def test_a_next_page_on_another_origin_is_never_requested(host: str) -> None:
    request = JsonRequest(API, API)
    url = NextUrlPagination(kind="next_url", next="$['next']", rows=ROWS)
    elsewhere = f"https://{host}.example.org/v2/items?page=2"

    assert next_request(url, request, 1, {"next": elsewhere}, ()) is None
    link = (("Link", f'<{elsewhere}>; rel="next"'),)
    assert next_request(LinkPagination(kind="link", rows=ROWS), request, 1, {}, link) is None
