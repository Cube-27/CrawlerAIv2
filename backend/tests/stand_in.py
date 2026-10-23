"""A stand-in network for the JSON rung (`acquire.curl_client.Transport`): each hop, after the SSRF guard, the redirect
rule and the fetch's cookie jar have run, goes to an httpx-style handler instead of the network. The real transport
(pinning, proxies, caps, decoding) is tested against local servers (`unit/test_api_fetch.py`, `test_proxy_pools.py`).
"""

from collections.abc import Callable

import httpx

from crawlerai.acquire.curl_client import Failed, Hop, Transport, Wire
from crawlerai.acquire.impersonate import Impersonation
from crawlerai.acquire.ssrf import Target
from crawlerai.core.settings import IMPERSONATE_DEFAULT

__all__ = ["CONNECT_FAILED", "IMPERSONATE", "STAND_IN_BROWSER", "handler_transport"]

# The default target with its own headers, as when the browser rung's Chrome is not read.
IMPERSONATE = Impersonation(IMPERSONATE_DEFAULT)
# What a process's startup reads in place of the browser rung's Chrome where no browser starts: a user agent naming the
# Chrome of the default target (synthetic).
STAND_IN_BROWSER = (("user-agent", f"Mozilla/5.0 (X11; Linux x86_64) Chrome/{IMPERSONATE_DEFAULT[6:]}.0.0.0"),)
# The reason of a connection the server refused: curl's CURLE_COULDNT_CONNECT, which a handler's `ConnectError` stands
# for.
CONNECT_FAILED = "network_error: curl 7"

Handler = Callable[[httpx.Request], httpx.Response]


def handler_transport(handler: Handler) -> Transport:
    """A transport answering each hop with `handler`'s response to it; the request names the target's host."""

    async def transport(target: Target, hop: Hop) -> Wire:
        headers = [(name, value) for name, value in hop.headers.items() if value is not None]
        request = httpx.Request(hop.method, target.url, headers=headers, content=hop.body)
        try:
            response = handler(request)
        except httpx.ConnectError as e:
            raise Failed(CONNECT_FAILED, None) from e
        return Wire(
            url=target.url,
            status=response.status_code,
            request_headers=tuple(request.headers.multi_items()),
            response_headers=tuple(response.headers.multi_items()),
            body=response.read(),
        )

    return transport
