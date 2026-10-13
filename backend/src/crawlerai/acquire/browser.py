"""Browser fetch with Patchright headless Chromium (SPEC-02 §4.8, ARCHITECTURE §7.1): one navigation, bounded waits,
and the JSON bodies the page loads captured for API discovery (§7.2 step 1).

One browser per worker process (`open_browser`), one fresh context per fetch. Every connection the context opens goes
through a `SocksGuard`, which applies the SSRF guard to every redirect hop, frame and worker (§4.5). As in
`fetch_http`, every failure becomes an `error` outcome with a short reason that never contains the URL (D-0128).
"""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

from patchright.async_api import Browser, Page, Request, Response, async_playwright
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import JsonValue

from crawlerai.acquire.classify import classify
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import RejectReason, SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.core.ids import uuid7
from crawlerai.storage.capture_bundle import (
    CaptureBundle,
    CaptureManifest,
    HeaderList,
    Headers,
    NetworkBody,
    network_file,
    sha256_hex,
)

__all__ = ["BrowserSession", "fetch_browser", "open_browser"]

# Chromium names its headless build `HeadlessChrome` in the user agent and the client-hint brands; the headed build
# says `Chrome` (§7.1: the user agent drops `HeadlessChrome`).
_HEADLESS_PRODUCT = "HeadlessChrome"
_HEADED_PRODUCT = "Chrome"
# RFC 6761 §6.4: `.invalid` never resolves. The identity probe page is served from inside the browser, not fetched;
# https makes it a secure context, where Chromium exposes its client hints (W3C Secure Contexts, UA-CH §3).
_PROBE_URL = "https://identity.invalid/"
# User-Agent Client Hints (WICG UA-CH §4): the high-entropy values, which with the low-entropy brands, mobile and
# platform make up CDP's `Network.UserAgentMetadata`.
_HIGH_ENTROPY_HINTS = ["architecture", "bitness", "fullVersionList", "model", "platformVersion", "wow64"]
# WebRTC sends UDP outside any proxy; Chromium's policy `disable_non_proxied_udp` keeps it inside the guard.
_LAUNCH_ARGS = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
# SPEC-02 §4.8, D-0010: JSON bodies are captured up to 2 MB each and 50 per page.
_JSON_BODY_MAX_BYTES = 2_000_000
_JSON_BODIES_MAX = 50
# The network-idle wait ends at this share of `browser_timeout_s`; the rest is for reading the DOM and the bodies.
_IDLE_SHARE = 0.9
# Chromium's network error names (net/base/net_error_list.h) carry no URL.
_NET_ERROR = re.compile(r"net::ERR_[A-Z0-9_]+")


@dataclass(frozen=True)
class BrowserSession:
    """A launched browser and the identity every page presents: Chromium's own user agent and client hints, with
    the headless product name replaced so the two agree."""

    browser: Browser
    user_agent: str
    client_hints: dict[str, JsonValue]  # CDP `Network.UserAgentMetadata`


@asynccontextmanager
async def open_browser() -> AsyncIterator[BrowserSession]:
    """The browser runs until the block ends; leaving it ends the browser and driver processes."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        try:
            yield BrowserSession(browser, *await _identity(browser))
        finally:
            await browser.close()


async def _identity(browser: Browser) -> tuple[str, dict[str, JsonValue]]:
    page = await browser.new_page()
    try:
        await page.route(_PROBE_URL, lambda route: route.fulfill(content_type="text/html", body=""))
        await page.goto(_PROBE_URL)
        user_agent = cast(str, await page.evaluate("navigator.userAgent"))
        hints = cast(
            dict[str, JsonValue],
            await page.evaluate("hints => navigator.userAgentData.getHighEntropyValues(hints)", _HIGH_ENTROPY_HINTS),
        )
    finally:
        await page.close()
    for key in ("brands", "fullVersionList"):
        brands = cast(list[dict[str, str]], hints[key])
        hints[key] = cast(JsonValue, [b for b in brands if b["brand"] != _HEADLESS_PRODUCT])
    return user_agent.replace(f"{_HEADLESS_PRODUCT}/", f"{_HEADED_PRODUCT}/"), hints


class _Failed(Exception):
    def __init__(self, error: str, response: "_Navigation | None") -> None:
        super().__init__(error)
        self.error = error
        self.response = response


@dataclass(frozen=True)
class _Navigation:
    url: str
    status: int
    request_headers: HeaderList
    response_headers: HeaderList


@dataclass(frozen=True)
class _Rendered:
    navigation: _Navigation
    body: bytes  # the rendered DOM
    raw_body: bytes | None  # the navigation response body; None when the browser no longer holds it
    network: tuple[tuple[NetworkBody, bytes], ...]


async def fetch_browser(
    url: str,
    policy: FetchPolicy,
    *,
    session: BrowserSession,
    engine_version: str,
    connector: SafeConnector | None = None,
) -> FetchResult:
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    timings: dict[str, int] = {}
    error: str | None = None
    rendered: _Rendered | None = None
    navigation: _Navigation | None = None
    try:
        async with asyncio.timeout(policy.browser_timeout_s):
            rendered = await _render(url, policy, session, connector or SafeConnector(), started, timings)
        navigation = rendered.navigation
        _check_size(rendered, policy)
        # classify parses HTML synchronously; a thread keeps the event loop free.
        headers = navigation.response_headers
        block_class: BlockClass = await asyncio.to_thread(classify, navigation.status, headers, rendered.body)
    except _Failed as failed:
        error, block_class, navigation = failed.error, "error", failed.response or navigation
    except TimeoutError:
        error, block_class = "timeout", "error"
    if error is not None:
        # An error keeps no body: it yields no records (INV-11), and a partial page would mislead a replay.
        rendered = None
    navigation = navigation or _Navigation(url=url, status=0, request_headers=(), response_headers=())
    duration_ms = round((time.monotonic() - started) * 1000)
    body = rendered.body if rendered else b""
    network = rendered.network if rendered else ()

    manifest = CaptureManifest(
        capture_id=uuid7(),
        url=url,
        final_url=navigation.url,
        fetched_at=fetched_at,
        method="browser",
        status_code=navigation.status,
        block_class=block_class,
        headers=Headers(request=navigation.request_headers, response=navigation.response_headers),
        # `context` is the browser context's wall time, which `browser_seconds` usage counts (§4.8).
        timings_ms={"total": duration_ms, **timings},
        html_sha256=sha256_hex(body),
        raw_html_sha256=None if rendered is None or rendered.raw_body is None else sha256_hex(rendered.raw_body),
        network_bodies=tuple(entry for entry, _ in network),
        fetch_policy=policy.model_dump(mode="json"),
        engine_version=engine_version,
    )
    status = navigation.status or None
    attempt = AttemptRecord(
        method="browser", status=status, block_class=block_class, duration_ms=duration_ms, error=error
    )
    return FetchResult(
        bundle=CaptureBundle(
            manifest=manifest,
            body=body,
            network=tuple(data for _, data in network),
            raw_body=rendered.raw_body if rendered else None,
        ),
        duration_ms=duration_ms,
        attempts=(attempt,),
    )


def _check_size(rendered: _Rendered, policy: FetchPolicy) -> None:
    # The browser hands over bodies after content decoding, so the decompressed cap is the one that applies.
    if max(len(rendered.body), len(rendered.raw_body or b"")) > policy.max_decompressed_bytes:
        raise _Failed("body_cap", rendered.navigation)


async def _render(
    url: str,
    policy: FetchPolicy,
    session: BrowserSession,
    connector: SafeConnector,
    started: float,
    timings: dict[str, int],
) -> _Rendered:
    try:
        first = await connector.check(url)  # also refuses `file:`, `data:` and other non-web schemes
    except SsrfRejected as e:
        raise _Failed(str(e), None) from e
    async with SocksGuard(connector, checked=(first,)) as guard:
        context = await session.browser.new_context(proxy={"server": guard.url}, accept_downloads=False)
        opened = time.monotonic()
        try:
            page = await context.new_page()
            cdp = await context.new_cdp_session(page)
            await cdp.send(
                "Network.setUserAgentOverride",
                {"userAgent": session.user_agent, "userAgentMetadata": session.client_hints},
            )
            return await _navigate(page, url, first, policy, guard, started)
        finally:
            await context.close()
            timings["context"] = round((time.monotonic() - opened) * 1000)


async def _navigate(
    page: Page, url: str, first: Target, policy: FetchPolicy, guard: SocksGuard, started: float
) -> _Rendered:
    hops: list[str] = [first.url]  # the main frame's navigation requests, one per redirect hop

    def on_request(request: Request) -> None:
        if request.is_navigation_request() and request.frame == page.main_frame:
            hops.append(request.url)

    json_responses: list[Response] = []

    def on_response(response: Response) -> None:
        # The navigation responses are the page itself, not data it loaded.
        if not response.request.is_navigation_request() and _is_json(response):
            json_responses.append(response)

    page.on("request", on_request)
    if policy.capture_network_json:
        page.on("response", on_response)

    budget_end = started + policy.browser_timeout_s
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=_ms_until(budget_end))
    except PlaywrightError as e:
        raise _Failed(_navigation_error(e, hops[-1], guard.rejections), None) from e
    if response is None:  # only a same-document navigation has none, and a new page has no document yet
        raise _Failed("no_response", None)
    navigation = _Navigation(
        url=response.url,
        status=response.status,
        request_headers=recorded(_header_list(await response.request.headers_array())),
        response_headers=recorded(_header_list(await response.headers_array())),
    )
    # Network idle (no connection for 500 ms) is waited for until the hard cap; a page that never settles is read
    # as it is then.
    idle_end = started + _IDLE_SHARE * policy.browser_timeout_s
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("networkidle", timeout=_ms_until(idle_end))
    try:
        body = (await page.content()).encode()
    except PlaywrightError as e:
        raise _Failed("render_error", navigation) from e
    raw_body: bytes | None = None
    with contextlib.suppress(PlaywrightError):
        raw_body = await response.body()
    return _Rendered(navigation=navigation, body=body, raw_body=raw_body, network=await _json_bodies(json_responses))


def _is_json(response: Response) -> bool:
    # JSON media types: `application/json` (RFC 8259 §11) and the `+json` structured syntax suffix (RFC 6839 §3.1).
    return "json" in response.headers.get("content-type", "").lower()


async def _json_bodies(responses: list[Response]) -> tuple[tuple[NetworkBody, bytes], ...]:
    captured: list[tuple[NetworkBody, bytes]] = []
    for response in responses:
        if len(captured) == _JSON_BODIES_MAX:
            break
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > _JSON_BODY_MAX_BYTES:
            continue
        try:
            data = await response.body()
        except PlaywrightError:
            continue  # no body to read: a redirect, or a request that failed or was evicted
        if len(data) > _JSON_BODY_MAX_BYTES:
            continue
        entry = NetworkBody(
            url=response.url,
            status=response.status,
            content_type=response.headers.get("content-type"),
            sha256=sha256_hex(data),
            file=network_file(len(captured)),
        )
        captured.append((entry, data))
    return tuple(captured)


def _navigation_error(error: PlaywrightError, last_hop: str, rejections: dict[tuple[str, int], RejectReason]) -> str:
    if isinstance(error, PlaywrightTimeout):
        return "timeout"
    reason = rejections.get(_guard_key(last_hop))
    if reason is not None:
        return str(SsrfRejected(reason))
    match = _NET_ERROR.search(error.message)
    return f"network_error: {match.group()}" if match else "network_error"


def _guard_key(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    default = 443 if parts.scheme == "https" else 80
    try:
        port = parts.port or default
    except ValueError:
        port = default
    return (parts.hostname or "", port)


def _header_list(headers: Sequence[Mapping[str, object]]) -> HeaderList:
    # Playwright's header arrays keep repeated names in order (RFC 9110 §5.3), as the bundle does.
    return tuple((str(h["name"]), str(h["value"])) for h in headers)


def _ms_until(deadline: float) -> float:
    # Playwright reads a timeout of 0 as "no timeout": a spent budget becomes the smallest positive one instead.
    return max(1.0, (deadline - time.monotonic()) * 1000)
