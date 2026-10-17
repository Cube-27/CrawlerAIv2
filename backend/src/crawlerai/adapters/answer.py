"""What an adapter does with the answer of its request, beyond reading it as the shapes say (SPEC-15 §4.2, §4.10): an
answer with no row is not served, and an answer that is not JSON (a feed, a page embedding data) or that several
requests made is recorded as the one JSON document its shapes read."""

import json
from collections.abc import Callable

from pydantic import JsonValue

from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchResult
from crawlerai.adapters.base import NOT_SERVED
from crawlerai.storage.capture_bundle import CaptureBundle, sha256_hex


def recorded(result: FetchResult, answer: JsonValue) -> FetchResult:
    """`result`, its capture's body the JSON text of `answer`; the request's attempts and timing are kept."""
    return with_body(result, result, json.dumps(answer, ensure_ascii=False).encode())


def with_body(kept: FetchResult, first: FetchResult, body: bytes) -> FetchResult:
    """`kept` (the attempts of every request), its capture that of `first` with `body`: the one answer of a list."""
    manifest = first.bundle.manifest.model_copy(update={"html_sha256": sha256_hex(body)})
    return kept.model_copy(update={"bundle": CaptureBundle(manifest=manifest, body=body, network=())})


def serving(result: FetchResult, rows: Callable[[JsonValue], int]) -> FetchResult:
    """`result`, or `NOT_SERVED` when the platform answered without a row: a tenant it holds none for (some answer 200
    with an empty list for an unknown tenant)."""
    if result.block_class != "ok":
        return result
    return result if rows(json.loads(result.bundle.body)) else as_error(result, NOT_SERVED)
