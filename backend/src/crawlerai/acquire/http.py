"""HTTP fetch with curl_cffi and Chrome TLS impersonation (acquisition spec), over the shared client (`curl_client`).

Redirects are followed by hand so the SSRF guard checks every hop (§4.5), and each request connects only to the
address the guard checked. Through a proxy pool, which resolves names itself, the guard still checks each hop's host
before it is requested. Every failure becomes an `error` outcome with a short reason that never
contains the URL. The request is a navigation, sent with the impersonation's own headers, or
with a site session's cookies and identity where the site has one (`acquire.session`, INV-29's exception).
"""

import asyncio
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession, BrowserTypeLiteral
from curl_cffi.requests.exceptions import RequestException

from crawlerai.acquire.challenge import CHALLENGED, block_class_of, challenge_label, count
from crawlerai.acquire.classify import Redirect
from crawlerai.acquire.curl_client import Hop, pinned, reason, send
from crawlerai.acquire.outcome import Content, fetch_result, report_proxy
from crawlerai.acquire.session import SiteSessions
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyPool
from crawlerai.storage.capture_bundle import decode_html


async def fetch_http(
    url: str,
    policy: FetchPolicy,
    *,
    engine_version: str,
    impersonate: BrowserTypeLiteral,
    connector: SafeConnector | None = None,
    pools: Mapping[str, ProxyPool] | None = None,
    sessions: SiteSessions | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every request. `sessions`
    are this process's site sessions: the site's, if any, goes with the fetch, and is dropped when it is `blocked`; a
    fetch with the caller's own context takes none (D-1432)."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    if policy.context is not None:
        sessions = None
    session = None if sessions is None else await sessions.take(url, url, policy.proxy_pool)
    sent = await send(
        url,
        Hop("GET", {}),
        policy,
        impersonate=impersonate,
        connector=connector or SafeConnector(),
        pools=pools,
        redirected=_follow,
        session=session,
    )
    last, challenge = sent.last, None
    block_class: BlockClass = "error"
    if sent.error is None and last is not None:
        # The body is decoded once (`decode_html`), and every rule reads that text. Classifying parses HTML
        # synchronously; a thread keeps the event loop free.
        text = decode_html(last.body, last.response_headers, "http")
        redirect = Redirect(url, last.exchange.url, policy.page_kind)
        block_class = await asyncio.to_thread(
            block_class_of, last.status, last.response_headers, text, policy.page_kind, redirect
        )
        if block_class in CHALLENGED:
            # The document's links resolve against the URL that served it (RFC 3986 §5), the last hop's.
            served = last.exchange.url
            challenge = await asyncio.to_thread(challenge_label, last.status, last.response_headers, text, served)
    count(challenge, "http")
    result = fetch_result(
        url=url,
        method="http",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=None if last is None else last.exchange,
        content=Content(body=b"" if last is None else last.body),
        block_class=block_class,
        error=sent.error,
        challenge=challenge,
        transferred=sent.transferred,
    )
    report_proxy(sent.pool, sent.proxy, result)
    if sessions is not None:
        await sessions.settle(sent.session, result)
    return result


def _follow(_hop: Hop, _status: int, _target: Target) -> Hop:
    """A navigation's redirect is followed with a plain GET (RFC 9110 §15.4)."""
    return Hop("GET", {})


class RequestFailed(Exception):
    """A request got no response: the reason never contains the URL (acquisition spec)."""


async def post(url: str, body: bytes, headers: Mapping[str, str], *, connector: SafeConnector, timeout_s: float) -> int:
    """POST `body` to `url` and return the response status. The guard checks `url` and the request connects only to
    the checked address; a redirect is returned as its status, never followed, so the body goes to no other target.
    The response body is discarded as it arrives. Raises `SsrfRejected`, or `RequestFailed`."""
    target = await connector.check(url)
    async with AsyncSession(trust_env=False) as session:
        options: dict[CurlOpt, object] = {**pinned(target), CurlOpt.PROTOCOLS_STR: "http,https"}
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
            raise RequestFailed(reason(e)) from e
    status: int = response.status_code
    return status
