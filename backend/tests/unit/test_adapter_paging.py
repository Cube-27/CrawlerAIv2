"""The paged list walk adapters share: pages are asked while the adapter names a next one, the rows
stay under the request's target and the hard cap, and a later page that fails ends the walk without losing the rows."""

import asyncio
import json
from collections.abc import Callable, Sequence

from pydantic import JsonValue

from snowcrawl.acquire.api import JsonFetcher, JsonRequest
from snowcrawl.acquire.types import FetchPolicy, FetchResult
from snowcrawl.adapters.paging import BUDGET_S, fetch_pages

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
