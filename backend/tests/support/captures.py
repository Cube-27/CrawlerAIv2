"""Synthetic captures and fetch results, the one builder of each a test uses (names per RFC 2606).

`capture` is a stored page (a `CaptureBundle`) for the tests that read one; `calls` are the network bodies it carries.
`fetched` is the result of one rung's fetch, as `acquire.outcome.fetch_result` reports it: the tests of the fetch path
build their results with the code the rungs use. `ScriptedRung` is a rung that answers every URL with one outcome.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import JsonValue

from crawlerai.acquire.outcome import Content, Exchange, as_error, fetch_result
from crawlerai.acquire.stored_fetch import policy_with_attempts
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    HeaderList,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

__all__ = [
    "ENGINE_VERSION",
    "FETCHED_AT",
    "HTML",
    "PAGE_URL",
    "STATUS",
    "ScriptedRung",
    "call",
    "calls",
    "capture",
    "fetched",
    "with_attempts",
]

ENGINE_VERSION = "0+cal.0"
PAGE_URL = "https://shop.example.test/p/1"
FETCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)
HTML: HeaderList = (("Content-Type", "text/html"),)
# The status a server answers with for each outcome a rung can report (RFC 9110 §15).
STATUS: dict[BlockClass, int] = {
    "ok": 200,
    "shell": 200,
    "blocked": 403,
    "not_found": 404,
    "error": 500,
    "auth_wall": 401,
    "soft_404": 200,
    "geo_redirect": 200,
    "redirected_to_listing": 200,
    "unsupported_media": 200,
}

Network = tuple[tuple[NetworkBody, bytes], ...]


def call(
    index: int, url: str, body: bytes, *, content_type: str | None = "application/json", **entry: Any
) -> tuple[NetworkBody, bytes]:
    """The `index`th network body of a capture: a 200 from `url`, filed where the bundle expects it; `entry` sets the
    rest of its `NetworkBody` (method, request headers, resource type...)."""
    manifest_entry = NetworkBody.model_validate(
        {
            "url": url,
            "status": 200,
            "content_type": content_type,
            "sha256": sha256_hex(body),
            "file": network_file(index),
            **entry,
        }
    )
    return manifest_entry, body


def calls(
    answers: Iterable[tuple[str, bytes]], *, content_type: str | None = "application/json", **entry: Any
) -> Network:
    """The network bodies `(url, body)` of a capture, in order, each as `call` files it."""
    return tuple(call(i, url, body, content_type=content_type, **entry) for i, (url, body) in enumerate(answers))


def capture(
    body: bytes,
    *,
    url: str = PAGE_URL,
    final_url: str | None = None,
    method: CaptureMethod = "http",
    status: int = 200,
    block_class: BlockClass = "ok",
    headers: HeaderList = HTML,
    request_headers: HeaderList = (),
    network: Network = (),
    raw_body: bytes | None = None,
    policy: FetchPolicy | dict[str, JsonValue] | None = None,
    fetched_at: datetime = FETCHED_AT,
    capture_id: UUID | None = None,
    timings_ms: dict[str, int] | None = None,
) -> CaptureBundle:
    """A capture of `url` answering `body`; `final_url` is where its redirects ended (default: `url`), `policy` the
    fetch policy its manifest keeps (default: none kept)."""
    kept = policy.model_dump(mode="json") if isinstance(policy, FetchPolicy) else policy or {}
    manifest = CaptureManifest(
        capture_id=capture_id or uuid7(),
        url=url,
        final_url=final_url or url,
        fetched_at=fetched_at,
        method=method,
        status_code=status,
        block_class=block_class,
        headers=Headers(request=request_headers, response=headers),
        timings_ms=timings_ms or {},
        html_sha256=sha256_hex(body),
        raw_html_sha256=None if raw_body is None else sha256_hex(raw_body),
        network_bodies=tuple(entry for entry, _ in network),
        fetch_policy=kept,
        engine_version=ENGINE_VERSION,
    )
    return CaptureBundle(manifest=manifest, body=body, network=tuple(data for _, data in network), raw_body=raw_body)


def fetched(
    url: str,
    status: int = 200,
    body: bytes = b"",
    headers: HeaderList = (),
    *,
    block_class: BlockClass = "ok",
    error: str | None = None,
    method: CaptureMethod = "http",
    policy: FetchPolicy | None = None,
    final_url: str | None = None,
    challenge: str | None = None,
    network: Network = (),
    fetched_at: datetime | None = None,
) -> FetchResult:
    """The result of one fetch of `url` by one rung, as the rung reports it, taking 1 ms; `final_url` is where its
    redirects ended (default: `url`)."""
    return fetch_result(
        url=url,
        method=method,
        policy=policy or FetchPolicy(),
        engine_version=ENGINE_VERSION,
        fetched_at=fetched_at or datetime.now(UTC),
        started=time.monotonic() - 0.001,
        exchange=Exchange(url=final_url or url, status=status, request_headers=(), response_headers=headers),
        content=Content(body=body, network=network),
        block_class=block_class,
        error=error,
        challenge=challenge,
    )


def with_attempts(result: FetchResult, attempts: tuple[AttemptRecord, ...]) -> FetchResult:
    """`result` as a fetch that tried every rung of `attempts` (the last one kept), as its manifest records them."""
    manifest = result.bundle.manifest.model_copy(
        update={"fetch_policy": policy_with_attempts(result.bundle.manifest.fetch_policy, attempts)}
    )
    return result.model_copy(
        update={"bundle": result.bundle.model_copy(update={"manifest": manifest}), "attempts": attempts}
    )


@dataclass
class ScriptedRung:
    """A rung answering every URL with one outcome by `method`, and recording each URL and policy it got. The body is
    `body`, else `ok_body` for an `ok` outcome and `other_body` for any other; the status is `status`, else the
    outcome's (`STATUS`). `reason` makes the answer an adapter answer that does not serve the page (`as_error`)."""

    method: CaptureMethod = "http"
    block_class: BlockClass = "ok"
    status: int | None = None
    body: bytes | None = None
    ok_body: bytes = b"<html></html>"
    other_body: bytes = b""
    headers: HeaderList = ()
    error: str | None = None
    challenge: str | None = None
    reason: str | None = None
    calls: list[tuple[str, FetchPolicy]] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [url for url, _ in self.calls]

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append((url, policy))
        ok = self.block_class == "ok"
        result = fetched(
            url,
            STATUS[self.block_class] if self.status is None else self.status,
            self.body if self.body is not None else self.ok_body if ok else self.other_body,
            self.headers,
            block_class=self.block_class,
            error=self.error,
            method=self.method,
            policy=policy,
            challenge=self.challenge,
        )
        return result if self.reason is None else as_error(result, self.reason)
