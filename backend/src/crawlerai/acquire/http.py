"""HTTP fetch with curl_cffi and Chrome TLS impersonation (SPEC-02 §4.7).

Redirects are followed by hand so the SSRF guard checks every hop (§4.5), and each request connects only to the
address the guard checked. Through a proxy pool, which resolves names itself, the guard still checks each hop's host
before it is requested (ARCHITECTURE §7.1). Every failure becomes an `error` outcome with a short reason that never
contains the URL. Given the validators a page last answered with, its request is conditional (SPEC-11 §4.2): an
unchanged page answers 304 with no body.
"""

import asyncio
import io
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from curl_cffi import Curl, CurlECode, CurlOpt
from curl_cffi.curl import CURL_WRITEFUNC_ERROR, CURLINFO_HEADER_OUT
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral, Response
from curl_cffi.requests.exceptions import RequestException

from crawlerai.acquire.classify import classify
from crawlerai.acquire.cookies import FetchCookies
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.redirects import MAX_REDIRECTS
from crawlerai.acquire.redirects import location as redirect_location
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected, Target, bracketed
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult, Validators
from crawlerai.core.proxy import ProxyEndpoint, UnknownProxyPool, pool_endpoint
from crawlerai.storage.capture_bundle import HeaderList

_CURLPROXY_HTTP = 0  # curl's `curl_proxytype` for an HTTP proxy (CURLOPT_PROXYTYPE)
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


class _Session(AsyncSession[Response]):
    """curl_cffi's session, releasing a request's handle from the event loop's multi handle before its callbacks.

    curl_cffi 0.16 frees a handle's callback data first and removes the handle from the multi handle second. For a
    request still in flight (cancelled by an outer time cap), the removal closes its connection, and curl reports
    that to the debug callback (`DEBUGFUNCTION`, which records the headers sent), whose data is gone by then: the
    process dies in native code. Removed first, the handle's events reach live callbacks; curl_cffi's own removal
    then finds it removed, which `curl_multi_remove_handle` answers with success.
    """

    def release_curl(self, curl: Curl) -> None:
        if not self._closed:
            self.acurl.remove_handle(curl)
        super().release_curl(curl)


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
    validators: Validators | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every request."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    error: str | None = None
    try:
        proxy = pool_endpoint(policy.proxy_pool, pools)
        deadline = started + policy.timeout_s
        headers = _conditional(validators)
        final = await _follow(url, policy, impersonate, connector or SafeConnector(), proxy, deadline, headers)
        # classify parses HTML synchronously; a thread keeps the event loop free.
        block_class: BlockClass = await asyncio.to_thread(
            classify, final.status, final.response_headers, final.body, policy.page_kind
        )
        last: _Response | None = final
    except _Failed as failed:
        error, block_class, last = failed.error, "error", failed.last
    except UnknownProxyPool as unknown:
        error, block_class, last = str(unknown), "error", None
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


async def _follow(
    url: str,
    policy: FetchPolicy,
    impersonate: BrowserTypeLiteral,
    connector: SafeConnector,
    proxy: ProxyEndpoint | None,
    deadline: float,
    headers: dict[str, str],
) -> _Response:
    target = await _checked(connector.check(url), deadline, None)
    # Cookies set by one hop go with the next, and none across fetches (INV-29). They are kept by `FetchCookies`, not
    # libcurl's engine, which this build runs without the public-suffix list (RFC 6265 §5.3 step 5): the session
    # discards what curl parsed, and each request clears curl's list before sending only the cookies passed in.
    cookies = await FetchCookies.new()
    # `trust_env=False` stops curl_cffi reading the proxy environment variables; libcurl reads them itself, so each
    # request also sets CURLOPT_PROXY, and a pool request CURLOPT_NOPROXY (below): proxies come only from the pools.
    async with _Session(impersonate=impersonate, trust_env=False, discard_cookies=True) as session:
        response = await _get(session, target, policy, proxy, deadline, headers, cookies)
        for hop in range(MAX_REDIRECTS + 1):
            location = redirect_location(response.status, response.response_headers)
            if location is None:
                break
            if hop == MAX_REDIRECTS:
                raise _Failed("too_many_redirects", response)
            target = await _checked(connector.redirect(target, location), deadline, response)
            # The validators describe the URL asked for: sent past a redirect, another resource's 304 would stand
            # for it.
            response = await _get(session, target, policy, proxy, deadline, {}, cookies)
    return response


def _conditional(validators: Validators | None) -> dict[str, str]:
    """The request headers that make a GET conditional: If-None-Match carries the entity tag (RFC 9110 §13.1.2),
    If-Modified-Since the Last-Modified date (§13.1.3). A server that has both decides on the entity tag."""
    if validators is None:
        return {}
    headers = {"If-None-Match": validators.etag, "If-Modified-Since": validators.last_modified}
    return {name: value for name, value in headers.items() if value is not None}


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
    session: AsyncSession[Response],
    target: Target,
    policy: FetchPolicy,
    proxy: ProxyEndpoint | None,
    deadline: float,
    headers: dict[str, str],
    cookies: FetchCookies,
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
    if (cookie := cookies.header(target.url)) is not None:
        headers = {**headers, "Cookie": cookie}
    try:
        response = await session.get(
            target.url, headers=headers, allow_redirects=False, timeout=remaining, content_callback=on_body
        )
    except RequestException as e:
        capped = received > policy.max_decompressed_bytes
        error = "body_cap" if capped else _CURL_ERRORS.get(e.code, f"network_error: curl {int(e.code)}")
        # The exception carries what arrived before the failure: the status and headers, if any.
        partial: Response | None = e.response
        raise _Failed(error, None if partial is None else _response(target, partial, sent, b"")) from e
    cookies.extract(target.url, response.status_code, _received(response))
    return _response(target, response, sent, body.getvalue())


def _pinned(target: Target) -> dict[CurlOpt, object]:
    ip = bracketed(str(target.ip))
    return {
        # Every connection of this request goes to the checked address, whatever host name curl derives from the
        # URL (IDNA, case, percent-encoding): CURLOPT_RESOLVE's `*` host matches every name on the port.
        CurlOpt.RESOLVE: [f"*:{target.port}:{ip}"],
        CurlOpt.PROXY: "",  # an empty proxy disables proxies, including the environment's (CURLOPT_PROXY)
    }


def _through(proxy: ProxyEndpoint) -> dict[CurlOpt, object]:
    # No CURLOPT_RESOLVE: its `*` would also redirect the connection to the proxy. The proxy resolves the page's host
    # itself (ARCHITECTURE §7.1); the guard checked that host before this request.
    options: dict[CurlOpt, object] = {
        # The proxy's host alone, with its type and port set apart: curl's CURLPROXY_HTTP (0) speaks plain HTTP to
        # the proxy, the only kind a pool is (`crawlerai.core.proxy`); pages inside the tunnel keep their own TLS.
        CurlOpt.PROXY: bracketed(proxy.host),
        CurlOpt.PROXYPORT: proxy.port,
        CurlOpt.PROXYTYPE: _CURLPROXY_HTTP,
        # A CONNECT tunnel for http pages too (RFC 9110 §9.3.6): the proxy relays bytes and never rewrites a request.
        CurlOpt.HTTPPROXYTUNNEL: 1,
        # An empty list overrides the environment's `no_proxy`, which would otherwise send matching hosts direct,
        # resolved by curl rather than the guard (CURLOPT_NOPROXY).
        CurlOpt.NOPROXY: "",
    }
    if proxy.username is not None:
        # Set apart from the proxy URL, so the credentials need no percent-encoding (CURLOPT_PROXYUSERNAME).
        options[CurlOpt.PROXYUSERNAME] = proxy.username
        options[CurlOpt.PROXYPASSWORD] = proxy.password or ""
    return options


def _received(response: Response) -> HeaderList:
    return tuple((name, value or "") for name, value in response.headers.multi_items())


def _response(target: Target, response: Response, sent: list[bytes], body: bytes) -> _Response:
    received = _received(response)
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


class RequestFailed(Exception):
    """A request got no response: the reason never contains the URL (SPEC-02 §4.11)."""


async def post(url: str, body: bytes, headers: Mapping[str, str], *, connector: SafeConnector, timeout_s: float) -> int:
    """POST `body` to `url` and return the response status. The guard checks `url` and the request connects only to
    the checked address; a redirect is returned as its status, never followed, so the body goes to no other target.
    The response body is discarded as it arrives. Raises `SsrfRejected`, or `RequestFailed`."""
    target = await connector.check(url)
    async with AsyncSession(trust_env=False) as session:
        options: dict[CurlOpt, object] = {**_pinned(target), CurlOpt.PROTOCOLS_STR: "http,https"}
        session.curl_options = cast(dict[CurlOpt, str], options)
        try:
            response = await session.post(
                target.url,
                data=body,
                headers=dict(headers),
                allow_redirects=False,
                timeout=timeout_s,
                content_callback=len,
            )
        except RequestException as e:
            raise RequestFailed(_CURL_ERRORS.get(e.code, f"network_error: curl {int(e.code)}")) from e
    status: int = response.status_code
    return status
