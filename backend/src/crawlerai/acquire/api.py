"""JSON over HTTP with httpx, for adapters and API recipes (SPEC-02 §4.1, ARCHITECTURE §7.1 "Adapter / API" rung).

The same guarantees as the HTTP fetch (§4.5, §4.7): redirects are followed by hand through the SSRF guard, each
request connects only to the address the guard checked, bodies are capped, and every failure becomes an `error`
outcome with a short reason that never contains the URL. The capture is recorded under the page the JSON stands for.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

from crawlerai.acquire.classify import classify
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.redirects import MAX_REDIRECTS
from crawlerai.acquire.redirects import location as redirect_location
from crawlerai.acquire.ssrf import SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult

__all__ = ["JsonFetcher", "JsonRequest", "fetch_json"]

# RFC 8259 §11: the JSON media type.
_ACCEPT = "application/json"
# httpx's own jar, which refuses every cookie: it would match them against the request URL, which holds the checked
# address, so a cookie would follow the address to every host behind it. It never stores one, so one serves all.
_NO_COOKIES = CookieJar(DefaultCookiePolicy(allowed_domains=[]))


@dataclass(frozen=True)
class JsonRequest:
    url: str  # the endpoint
    page_url: str  # the page the JSON stands for: the capture's `url`; the endpoint is its `final_url`


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
) -> FetchResult:
    """`transport` replaces httpx's network transport (tests)."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    error: str | None = None
    last: Exchange | None = None
    body = b""
    try:
        async with asyncio.timeout(policy.timeout_s):
            last, body = await _follow(request.url, policy, connector or SafeConnector(), transport)
        block_class, error = await asyncio.to_thread(_outcome, last.status, body)
    except _Failed as failed:
        error, block_class, last = failed.error, "error", failed.last
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
    url: str, policy: FetchPolicy, connector: SafeConnector, transport: httpx.AsyncBaseTransport | None
) -> tuple[Exchange, bytes]:
    target = await _checked(connector.check(url), None)
    # Cookies live for this fetch only (INV-29), matched on each hop's host name (RFC 6265 §5.4), not by httpx's jar
    # (`_NO_COOKIES`). Host-only cookies stay on their host (§5.3 step 6).
    cookies = httpx.Cookies(CookieJar(DefaultCookiePolicy(strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain)))
    # `trust_env=False` ignores proxy environment variables: a proxy resolves the host itself, which would bypass the
    # checked address.
    async with httpx.AsyncClient(
        transport=transport, trust_env=False, timeout=policy.timeout_s, cookies=_NO_COOKIES
    ) as client:
        hops = 0
        while True:
            exchange, response = await _send(client, target, cookies)
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


async def _checked(check: Awaitable[Target], last: Exchange | None) -> Target:
    try:
        return await check
    except SsrfRejected as e:
        raise _Failed(str(e), last) from e


async def _send(client: httpx.AsyncClient, target: Target, cookies: httpx.Cookies) -> tuple[Exchange, httpx.Response]:
    url = httpx.URL(target.url)
    named = httpx.Request("GET", url)  # the hop as cookie matching sees it: by host name, not by address
    cookies.set_cookie_header(named)
    # The request goes to the checked address; the Host header (RFC 9110 §7.2) and the TLS server name (RFC 6066 §3,
    # httpx's `sni_hostname` extension) keep the name, so virtual hosting and certificate checks see the real host.
    headers = {"Host": url.netloc.decode("ascii"), "Accept": _ACCEPT}
    if "Cookie" in named.headers:
        headers["Cookie"] = named.headers["Cookie"]
    request = client.build_request(
        "GET", url.copy_with(host=str(target.ip)), headers=headers, extensions={"sni_hostname": target.host}
    )
    try:
        response = await client.send(request, stream=True)
    except httpx.HTTPError as e:
        raise _Failed(_reason(e), None) from e
    cookies.extract_cookies(httpx.Response(response.status_code, headers=response.headers, request=named))
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
