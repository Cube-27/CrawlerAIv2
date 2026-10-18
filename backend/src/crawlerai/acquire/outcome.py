"""One fetch attempt as a `FetchResult`: the manifest, the attempt record and the bundle, built the same way by every
fetcher (SPEC-02 §4.2, §4.4)."""

import time
from dataclasses import dataclass
from datetime import datetime

from crawlerai.acquire.politeness import retry_after
from crawlerai.acquire.ssrf import SSRF_REJECTED
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult, StepOutcome
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.core.proxy import ProxyEndpoint, ProxyPool
from crawlerai.core.redaction import REDACTED
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    HeaderList,
    Headers,
    NetworkBody,
    sha256_hex,
)

__all__ = ["Content", "Exchange", "Traffic", "as_error", "fetch_result", "report_proxy"]


@dataclass(frozen=True)
class Exchange:
    """The last request and response of a fetch. `status` is 0 when no status line arrived (D-0127)."""

    url: str
    status: int
    request_headers: HeaderList
    response_headers: HeaderList


@dataclass
class Traffic:
    """The bytes a fetch's requests have moved so far, both ways, which `proxy_bytes` usage counts for a fetch through
    a pool (D-1381): the HTTP messages of the HTTP and JSON rungs, the tunnelled bytes of the browser's guard."""

    bytes: int = 0


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
    challenge: str | None = None,
    transferred: int = 0,
    steps: tuple[StepOutcome, ...] = (),
    artifacts: dict[str, bytes] | None = None,
) -> FetchResult:
    """`started` is the `time.monotonic()` reading when the fetch began; `timings` are added to its total; `challenge`
    labels the attempt (`acquire.challenge`); `transferred` is the bytes the attempt moved (`Traffic`); `steps` how the
    policy's page steps ended; `artifacts` are the files made of an `ok` page, kept with the result. The caller's header
    values are recorded redacted (D-1432)."""
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
        headers=Headers(request=_redacted(exchange.request_headers, policy), response=exchange.response_headers),
        timings_ms={"total": duration_ms, **(timings or {})},
        html_sha256=sha256_hex(content.body),
        raw_html_sha256=None if raw_body is None else sha256_hex(raw_body),
        network_bodies=tuple(entry for entry, _ in content.network),
        fetch_policy=policy.model_dump(mode="json"),
        engine_version=engine_version,
    )
    status = exchange.status or None
    attempt = AttemptRecord(
        method=method,
        status=status,
        block_class=block_class,
        duration_ms=duration_ms,
        error=error,
        challenge=challenge,
        retry_after=retry_after(exchange.response_headers, fetched_at),
        transferred=transferred,
        steps=steps,
    )
    bundle = CaptureBundle(
        manifest=manifest, body=content.body, network=tuple(data for _, data in content.network), raw_body=raw_body
    )
    kept = artifacts if artifacts and error is None and block_class == "ok" else {}
    return FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=(attempt,), artifacts=kept)


def _redacted(headers: HeaderList, policy: FetchPolicy) -> HeaderList:
    """`headers` with the value of each header the caller set (`RequestContext`) redacted: the caller's values are
    secrets (D-1432)."""
    if policy.context is None or not policy.context.headers:
        return headers
    names = policy.context.header_names()
    return tuple((name, REDACTED if name.lower() in names else value) for name, value in headers)


def as_error(result: FetchResult, reason: str) -> FetchResult:
    """`result` as an `error` outcome for `reason`: an answer that arrived but is not the content the fetch asked for
    (an adapter's answer that does not serve its page, SPEC-15 §4.2). As every error, it keeps no body."""
    manifest = result.bundle.manifest.model_copy(update={"block_class": "error", "html_sha256": sha256_hex(b"")})
    last = result.attempts[-1].model_copy(update={"block_class": "error", "error": reason})
    return FetchResult(
        bundle=CaptureBundle(manifest=manifest, body=b"", network=()),
        duration_ms=result.duration_ms,
        attempts=(*result.attempts[:-1], last),
    )


def report_proxy(pool: ProxyPool | None, endpoint: ProxyEndpoint | None, result: FetchResult) -> None:
    """Record how a fetch through a pool's `endpoint` went (`core.proxy_health`): a block, or a request that got no
    answer (a timeout, a network failure: the proxy, or the address it sends from), counts against the endpoint; any
    other answer for it; a failure the endpoint has no part in (an SSRF refusal, a cap, a decoding error) for
    neither."""
    if pool is None or endpoint is None:
        return
    attempt = result.attempts[-1]
    if _not_the_endpoints(attempt.error):
        return
    if attempt.block_class == "blocked" or (attempt.status is None and _unanswered(attempt.error)):
        pool.report(endpoint, healthy=False)
    elif attempt.error is None or attempt.status is not None:
        pool.report(endpoint, healthy=True)


def _unanswered(error: str | None) -> bool:
    return error is not None and (error == "timeout" or error.startswith("network_error"))


# The errors our own limits set on an answer the endpoint relayed: a body past the cap, a body that does not decode.
_OWN_FAILURES = frozenset({"body_cap", "decode_error"})


def _not_the_endpoints(error: str | None) -> bool:
    """A failure of our own limits or guard, not of the endpoint: a cap or a decoding error keeps the status of an
    answer the endpoint did relay, which says nothing either way (D-1324)."""
    return error is not None and (error in _OWN_FAILURES or error.startswith(SSRF_REJECTED))
