"""JSON over HTTP, for adapters and API recipes (the acquisition rung), over the HTTP
rung's client (`curl_client`): the same Chrome impersonation, SSRF guard, caps, cookie jar, proxy pools and
reasons. The capture is recorded under the page the JSON stands for.

The request is what that page's own script would send with `fetch()`: the impersonation's headers, less the
two only a navigation sends (Upgrade Insecure Requests §3.2; Fetch Metadata §2.4 `Sec-Fetch-User`), with the Fetch
Metadata of a CORS request for no destination (W3C Fetch Metadata Request Headers §2: `Sec-Fetch-Mode: cors`,
`Sec-Fetch-Dest: empty`, `Sec-Fetch-Site` from the page to the endpoint), the `Referer` the default referrer policy
gives (W3C Referrer Policy §3, `strict-origin-when-cross-origin`) and an `Origin` where Fetch §3.1 sends one (a CORS
request to another origin, or any request that is not a GET). A recipe's own headers come last and win. The page's
site session, if any (`acquire.session`), lends its cookies to a request in the
site's registrable domain.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal
from urllib.parse import urlsplit, urlunsplit

from crawlerai.acquire.challenge import CHALLENGED, challenge_label, count
from crawlerai.acquire.classify import classify
from crawlerai.acquire.curl_client import Hop, Transport, Wire, send
from crawlerai.acquire.impersonate import Impersonation
from crawlerai.acquire.locality import language_headers
from crawlerai.acquire.outcome import Content, fetch_result, report_proxy
from crawlerai.acquire.public_suffix import default_suffixes
from crawlerai.acquire.session import SiteSessions
from crawlerai.acquire.ssrf import SafeConnector, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core import json_text
from crawlerai.core.proxy import ProxyPool
from crawlerai.storage.capture_bundle import HeaderList, decode_html

__all__ = ["ACCEPT", "JsonFetcher", "JsonRequest", "fetch_json"]

# RFC 8259 §11: the JSON media type.
ACCEPT = "application/json"
# Fetch §5.2 "extract a body": a string body's type when the request names none.
_TEXT_BODY = "text/plain;charset=UTF-8"
_CONTENT_TYPE = "content-type"
# Fetch §4.4 step 12 (HTTP-redirect fetch): the request-body-header names, dropped with the body.
_BODY_HEADERS = frozenset({"content-encoding", "content-language", "content-location", _CONTENT_TYPE})
SiteRelation = Literal["same-origin", "same-site", "cross-site"]
# Fetch Metadata §2.1: across a redirect chain the value is the least related hop's.
_RELATION_ORDER: Final[tuple[SiteRelation, ...]] = ("same-origin", "same-site", "cross-site")
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}  # RFC 9110 §4.2
# The order in which Chromium sends a script's `fetch()` headers, as the browser rung's Chromium sends them to a
# header echo service; the impersonation profile describes a navigation's. A header absent from a request is skipped.
FETCH_HEADER_ORDER: Final = (
    "host",
    "content-length",
    "sec-ch-ua-platform",
    "user-agent",
    "sec-ch-ua",
    "content-type",
    "sec-ch-ua-mobile",
    "accept",
    "origin",
    "sec-fetch-site",
    "sec-fetch-mode",
    "sec-fetch-dest",
    "referer",
    "accept-encoding",
    "accept-language",
    "cookie",
    "priority",
)


@dataclass(frozen=True)
class JsonRequest:
    url: str  # the endpoint
    page_url: str  # the page the JSON stands for: the capture's `url`; the endpoint is its `final_url`
    method: Literal["GET", "POST"] = "GET"
    # Sent after the fetch's own headers, replacing a field of the same name; never Host or Cookie.
    headers: HeaderList = ()
    body: str | None = None  # UTF-8 text, a POST's only
    # The endpoint answers XML or HTML, not JSON (a feed, a page embedding data): a 2xx answer is `ok` whatever its
    # body, and the adapter that asked reads it into the JSON its shapes describe (`adapters.answer`).
    raw: bool = False


JsonFetcher = Callable[[JsonRequest, FetchPolicy], Awaitable[FetchResult]]


async def fetch_json(
    request: JsonRequest,
    policy: FetchPolicy,
    *,
    engine_version: str,
    impersonate: Impersonation,
    connector: SafeConnector | None = None,
    pools: Mapping[str, ProxyPool] | None = None,
    transport: Transport | None = None,
    sessions: SiteSessions | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every request. `transport`
    replaces the network (tests). `sessions` are this process's site sessions: the page's site's goes with a request
    in its registrable domain, and is dropped when it is `blocked`."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    # A fetch with the caller's own context takes no site session.
    if policy.context is not None:
        sessions = None
    session = None if sessions is None else sessions.take(request.page_url, request.url, policy.proxy_pool)
    sent = await send(
        request.url,
        _first_hop(request, policy.locale_hint),
        policy,
        impersonate=impersonate,
        connector=connector or SafeConnector(),
        pools=pools,
        redirected=_Redirect(request.page_url),
        transport=transport,
        session=session,
        page_url=request.page_url,
    )
    last, error, challenge = sent.last, sent.error, None
    block_class: BlockClass = "error"
    body = b""
    if error is None and last is not None:
        block_class, error = await asyncio.to_thread(_outcome, last.status, last.body, request.raw)
        body = last.body
        if block_class in CHALLENGED:
            challenge = await asyncio.to_thread(_label, last, request.url)
    count(challenge, "api")
    result = fetch_result(
        url=request.page_url,
        method="api",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=None if last is None else last.exchange,
        content=Content(body=body),
        block_class=block_class,
        error=error,
        challenge=challenge,
        transferred=sent.transferred,
    )
    report_proxy(sent.pool, sent.proxy, result)
    if sessions is not None:
        sessions.settle(sent.session, result)
    return result


def _label(last: Wire, url: str) -> str | None:
    # A refused API answer is labelled by its markup, decoded as a page's is (`decode_html`).
    return challenge_label(
        last.status, last.response_headers, decode_html(last.body, last.response_headers, "api"), url
    )


def _outcome(status: int, body: bytes, raw: bool) -> tuple[BlockClass, str | None]:
    if 200 <= status < 300:
        if raw:
            return "ok", None
        try:
            json_text.parse(body)
        except ValueError:
            return "error", "decode_error"
        return "ok", None
    # The status rules apply; the body is not HTML, so it is never a shell.
    block_class = classify(status, (), "")
    return ("error", "unexpected_status") if block_class == "ok" else (block_class, None)


def _first_hop(request: JsonRequest, locale: str | None) -> Hop:
    # The page's language goes with its script's calls, as the browser rung's context sends it (`acquire.locality`).
    headers: dict[str, str | None] = {**language_headers(locale)}
    headers.update(_fetch_headers(request.page_url, request.url, request.method, "same-origin"))
    for name, value in request.headers:
        _replace(headers, name, value)
    if request.body is not None and not any(name.lower() == _CONTENT_TYPE for name in headers):
        headers["Content-Type"] = _TEXT_BODY
    body = None if request.body is None else request.body.encode()
    return Hop(request.method, headers, body, FETCH_HEADER_ORDER)


def _replace(headers: dict[str, str | None], name: str, value: str | None) -> None:
    """Set `name` in `headers`, replacing a field of the same name in any case (RFC 9110 §5.1)."""
    for existing in [key for key in headers if key.lower() == name.lower()]:
        del headers[existing]
    headers[name] = value


def _fetch_headers(page_url: str, url: str, method: str, before: SiteRelation) -> dict[str, str | None]:
    """The headers a `fetch()` from `page_url` sends to `url` (module docstring); `before` is the least related hop
    of the redirect chain so far."""
    relation = max(before, site_relation(page_url, url), key=_RELATION_ORDER.index)
    headers: dict[str, str | None] = {
        "Accept": ACCEPT,
        "Sec-Fetch-Site": relation,
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-User": None,
        "Upgrade-Insecure-Requests": None,
        "Referer": referrer(page_url, url),
        # RFC 9218 §4: urgency 1, incremental, as Chromium sends for a script's fetch (a navigation is urgency 0).
        "Priority": "u=1, i",
    }
    if method != "GET" or _origin(page_url) != _origin(url):
        headers["Origin"] = _serialized_origin(page_url)
    return headers


@dataclass(frozen=True)
class _Redirect:
    """The hop after a redirect: WHATWG Fetch §4.4 (HTTP-redirect fetch) step 12 makes a 303, or a 301 or 302 after a
    POST, a GET without its body and body headers; 307 and 308 repeat the request. The Fetch Metadata, `Referer` and
    `Origin` are those of the new target."""

    page_url: str

    def __call__(self, hop: Hop, status: int, target: Target) -> Hop:
        method, body = hop.method, hop.body
        headers = dict(hop.headers)
        if status == 303 or (status in (301, 302) and hop.method == "POST"):
            method, body = "GET", None
            headers = {name: value for name, value in headers.items() if name.lower() not in _BODY_HEADERS}
        before = _relation_of(headers.get("Sec-Fetch-Site"))
        for name, value in _fetch_headers(self.page_url, target.url, method, before).items():
            _replace(headers, name, value)
        if method == "GET" and _origin(self.page_url) == _origin(target.url):
            _replace(headers, "Origin", None)
        return Hop(method, headers, body, FETCH_HEADER_ORDER)


def _relation_of(value: str | None) -> SiteRelation:
    return next((relation for relation in _RELATION_ORDER if relation == value), "same-origin")


def _origin(url: str) -> tuple[str, str, int | None]:
    """A URL's origin (RFC 6454 §4): scheme, host and port, the scheme's default port filled in."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or ""), parts.port or _DEFAULT_PORTS.get(scheme)


def _serialized_origin(url: str) -> str:
    """RFC 6454 §6.2: scheme "://" host, and ":" port unless it is the scheme's default."""
    scheme, host, port = _origin(url)
    netloc = f"[{host}]" if ":" in host else host
    return f"{scheme}://{netloc}" if port == _DEFAULT_PORTS.get(scheme) else f"{scheme}://{netloc}:{port}"


def site_relation(page_url: str, url: str) -> SiteRelation:
    """Fetch Metadata §2.1: `same-origin` for equal origins, `same-site` for the same scheme and site (HTML Standard
    §7.1.1 "same site": the registrable domain of the Public Suffix List, or the host itself where it has none),
    else `cross-site`."""
    if _origin(page_url) == _origin(url):
        return "same-origin"
    (scheme_a, host_a, _), (scheme_b, host_b, _) = _origin(page_url), _origin(url)
    suffixes = default_suffixes()
    if scheme_a == scheme_b and suffixes.site(host_a) == suffixes.site(host_b):
        return "same-site"
    return "cross-site"


def referrer(page_url: str, url: str) -> str | None:
    """The `Referer` under `strict-origin-when-cross-origin` (Referrer Policy §3.9, the default since its §8.3):
    the page's URL without fragment or credentials (§8.4 "strip url") to its own origin, only its origin elsewhere,
    and none from an https page to an http URL."""
    page = urlsplit(page_url)
    if page.scheme.lower() == "https" and urlsplit(url).scheme.lower() == "http":
        return None
    if _origin(page_url) == _origin(url):
        netloc = page.netloc.rpartition("@")[2]
        return urlunsplit((page.scheme, netloc, page.path or "/", page.query, ""))
    return _serialized_origin(page_url) + "/"
