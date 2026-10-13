"""HTTP fetch with curl_cffi and Chrome TLS impersonation (SPEC-02 §4.7).

Redirects are followed by hand so the SSRF guard checks every hop (§4.5), and each request connects only to the
address the guard checked. Every failure becomes an `error` outcome with a short reason that never contains the URL.
"""

import asyncio
import io
import time
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast

from curl_cffi import CurlECode, CurlOpt
from curl_cffi.curl import CURL_WRITEFUNC_ERROR, CURLINFO_HEADER_OUT
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Response
from curl_cffi.requests.exceptions import RequestException

from crawlerai.acquire.classify import classify
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, HeaderList, Headers, sha256_hex

# RFC 9110 §15.4: the redirect status codes that carry a Location to follow (300 and 304 do not redirect by
# themselves, 305 and 306 are deprecated).
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5  # SPEC-02 §4.5
# Credentials are never stored in a capture: cookies (RFC 6265 §4) and the proxy credentials (RFC 9110 §11.7.2).
_UNRECORDED = frozenset({"cookie", "set-cookie", "proxy-authorization"})
_CURL_ERRORS: dict[int, str] = {
    CurlECode.OPERATION_TIMEDOUT: "timeout",
    CurlECode.FILESIZE_EXCEEDED: "body_cap",  # the compressed body passed max_body_bytes
    CurlECode.BAD_CONTENT_ENCODING: "decode_error",
}


@dataclass(frozen=True)
class _Response:
    url: str
    status: int  # 0 when no response status line arrived
    request_headers: HeaderList
    response_headers: HeaderList
    body: bytes


class _Failed(Exception):
    def __init__(self, error: str, last: _Response | None) -> None:
        super().__init__(error)
        self.error = error
        self.last = last


async def fetch_http(
    url: str,
    policy: FetchPolicy,
    *,
    engine_version: str,
    impersonate: BrowserTypeLiteral,
    connector: SafeConnector | None = None,
) -> FetchResult:
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    error: str | None = None
    try:
        final = await _follow(url, policy, impersonate, connector or SafeConnector(), started + policy.timeout_s)
        # classify parses HTML synchronously; a thread keeps the event loop free.
        block_class: BlockClass = await asyncio.to_thread(classify, final.status, final.response_headers, final.body)
    except _Failed as failed:
        error, block_class = failed.error, "error"
        # An error keeps no body: it yields no records (INV-11), and a partial body would mislead a replay.
        last = failed.last or _Response(url=url, status=0, request_headers=(), response_headers=(), body=b"")
        final = replace(last, body=b"")
    duration_ms = round((time.monotonic() - started) * 1000)

    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=final.url,
        fetched_at=fetched_at,
        method="http",
        status_code=final.status,
        block_class=block_class,
        headers=Headers(request=final.request_headers, response=final.response_headers),
        timings_ms={"total": duration_ms},
        html_sha256=sha256_hex(final.body),
        network_bodies=(),
        fetch_policy=policy.model_dump(mode="json"),
        engine_version=engine_version,
    )
    attempt = AttemptRecord(
        method="http", status=final.status or None, block_class=block_class, duration_ms=duration_ms, error=error
    )
    return FetchResult(
        bundle=CaptureBundle(manifest=manifest, body=final.body, network=()),
        duration_ms=duration_ms,
        attempts=(attempt,),
    )


async def _follow(
    url: str, policy: FetchPolicy, impersonate: BrowserTypeLiteral, connector: SafeConnector, deadline: float
) -> _Response:
    target = await _checked(connector.check(url), deadline, None)
    # One session per fetch keeps cookies set by one hop for the next, and none across fetches. `trust_env=False`
    # with an empty proxy (below) ignores proxy environment variables: a proxy resolves the host itself, which would
    # bypass the checked address.
    async with AsyncSession(impersonate=impersonate, trust_env=False) as session:
        response = await _get(session, target, policy, deadline)
        for hop in range(_MAX_REDIRECTS + 1):
            location = _location(response)
            if location is None:
                break
            if hop == _MAX_REDIRECTS:
                raise _Failed("too_many_redirects", response)
            target = await _checked(connector.redirect(target, location), deadline, response)
            response = await _get(session, target, policy, deadline)
    return response


async def _checked(check: Awaitable[Target], deadline: float, last: _Response | None) -> Target:
    """Run one guard check within the fetch's time budget: name resolution can take as long as the request."""
    try:
        async with asyncio.timeout(deadline - time.monotonic()):
            return await check
    except SsrfRejected as e:
        raise _Failed(str(e), last) from e
    except TimeoutError as e:
        raise _Failed("timeout", last) from e


async def _get(session: AsyncSession[Response], target: Target, policy: FetchPolicy, deadline: float) -> _Response:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _Failed("timeout", None)

    body = io.BytesIO()
    received = 0

    def on_body(chunk: bytes) -> int:
        # curl hands over the body after content decoding, so this counts decompressed bytes: a compression bomb
        # stops here, holding at most the cap in memory.
        nonlocal received
        received += len(chunk)
        if received > policy.max_decompressed_bytes:
            return CURL_WRITEFUNC_ERROR
        return body.write(chunk)

    sent: list[bytes] = []

    def on_debug(kind: int, data: bytes) -> None:
        if kind == CURLINFO_HEADER_OUT:
            sent.append(data)

    ip = f"[{target.ip}]" if target.ip.version == 6 else str(target.ip)
    options: dict[CurlOpt, object] = {
        # Every connection of this request goes to the checked address, whatever host name curl derives from the
        # URL (IDNA, case, percent-encoding): CURLOPT_RESOLVE's `*` host matches every name on the port.
        CurlOpt.RESOLVE: [f"*:{target.port}:{ip}"],
        CurlOpt.PROXY: "",  # an empty proxy disables proxies, including the environment's (CURLOPT_PROXY)
        # curl speaks only the schemes the guard admits, whatever URL reaches it (CURLOPT_PROTOCOLS_STR).
        CurlOpt.PROTOCOLS_STR: "http,https",
        CurlOpt.MAXFILESIZE_LARGE: policy.max_body_bytes,  # counts body bytes as received, before decoding
        # The debug callback is the only place curl reports the request headers it sent (impersonation sets them in
        # C). It also sees every other debug event, a cost accepted for recording what was sent.
        CurlOpt.VERBOSE: 1,
        CurlOpt.DEBUGFUNCTION: on_debug,
    }
    # curl_cffi types option values as str, but passes each to curl_easy_setopt with the option's own type.
    session.curl_options = cast(dict[CurlOpt, str], options)
    try:
        response = await session.get(target.url, allow_redirects=False, timeout=remaining, content_callback=on_body)
    except RequestException as e:
        capped = received > policy.max_decompressed_bytes
        error = "body_cap" if capped else _CURL_ERRORS.get(e.code, f"network_error: curl {int(e.code)}")
        # The exception carries what arrived before the failure: the status and headers, if any.
        partial: Response | None = e.response
        raise _Failed(error, None if partial is None else _response(target, partial, sent, b"")) from e
    return _response(target, response, sent, body.getvalue())


def _response(target: Target, response: Response, sent: list[bytes], body: bytes) -> _Response:
    received = tuple((name, value or "") for name, value in response.headers.multi_items())
    return _Response(
        url=target.url,
        status=response.status_code,
        request_headers=_recorded(_parse_request_headers(sent[-1] if sent else b"")),
        response_headers=_recorded(received),
        body=body,
    )


def _parse_request_headers(block: bytes) -> HeaderList:
    # curl reports the header block it sent in HTTP/1.1 form for every protocol version: a request line, then
    # `name: value` lines (RFC 9112 §3, §5).
    lines = block.decode("latin-1").split("\r\n")[1:]
    return tuple((name, value.strip()) for name, _, value in (line.partition(":") for line in lines if ":" in line))


def _recorded(headers: HeaderList) -> HeaderList:
    return tuple((name, value) for name, value in headers if name.lower() not in _UNRECORDED)


def _location(response: _Response) -> str | None:
    if response.status not in _REDIRECTS:
        return None
    # RFC 9110 §10.2.2: one Location value; when repeated, the last one received is used.
    values = [value for name, value in response.response_headers if name.lower() == "location"]
    return values[-1] if values else None
