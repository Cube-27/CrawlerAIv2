"""HTTP fetch with curl_cffi and Chrome TLS impersonation (SPEC-02 §4.7).

Redirects are followed by hand so the SSRF guard checks every hop (§4.5), and each request connects only to the
address the guard checked. Through a proxy pool, which resolves names itself, the guard still checks each hop's host
before it is requested (ARCHITECTURE §7.1). Every failure becomes an `error` outcome with a short reason that never
contains the URL.
"""

import asyncio
import io
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from curl_cffi import CurlECode, CurlOpt
from curl_cffi.curl import CURL_WRITEFUNC_ERROR, CURLINFO_HEADER_OUT
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Response
from curl_cffi.requests.exceptions import RequestException

from crawlerai.acquire.classify import classify
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.redirects import MAX_REDIRECTS
from crawlerai.acquire.redirects import location as redirect_location
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyEndpoint, UnknownProxyPool, pool_endpoint
from crawlerai.storage.capture_bundle import HeaderList

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

    @property
    def exchange(self) -> Exchange:
        return Exchange(self.url, self.status, self.request_headers, self.response_headers)


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
    pools: Mapping[str, ProxyEndpoint] | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every request."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    error: str | None = None
    try:
        proxy = _pool(policy, pools)
        deadline = started + policy.timeout_s
        final = await _follow(url, policy, impersonate, connector or SafeConnector(), proxy, deadline)
        # classify parses HTML synchronously; a thread keeps the event loop free.
        block_class: BlockClass = await asyncio.to_thread(classify, final.status, final.response_headers, final.body)
        last: _Response | None = final
    except _Failed as failed:
        error, block_class, last = failed.error, "error", failed.last
    return fetch_result(
        url=url,
        method="http",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=None if last is None else last.exchange,
        content=Content(body=b"" if last is None else last.body),
        block_class=block_class,
        error=error,
    )


def _pool(policy: FetchPolicy, pools: Mapping[str, ProxyEndpoint] | None) -> ProxyEndpoint | None:
    try:
        return pool_endpoint(policy.proxy_pool, pools or {})
    except UnknownProxyPool as e:
        raise _Failed(str(e), None) from e


async def _follow(
    url: str,
    policy: FetchPolicy,
    impersonate: BrowserTypeLiteral,
    connector: SafeConnector,
    proxy: ProxyEndpoint | None,
    deadline: float,
) -> _Response:
    target = await _checked(connector.check(url), deadline, None)
    # One session per fetch keeps cookies set by one hop for the next, and none across fetches. `trust_env=False`
    # with an explicit proxy option (below) ignores proxy environment variables: proxies come only from the pools.
    async with AsyncSession(impersonate=impersonate, trust_env=False) as session:
        response = await _get(session, target, policy, proxy, deadline)
        for hop in range(MAX_REDIRECTS + 1):
            location = redirect_location(response.status, response.response_headers)
            if location is None:
                break
            if hop == MAX_REDIRECTS:
                raise _Failed("too_many_redirects", response)
            target = await _checked(connector.redirect(target, location), deadline, response)
            response = await _get(session, target, policy, proxy, deadline)
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


async def _get(
    session: AsyncSession[Response], target: Target, policy: FetchPolicy, proxy: ProxyEndpoint | None, deadline: float
) -> _Response:
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

    options: dict[CurlOpt, object] = {
        **(_pinned(target) if proxy is None else _through(proxy)),
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


def _pinned(target: Target) -> dict[CurlOpt, object]:
    ip = f"[{target.ip}]" if target.ip.version == 6 else str(target.ip)
    return {
        # Every connection of this request goes to the checked address, whatever host name curl derives from the
        # URL (IDNA, case, percent-encoding): CURLOPT_RESOLVE's `*` host matches every name on the port.
        CurlOpt.RESOLVE: [f"*:{target.port}:{ip}"],
        CurlOpt.PROXY: "",  # an empty proxy disables proxies, including the environment's (CURLOPT_PROXY)
    }


def _through(proxy: ProxyEndpoint) -> dict[CurlOpt, object]:
    # No CURLOPT_RESOLVE: its `*` would also redirect the connection to the proxy. The proxy resolves the page's host
    # itself (ARCHITECTURE §7.1); the guard checked that host before this request.
    host = f"[{proxy.host}]" if ":" in proxy.host else proxy.host
    options: dict[CurlOpt, object] = {
        CurlOpt.PROXY: f"http://{host}:{proxy.port}",
        # A CONNECT tunnel for http pages too (RFC 9110 §9.3.6): the proxy relays bytes and never rewrites a request.
        CurlOpt.HTTPPROXYTUNNEL: 1,
    }
    if proxy.username is not None:
        # Set apart from the proxy URL, so the credentials need no percent-encoding (CURLOPT_PROXYUSERNAME).
        options[CurlOpt.PROXYUSERNAME] = proxy.username
        options[CurlOpt.PROXYPASSWORD] = proxy.password or ""
    return options


def _response(target: Target, response: Response, sent: list[bytes], body: bytes) -> _Response:
    received = tuple((name, value or "") for name, value in response.headers.multi_items())
    return _Response(
        url=target.url,
        status=response.status_code,
        request_headers=recorded(_parse_request_headers(sent[-1] if sent else b"")),
        response_headers=recorded(received),
        body=body,
    )


def _parse_request_headers(block: bytes) -> HeaderList:
    # curl reports the header block it sent in HTTP/1.1 form for every protocol version: a request line, then
    # `name: value` lines (RFC 9112 §3, §5).
    lines = block.decode("latin-1").split("\r\n")[1:]
    return tuple((name, value.strip()) for name, _, value in (line.partition(":") for line in lines if ":" in line))
