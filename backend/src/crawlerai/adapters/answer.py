"""What an adapter does with the answer of its request, beyond reading it as the shapes say (adapters spec): an
answer with no row is not served, and an answer that is not JSON (a feed, a page embedding data) or that several
requests made is recorded as the one JSON document its shapes read."""

import json
from collections.abc import Callable

from pydantic import JsonValue

from crawlerai.acquire.outcome import as_error
from crawlerai.acquire.types import FetchResult
from crawlerai.adapters.base import NOT_SERVED
from crawlerai.core import json_text
from crawlerai.storage.capture_bundle import CaptureBundle, sha256_hex

# RFC 8259 §11: JSON's media type, which defines no charset parameter.
_JSON_TYPE = ("Content-Type", "application/json")


def recorded(result: FetchResult, answer: JsonValue) -> FetchResult:
    """`result`, its capture's body the JSON text of `answer`; the request's attempts and timing are kept."""
    return with_body(result, result, json.dumps(answer, ensure_ascii=False).encode())


def with_body(kept: FetchResult, first: FetchResult, body: bytes) -> FetchResult:
    """`kept` (the attempts of every request), its capture that of `first` with `body`: the one answer of a list.
    The body is JSON text in UTF-8 (RFC 8259 §8.1), so its Content-Type says so in place of the answer's own, whose
    charset would decode it wrongly (`decode_body`)."""
    original = first.bundle.manifest
    response = (*((n, v) for n, v in original.headers.response if n.lower() != "content-type"), _JSON_TYPE)
    manifest = original.model_copy(
        update={"html_sha256": sha256_hex(body), "headers": original.headers.model_copy(update={"response": response})}
    )
    return kept.model_copy(update={"bundle": CaptureBundle(manifest=manifest, body=body, network=())})


def serving(result: FetchResult, rows: Callable[[JsonValue], int]) -> FetchResult:
    """`result`, or `NOT_SERVED` when the platform answered without a row: a tenant it holds none for (some answer 200
    with an empty list for an unknown tenant)."""
    if result.block_class != "ok":
        return result
    return result if rows(json_text.parse(result.bundle.body)) else as_error(result, NOT_SERVED)
