"""A list an API serves in pages, fetched whole (SPEC-15 §4.10): the adapter says how to ask the next page and how the
pages merge, and this module walks them through the caller's `send`, which is polite per request (robots.txt, the
host's rate; SPEC-15 §4.6).

The walk ends when the adapter has no next request, when the rows reach the request's target (`FetchPolicy.max_rows`,
soft: whole pages are kept) or the hard cap, or when the time budget is spent. A later page that fails ends the walk
with the pages already read, as an answer with fewer rows; only the first page decides the outcome. An empty page ends
the walk, so an adapter's next request cannot loop.
"""

import json
import time
from collections.abc import Callable, Sequence
from typing import Final

from pydantic import JsonValue

from crawlerai.acquire.api import JsonFetcher, JsonRequest
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.storage.capture_bundle import CaptureBundle, sha256_hex

# The most rows one adapter list collects, whatever the request asks.
MAX_ROWS: Final = 1000
# The time the pages after the first may take together: a scrape's default timeout is 60 s, which its extraction shares.
BUDGET_S: Final = 30.0

NextPage = Callable[[Sequence[JsonValue]], JsonRequest | None]  # the answers so far -> the next page's request
Merge = Callable[[Sequence[JsonValue]], JsonValue]  # the answers -> the one answer the shapes read
Rows = Callable[[JsonValue], int]  # an answer -> its row count


async def fetch_pages(
    first: JsonRequest,
    policy: FetchPolicy,
    send: JsonFetcher,
    *,
    next_page: NextPage,
    merge: Merge,
    rows: Rows,
    clock: Callable[[], float] = time.monotonic,
) -> FetchResult:
    """The list from `first` on, as one result: the first page's capture, its body the merged answer. A list of one
    page is returned as it was answered."""
    result = await send(first, policy)
    if result.block_class != "ok":
        return result
    deadline = clock() + BUDGET_S
    target = min(policy.max_rows or MAX_ROWS, MAX_ROWS)
    answers: list[JsonValue] = [json.loads(result.bundle.body)]  # `fetch_json` checked that an `ok` body is JSON
    kept = result
    count = rows(answers[0])
    progress = count
    while count < target and progress and clock() < deadline and (request := next_page(answers)) is not None:
        page = await send(request, policy)
        if page.block_class != "ok":
            break
        answers.append(json.loads(page.bundle.body))
        progress = rows(answers[-1])  # an empty page ends the list, whatever the adapter asks next
        count += progress
        kept = kept.model_copy(
            update={"attempts": (*kept.attempts, *page.attempts), "duration_ms": kept.duration_ms + page.duration_ms}
        )
    if len(answers) == 1:
        return result
    return _merged(kept, result, json.dumps(merge(answers), ensure_ascii=False).encode())


def _merged(kept: FetchResult, first: FetchResult, body: bytes) -> FetchResult:
    manifest = first.bundle.manifest.model_copy(update={"html_sha256": sha256_hex(body)})
    return kept.model_copy(update={"bundle": CaptureBundle(manifest=manifest, body=body, network=())})
