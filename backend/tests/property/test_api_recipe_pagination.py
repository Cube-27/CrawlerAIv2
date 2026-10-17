"""A listing recipe's pagination (Appendix A #59, SPEC-09 §4.8): the kind a series of calls follows is inferred from
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
    next_link,
    next_request,
    with_body_value,
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


@given(
    start=st.integers(min_value=0, max_value=3), step=st.integers(min_value=1, max_value=30), count=st.integers(3, 6)
)
def test_a_first_call_without_the_page_parameter_still_shows_the_step(start: int, step: int, count: int) -> None:
    paging = ParamPagination(kind="param", where="query", name="page", start=start, step=step, rows=ROWS)
    calls = _series(paging, JsonRequest(f"{API}?q=x", API), count, lambda n: ({"items": _rows(n)}, ()))
    bare = JsonRequest(f"{API}?q=x", API)
    first = _call(0, bare, calls[0].document)

    assert infer([first, *calls[1:]], ROWS) == paging


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


@given(tokens=st.lists(_token, min_size=2, max_size=6, unique=True), relative=st.booleans())
def test_a_next_url_in_the_answer_is_followed(tokens: list[str], relative: bool) -> None:
    paging = NextUrlPagination(kind="next_url", next="$['links']['next']", rows=ROWS)

    def respond(n: int) -> tuple[JsonValue, HeaderList]:
        target = f"/v2/items?token={tokens[n]}"
        return {"items": _rows(n), "links": {"next": target if relative else f"https://api.example.test{target}"}}, ()

    calls = _series(paging, JsonRequest(API, API), len(tokens), respond)

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


@given(count=_calls)
def test_two_varying_request_values_leave_the_series_without_pagination(count: int) -> None:
    calls = [
        _call(n, JsonRequest(f"{API}?page={n + 1}&t={1000 + 7 * n}", API), {"items": _rows(n)}) for n in range(count)
    ]

    assert infer(calls, ROWS) is None


def test_one_call_shows_no_pagination() -> None:
    assert infer([_call(0, JsonRequest(f"{API}?page=1", API), {"items": _rows(0)})], ROWS) is None


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


@given(value=st.integers(min_value=0, max_value=10**6), as_string=st.booleans())
def test_a_body_value_keeps_the_json_type_the_captured_body_gave_it(value: int, as_string: bool) -> None:
    body = json.dumps({"variables": {"page": "1" if as_string else 1, "q": "x"}})

    changed = with_body_value(body, "$['variables']['page']", value)

    assert changed is not None
    assert json.loads(changed) == {"variables": {"page": str(value) if as_string else value, "q": "x"}}


def test_a_body_without_the_path_s_parent_is_not_paged() -> None:
    assert with_body_value('{"q": 1}', "$['variables']['page']", 2) is None
    assert with_body_value("not json", "$['page']", 2) is None
    assert json.loads(with_body_value('{"q": 1}', "$['page']", 2) or "") == {"q": 1, "page": 2}


@given(relation=st.sampled_from(["next", "Next", "prev next", "next last"]))
def test_the_first_link_whose_relation_types_hold_next_is_the_target(relation: str) -> None:
    headers = (
        ("link", '</a>; rel="first"'),
        ("Link", f'</b?x=1>; rel="{relation}"; anchor="/c", </d>; rel="next"'),
    )

    assert next_link(headers, "https://api.example.test/v2/") == "https://api.example.test/b?x=1"
