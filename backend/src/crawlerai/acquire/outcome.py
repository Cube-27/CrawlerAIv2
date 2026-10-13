"""One fetch attempt as a `FetchResult`: the manifest, the attempt record and the bundle, built the same way by every
fetcher (SPEC-02 §4.2, §4.4)."""

import time
from dataclasses import dataclass
from datetime import datetime

from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    HeaderList,
    Headers,
    NetworkBody,
    sha256_hex,
)

__all__ = ["Content", "Exchange", "fetch_result"]


@dataclass(frozen=True)
class Exchange:
    """The last request and response of a fetch. `status` is 0 when no status line arrived (D-0127)."""

    url: str
    status: int
    request_headers: HeaderList
    response_headers: HeaderList


@dataclass(frozen=True)
class Content:
    body: bytes
    raw_body: bytes | None = None  # browser only: the navigation response body
    network: tuple[tuple[NetworkBody, bytes], ...] = ()  # browser only: captured JSON bodies


def fetch_result(
    *,
    url: str,
    method: CaptureMethod,
    policy: FetchPolicy,
    engine_version: str,
    fetched_at: datetime,
    started: float,
    exchange: Exchange | None,
    content: Content,
    block_class: BlockClass,
    error: str | None,
    timings: dict[str, int] | None = None,
) -> FetchResult:
    """`started` is the `time.monotonic()` reading when the fetch began; `timings` are added to its total."""
    if error is not None:
        # An error keeps no body: it yields no records (INV-11), and a partial body would mislead a replay.
        content = Content(body=b"")
    exchange = exchange or Exchange(url=url, status=0, request_headers=(), response_headers=())
    duration_ms = round((time.monotonic() - started) * 1000)
    raw_body = content.raw_body
    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=exchange.url,
        fetched_at=fetched_at,
        method=method,
        status_code=exchange.status,
        block_class=block_class,
        headers=Headers(request=exchange.request_headers, response=exchange.response_headers),
        timings_ms={"total": duration_ms, **(timings or {})},
        html_sha256=sha256_hex(content.body),
        raw_html_sha256=None if raw_body is None else sha256_hex(raw_body),
        network_bodies=tuple(entry for entry, _ in content.network),
        fetch_policy=policy.model_dump(mode="json"),
        engine_version=engine_version,
    )
    status = exchange.status or None
    attempt = AttemptRecord(method=method, status=status, block_class=block_class, duration_ms=duration_ms, error=error)
    bundle = CaptureBundle(
        manifest=manifest, body=content.body, network=tuple(data for _, data in content.network), raw_body=raw_body
    )
    return FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=(attempt,))
