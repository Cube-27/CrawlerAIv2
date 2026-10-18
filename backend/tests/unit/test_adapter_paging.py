"""The paged list walk adapters share (SPEC-15 §4.10): pages are asked while the adapter names a next one, the rows
stay under the request's target and the hard cap, and a later page that fails ends the walk without losing the rows."""

import asyncio
import json
from collections.abc import Callable, Sequence

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.adapters.paging import BUDGET_S, MAX_ROWS, fetch_pages

ScriptedApi = Callable[[Callable[[JsonRequest], bytes], list[JsonRequest]], JsonFetcher]  # `scripted_api` (conftest)

ENDPOINT = "https://api.example.test/rows"
SIZE = 3


def _request(offset: int) -> JsonRequest:
    return JsonRequest(url=f"{ENDPOINT}?offset={offset}", page_url="https://careers.example.test/")


def _offset(request: JsonRequest) -> int:
    return int(request.url.rsplit("=", 1)[1])


def _rows(answer: JsonValue) -> int:
    return len(answer) if isinstance(answer, list) else 0


def _next(answers: Sequence[JsonValue]) -> JsonRequest | None:
    return _request(sum(_rows(a) for a in answers))


def _merge(answers: Sequence[JsonValue]) -> JsonValue:
    return [row for answer in answers if isinstance(answer, list) for row in answer]


def _walk(
    send: JsonFetcher, policy: FetchPolicy | None = None, clock: Callable[[], float] | None = None
) -> FetchResult:
    return asyncio.run(
        fetch_pages(
            _request(0),
            policy or FetchPolicy(),
            send,
            next_page=_next,
            merge=_merge,
            rows=_rows,
            **({} if clock is None else {"clock": clock}),
        )
    )


def _table(total: int) -> Callable[[JsonRequest], bytes]:
    """Pages of `SIZE` rows from a list of `total` rows (the row's value is its index); an empty page past the end."""

    def answer(request: JsonRequest) -> bytes:
        start = _offset(request)
        return json.dumps(list(range(start, min(start + SIZE, total)))).encode()

    return answer


def test_every_page_is_read_and_merged_into_the_first_pages_capture(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    result = _walk(scripted_api(_table(8), sent))

    assert json.loads(result.bundle.body) == list(range(8))
    assert [_offset(r) for r in sent] == [0, 3, 6, 8]  # the empty page past the end stops the walk
    manifest = result.bundle.manifest
    assert (manifest.url, manifest.final_url, manifest.block_class) == (
        "https://careers.example.test/",
        f"{ENDPOINT}?offset=0",
        "ok",
    )
    assert len(result.attempts) == len(sent)


def test_a_list_of_one_page_is_returned_as_answered(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    def stops(_answers: Sequence[JsonValue]) -> JsonRequest | None:
        return None

    result = asyncio.run(
        fetch_pages(
            _request(0),
            FetchPolicy(),
            scripted_api(_table(2), sent),
            next_page=stops,
            merge=_merge,
            rows=_rows,
        )
    )

    assert result.bundle.body == b"[0, 1]"
    assert len(sent) == 1


def test_the_walk_stops_at_the_requests_row_target_keeping_whole_pages(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    result = _walk(scripted_api(_table(100), sent), FetchPolicy(max_rows=4))

    assert json.loads(result.bundle.body) == list(range(6))  # a soft target: the page that reaches it is kept whole
    assert [_offset(r) for r in sent] == [0, 3]


def test_the_hard_cap_bounds_a_target_above_it(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    result = _walk(scripted_api(_table(MAX_ROWS * 2), sent), FetchPolicy(max_rows=MAX_ROWS * 2))

    rows = json.loads(result.bundle.body)
    assert MAX_ROWS <= len(rows) < MAX_ROWS + SIZE
    assert len(sent) == -(-MAX_ROWS // SIZE)


def test_a_later_page_that_fails_ends_the_walk_with_the_rows_read(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []
    answer = _table(100)

    def fails_after_two_pages(request: JsonRequest) -> bytes:
        return b"not json" if _offset(request) >= 2 * SIZE else answer(request)

    result = _walk(scripted_api(fails_after_two_pages, sent))

    assert (result.block_class, json.loads(result.bundle.body)) == ("ok", list(range(2 * SIZE)))
    # The failed page's attempt is kept, last: its refusal or slow-down is the caller's to read.
    assert [(a.block_class, a.error) for a in result.attempts] == [
        ("ok", None),
        ("ok", None),
        ("error", "decode_error"),
    ]
    assert len(sent) == 3


def test_a_second_page_that_fails_leaves_the_first_pages_answer_with_both_attempts(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []
    answer = _table(100)

    def fails_on_the_second_page(request: JsonRequest) -> bytes:
        return b"not json" if _offset(request) else answer(request)

    result = _walk(scripted_api(fails_on_the_second_page, sent))

    assert (result.block_class, json.loads(result.bundle.body)) == ("ok", list(range(SIZE)))
    assert [a.error for a in result.attempts] == [None, "decode_error"]


def test_a_first_page_that_fails_is_the_outcome(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []

    result = _walk(scripted_api(lambda _request: b"not json", sent))

    assert (result.block_class, result.attempts[-1].error, len(sent)) == ("error", "decode_error", 1)


def test_the_walk_stops_when_its_time_budget_is_spent(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []
    ticks = iter([0.0, 1.0, BUDGET_S + 5.0, BUDGET_S + 6.0])

    result = _walk(scripted_api(_table(100), sent), clock=lambda: next(ticks))

    assert json.loads(result.bundle.body) == list(range(2 * SIZE))
    assert len(sent) == 2


def test_a_later_page_may_take_only_the_time_left_in_the_budget(scripted_api: ScriptedApi) -> None:
    sent: list[JsonRequest] = []
    timeouts: list[float] = []
    table = scripted_api(_table(2 * SIZE), sent)

    async def send(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
        timeouts.append(policy.timeout_s)
        return await table(request, policy)

    ticks = iter([0.0, BUDGET_S - 1.0, BUDGET_S - 0.5])

    _walk(send, FetchPolicy(timeout_s=30.0), clock=lambda: next(ticks))

    assert timeouts == [30.0, 1.0, 0.5]  # the first page has the request's own timeout
