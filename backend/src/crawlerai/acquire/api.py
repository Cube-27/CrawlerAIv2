"""JSON over HTTP with httpx, for adapters and API recipes (SPEC-02 §4.1, ARCHITECTURE §7.1 "Adapter / API" rung).

The same guarantees as the HTTP fetch (§4.5, §4.7): redirects are followed by hand through the SSRF guard, each
request connects only to the address the guard checked, bodies are capped, and every failure becomes an `error`
outcome with a short reason that never contains the URL. The capture is recorded under the page the JSON stands for.

Through a proxy pool, every request goes through a CONNECT tunnel (`acquire.tunnel`), as in the other rungs: the guard
still checks each hop's host, and the proxy resolves it, so the request names the host instead of the checked address.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Literal

import httpx

from crawlerai.acquire.classify import classify
from crawlerai.acquire.cookies import FetchCookies
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.redirects import MAX_REDIRECTS
from crawlerai.acquire.redirects import location as redirect_location
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected, Target
from crawlerai.acquire.tunnel import tunnelled_transport
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyEndpoint, UnknownProxyPool, pool_endpoint
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["JsonFetcher", "JsonRequest", "fetch_json"]

# RFC 8259 §11: the JSON media type.
ACCEPT = "application/json"
# httpx's own jar, which refuses every cookie: it would match them against the request URL, which holds the checked
# address, so a cookie would follow the address to every host behind it. It never stores one, so one serves all.
_NO_COOKIES = CookieJar(DefaultCookiePolicy(allowed_domains=[]))


@dataclass(frozen=True)
class JsonRequest:
    url: str  # the endpoint
    page_url: str  # the page the JSON stands for: the capture's `url`; the endpoint is its `final_url`
    method: Literal["GET", "POST"] = "GET"
    # Sent in order after `Accept: application/json`, replacing a field of the same name; never Host or Cookie.
    headers: HeaderList = ()
    body: str | None = None  # UTF-8 text, a POST's only


JsonFetcher = Callable[[JsonRequest, FetchPolicy], Awaitable[FetchResult]]


class _Failed(Exception):
    def __init__(self, error: str, last: Exchange | None) -> None:
        super().__init__(error)
        self.error = error
        self.last = last


async def fetch_json(
    request: JsonRequest,
    policy: FetchPolicy,
    *,
    engine_version: str,
    connector: SafeConnector | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    pools: Mapping[str, ProxyEndpoint] | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every request. `transport`
    replaces httpx's network transport (tests)."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    error: str | None = None
    last: Exchange | None = None
    body = b""
    try:
        proxy = pool_endpoint(policy.proxy_pool, pools)
        if proxy is not None and transport is None:
            transport = tunnelled_transport(proxy)
        async with asyncio.timeout(policy.timeout_s):
            last, body = await _follow(request, policy, connector or SafeConnector(), transport, pinned=proxy is None)
        block_class, error = await asyncio.to_thread(_outcome, last.status, body)
    except _Failed as failed:
        error, block_class, last = failed.error, "error", failed.last
    except UnknownProxyPool as unknown:
        error, block_class = str(unknown), "error"
    except TimeoutError:
        error, block_class = "timeout", "error"
    return fetch_result(
        url=request.page_url,
        method="api",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=last,
        content=Content(body=body),
        block_class=block_class,
        error=error,
    )


def _outcome(status: int, body: bytes) -> tuple[BlockClass, str | None]:
    if 200 <= status < 300:
        # RFC 8259 §8.1: JSON text exchanged between systems is UTF-8; `json.loads` also detects UTF-16/32 from bytes.
        try:
            json.loads(body)
        except ValueError:
            return "error", "decode_error"
        return "ok", None
    # The status rules of SPEC-02 §4.3; the body is not HTML, so it is never a shell.
    block_class = classify(status, (), b"")
    return ("error", "unexpected_status") if block_class == "ok" else (block_class, None)


async def _follow(
    request: JsonRequest,
    policy: FetchPolicy,
    connector: SafeConnector,
    transport: httpx.AsyncBaseTransport | None,
    *,
    pinned: bool,
) -> tuple[Exchange, bytes]:
    """The last exchange and its body, every hop sent to its checked address when `pinned`, else to its host's name
    (through a proxy, which resolves it)."""
    target = await _checked(connector.check(request.url), None)
    # Cookies live for this fetch only (INV-29), matched on each hop's host name, not by httpx's jar (`_NO_COOKIES`).
    cookies = await FetchCookies.new()
    # `trust_env=False` ignores proxy environment variables: proxies come only from the pools.
    async with httpx.AsyncClient(
        transport=transport, trust_env=False, timeout=policy.timeout_s, cookies=_NO_COOKIES
    ) as client:
        hops = 0
        while True:
            exchange, response = await _send(client, target, cookies, request, pinned=pinned)
            try:
                location = redirect_location(exchange.status, exchange.response_headers)
                if location is None:
                    return exchange, await _read(response, policy, exchange)
            finally:
                await response.aclose()  # a redirect's body is never read
            if hops == MAX_REDIRECTS:
                raise _Failed("too_many_redirects", exchange)
            hops += 1
            target = await _checked(connector.redirect(target, location), exchange)
            request = _redirected(request, exchange.status)


def _redirected(request: JsonRequest, status: int) -> JsonRequest:
    """WHATWG Fetch §4.4 (HTTP-redirect fetch) step 12: a 303, or a 301 or 302 after a POST, goes on as a GET without
    a body; 307 and 308 repeat the request."""
    if status == 303 or (status in (301, 302) and request.method == "POST"):
        return replace(request, method="GET", body=None)
    return request


async def _checked(check: Awaitable[Target], last: Exchange | None) -> Target:
    try:
        return await check
    except SsrfRejected as e:
        raise _Failed(str(e), last) from e


async def _send(
    client: httpx.AsyncClient, target: Target, cookies: FetchCookies, json_request: JsonRequest, *, pinned: bool
) -> tuple[Exchange, httpx.Response]:
    url = httpx.URL(target.url)
    # The request goes to the checked address; the Host header (RFC 9110 §7.2) and the TLS server name (RFC 6066 §3,
    # httpx's `sni_hostname` extension) keep the name, so virtual hosting and certificate checks see the real host.
    headers = httpx.Headers({"Accept": ACCEPT})
    for name, value in json_request.headers:
        if name.lower() != "cookie":  # the fetch sends only its own cookies (INV-29)
            headers[name] = value
    headers["Host"] = url.netloc.decode("ascii")  # replaces a caller's Host: the checked host's name
    if (cookie := cookies.header(target.url)) is not None:
        headers["Cookie"] = cookie
    request = client.build_request(
        json_request.method,
        url.copy_with(host=str(target.ip)) if pinned else url,
        headers=headers,
        content=json_request.body,  # httpx encodes text as UTF-8
        extensions={"sni_hostname": target.host},
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.HTTPError as e:
        raise _Failed(_reason(e), None) from e
    cookies.extract(target.url, response.status_code, tuple(response.headers.multi_items()))
    exchange = Exchange(
        url=target.url,
        status=response.status_code,
        request_headers=recorded(tuple(request.headers.multi_items())),
        response_headers=recorded(tuple(response.headers.multi_items())),
    )
    return exchange, response


async def _read(response: httpx.Response, policy: FetchPolicy, exchange: Exchange) -> bytes:
    chunks: list[bytes] = []
    decoded = 0
    try:
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
            decoded += len(chunk)
            # `num_bytes_downloaded` counts bytes as received, before content decoding; `decoded` counts them after,
            # so a compression bomb stops here with at most one chunk past the cap in memory.
            if response.num_bytes_downloaded > policy.max_body_bytes or decoded > policy.max_decompressed_bytes:
                raise _Failed("body_cap", exchange)
    except httpx.HTTPError as e:
        raise _Failed(_reason(e), exchange) from e
    return b"".join(chunks)


def _reason(error: httpx.HTTPError) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.DecodingError):
        return "decode_error"
    # The exception's message can hold the URL; its class name says what failed.
    return f"network_error: {type(error).__name__}"
