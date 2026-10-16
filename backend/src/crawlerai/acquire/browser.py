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

from patchright.async_api import Browser, Page, Request, Response, async_playwright
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.classify import classify, lacks_site_structure
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import RejectReason, SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyEndpoint, UnknownProxyPool, pool_endpoint
from crawlerai.storage.capture_bundle import HeaderList, NetworkBody, network_file, sha256_hex

__all__ = ["BrowserSession", "fetch_browser", "open_browser"]

# Patchright's documented setup (D-1204, D-1205): the full Chromium build (`chromium`), not the headless shell
# Playwright picks for `headless=True` by default, run in Chromium's own headless mode, with its own user agent and
# client hints and no custom headers, so the page, its workers and its requests all show one identity.
_CHANNEL = "chromium"
# WebRTC sends UDP outside any proxy; Chromium's policy `disable_non_proxied_udp` keeps it inside the guard.
_LAUNCH_ARGS = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
# Chromium's implicit proxy-bypass rules (`ProxyBypassRules`, net/proxy_resolution) send `localhost`, 127.0.0.0/8,
# [::1], 169.254.0.0/16 and fe80::/10 around any proxy; 169.254.169.254 is the cloud metadata address. The bypass rule
# `<-loopback>` removes those implicit rules, so they too go through the guard (INV-16). Playwright adds it itself
# unless told not to; it is named here so the guard does not rest on a library default.
_PROXY_ALL_LOOPBACK = "<-loopback>"
# SPEC-02 §4.8, D-0010: JSON bodies are captured up to 2 MB each and 50 per page.
_JSON_BODY_MAX_BYTES = 2_000_000
_JSON_BODIES_MAX = 50
# The wait for the page to settle ends at this share of `browser_timeout_s`; the rest is for reading the DOM and the
# bodies.
_SETTLE_SHARE = 0.9
# D-1200: after `load` (HTML Standard §8.4.6), the page is read once its DOM's structure and text have not changed for
# this long (DOM Standard §4.3, a MutationObserver on `childList` and `characterData`), or once the network is idle.
# Attribute changes are left out: animations and style toggles change attributes, not content.
_QUIET_S = 2.0
_POLL_S = 0.25
# Evaluated in Patchright's isolated world, which shares the document but not the page's globals, so the page neither
# sees nor touches the observer. It is installed on the first call in each document, and answers the seconds since
# the last change.
_QUIET_JS = """() => {
  const millis = () => new Date().getTime();
  if (globalThis.__lastChange === undefined) {
    globalThis.__lastChange = millis();
    new MutationObserver(() => { globalThis.__lastChange = millis(); })
      .observe(document, {subtree: true, childList: true, characterData: true});
  }
  return (millis() - globalThis.__lastChange) / 1000;
}"""
# RFC 9110 §15.4: a 3xx document answer is a redirect hop (or a validator's 304), never the document the frame shows.
_REDIRECTION = range(300, 400)
# RFC 9110 §15.5, §15.6: a 4xx or 5xx document. Its network going idle does not end the wait (D-1201): such a page may
# still replace itself, and is read once its content is quiet.
_ERROR_STATUS = 400
# D-1206: a refusal a page's own script may lift: 403 (RFC 9110 §15.5.4), 429 (RFC 6585 §4), 503 (RFC 9110 §15.6.4);
# not 401/407, which ask for credentials (RFC 9110 §11.6), nor 451, a legal refusal (RFC 7725). Such a document that is
# no site page by structure (`lacks_site_structure`) is an interstitial: the wait for the main frame to navigate on
# lasts up to this share of `browser_timeout_s`, not the 2 s DOM quiet. Nothing is clicked or typed.
_INTERSTITIAL_STATUS = frozenset({403, 429, 503})
_INTERSTITIAL_SHARE = 0.4
# Chromium's network error names (net/base/net_error_list.h) carry no URL.
_NET_ERROR = re.compile(r"net::ERR_[A-Z0-9_]+")


@dataclass(frozen=True)
class BrowserSession:
    """A launched browser, shared by the fetches of one worker process."""

    browser: Browser


@asynccontextmanager
async def open_browser() -> AsyncIterator[BrowserSession]:
    """The browser runs until the block ends; leaving it ends the browser and driver processes."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(channel=_CHANNEL, headless=True, args=_LAUNCH_ARGS)
        try:
            yield BrowserSession(browser)
        finally:
            await browser.close()


class _Failed(Exception):
    def __init__(self, error: str, exchange: Exchange | None) -> None:
        super().__init__(error)
        self.error = error
        self.exchange = exchange


async def fetch_browser(
    url: str,
    policy: FetchPolicy,
    *,
    session: BrowserSession,
    engine_version: str,
    connector: SafeConnector | None = None,
    pools: Mapping[str, ProxyEndpoint] | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every connection."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    timings: dict[str, int] = {}
    error: str | None = None
    exchange: Exchange | None = None
    content = Content(body=b"")
    try:
        proxy = pool_endpoint(policy.proxy_pool, pools)
        async with asyncio.timeout(policy.browser_timeout_s):
            exchange, content = await _render(
                url, policy, session, connector or SafeConnector(), proxy, started, timings
            )
        # classify parses HTML synchronously; a thread keeps the event loop free. Without the page kind: the listing
        # rule calls a page a shell for the browser to render, and the browser is the last rung, so its page is
        # extracted whatever its links (rows from captured JSON are read then).
        headers = exchange.response_headers
        block_class: BlockClass = await asyncio.to_thread(classify, exchange.status, headers, content.body)
    except _Failed as failed:
        error, block_class, exchange = failed.error, "error", failed.exchange
    except UnknownProxyPool as unknown:
        error, block_class = str(unknown), "error"
    except TimeoutError:
        error, block_class = "timeout", "error"
    return fetch_result(
        url=url,
        method="browser",
        policy=policy,
        engine_version=engine_version,
        fetched_at=fetched_at,
        started=started,
        exchange=exchange,
        content=content,
        block_class=block_class,
        error=error,
        # `context` is the browser context's wall time, which `browser_seconds` usage counts (§4.8).
        timings=timings,
    )


async def _render(
    url: str,
    policy: FetchPolicy,
    session: BrowserSession,
    connector: SafeConnector,
    proxy: ProxyEndpoint | None,
    started: float,
    timings: dict[str, int],
) -> tuple[Exchange, Content]:
    try:
        first = await connector.check(url)  # also refuses `file:`, `data:` and other non-web schemes
    except SsrfRejected as e:
        raise _Failed(str(e), None) from e
    async with SocksGuard(connector, checked=(first,), upstream=proxy) as guard:
        context = await session.browser.new_context(
            proxy={"server": guard.url, "bypass": _PROXY_ALL_LOOPBACK}, accept_downloads=False
        )
        opened = time.monotonic()
        try:
            page = await context.new_page()
            return await _navigate(page, url, first, policy, guard, started)
        finally:
            await context.close()
            timings["context"] = round((time.monotonic() - opened) * 1000)


class _MainFrame:
    """The main frame's document navigations (D-1201): the latest request (one per redirect hop), whether one is in
    flight, and the response of the latest document, which the frame shows once the navigation commits."""

    def __init__(self, page: Page, first_url: str) -> None:
        self._page = page
        self.last_hop = first_url
        self.pending = False
        self.latest: Response | None = None

    def _ours(self, request: Request) -> bool:
        return request.is_navigation_request() and request.frame == self._page.main_frame

    def on_request(self, request: Request) -> None:
        if self._ours(request):
            self.last_hop, self.pending = request.url, True

    def on_response(self, response: Response) -> None:
        if self._ours(response.request) and response.status not in _REDIRECTION:
            self.latest, self.pending = response, False

    def on_failed(self, request: Request) -> None:
        if self._ours(request):
            self.pending = False


async def _navigate(
    page: Page, url: str, first: Target, policy: FetchPolicy, guard: SocksGuard, started: float
) -> tuple[Exchange, Content]:
    frame = _MainFrame(page, first.url)
    json_responses: list[Response] = []

    def on_response(response: Response) -> None:
        # The navigation responses are the page itself, not data it loaded.
        if not response.request.is_navigation_request() and _is_json(response):
            json_responses.append(response)

    page.on("request", frame.on_request)
    page.on("response", frame.on_response)
    page.on("requestfailed", frame.on_failed)
    if policy.capture_network_json:
        page.on("response", on_response)

    budget_end = started + policy.browser_timeout_s
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=_ms_until(budget_end))
    except PlaywrightError as e:
        raise _Failed(_navigation_error(e, guard.rejection_for(frame.last_hop)), None) from e
    if response is None:  # only a same-document navigation has none, and a new page has no document yet
        raise _Failed("no_response", None)
    # A page that never settles is read as it is when the wait ends.
    await _settle(
        page,
        frame,
        started + _SETTLE_SHARE * policy.browser_timeout_s,
        interstitial_deadline=started + _INTERSTITIAL_SHARE * policy.browser_timeout_s,
    )
    # The document the frame shows: the first one, or where a navigation it started itself ended.
    response = frame.latest or response
    sent, received = await asyncio.gather(response.request.headers_array(), response.headers_array())
    exchange = Exchange(
        url=response.url,
        status=response.status,
        request_headers=recorded(_header_list(sent)),
        response_headers=recorded(_header_list(received)),
    )
    body, raw_body, network, wire_size = await asyncio.gather(
        _rendered(page, exchange), _raw_body(response), _json_bodies(json_responses), _wire_size(response, exchange)
    )
    # The browser hands over bodies after content decoding; `wire_size` counts the body as it arrived, before. Both
    # caps bound what is stored, not memory: the browser has no streaming read, so the bodies are read in full first.
    decoded = max(len(body), len(raw_body or b""))
    if wire_size > policy.max_body_bytes or decoded > policy.max_decompressed_bytes:
        raise _Failed("body_cap", exchange)
    return exchange, Content(body=body, raw_body=raw_body, network=network)


async def _settle(page: Page, frame: _MainFrame, deadline: float, *, interstitial_deadline: float) -> None:
    """Wait for `load`, then, while the document is an interstitial, for the next one (until `interstitial_deadline`),
    then until the content is quiet (`_QUIET_JS`) or, for a document that is no error, the network is idle (no
    connection for 500 ms), whichever comes first; at most until `deadline`."""
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("load", timeout=_ms_until(deadline))
    while time.monotonic() < interstitial_deadline and await _interstitial(page, frame):
        if not await _next_document(page, frame, interstitial_deadline):
            break
    waits = [asyncio.create_task(_content_quiet(page, frame))]
    if frame.latest is None or frame.latest.status < _ERROR_STATUS:
        waits.append(asyncio.create_task(_network_idle(page, deadline)))
    try:
        await asyncio.wait(waits, timeout=max(0.0, deadline - time.monotonic()), return_when=asyncio.FIRST_COMPLETED)
    finally:
        for wait in waits:
            wait.cancel()
        await asyncio.gather(*waits, return_exceptions=True)


async def _interstitial(page: Page, frame: _MainFrame) -> bool:
    shown = frame.latest
    if shown is None or shown.status not in _INTERSTITIAL_STATUS:
        return False
    try:
        body = (await page.content()).encode()
    except PlaywrightError:
        return False  # the document is being replaced: the waits that follow see the next one
    # classify's rules parse HTML synchronously; a thread keeps the event loop free.
    return await asyncio.to_thread(lacks_site_structure, body)


async def _next_document(page: Page, frame: _MainFrame, deadline: float) -> bool:
    """Whether the main frame showed another document and it loaded before `deadline`."""
    shown = frame.latest
    while frame.latest is shown:
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_POLL_S)
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("load", timeout=_ms_until(deadline))
    return True


async def _content_quiet(page: Page, frame: _MainFrame) -> None:
    """Returns once no navigation is in flight and the document's structure and text have not changed for `_QUIET_S`."""
    while True:
        await asyncio.sleep(_POLL_S)
        if frame.pending:
            continue
        try:
            quiet = cast(float, await page.evaluate(_QUIET_JS))
        except PlaywrightError:
            continue  # the document is being replaced, and its observer with it
        if quiet >= _QUIET_S:
            return


async def _network_idle(page: Page, deadline: float) -> None:
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("networkidle", timeout=_ms_until(deadline))
        return
    await asyncio.Event().wait()  # never idle: the quiet content or the deadline ends the wait


async def _rendered(page: Page, exchange: Exchange) -> bytes:
    try:
        return (await page.content()).encode()
    except PlaywrightError as e:
        raise _Failed("render_error", exchange) from e


async def _raw_body(response: Response) -> bytes | None:
    """The navigation response body, or None when the browser no longer holds it."""
    try:
        return await response.body()
    except PlaywrightError:
        return None


async def _wire_size(response: Response, exchange: Exchange) -> int:
    """The navigation response body's size on the wire, before content decoding."""
    try:
        return (await response.request.sizes())["responseBodySize"]
    except PlaywrightError as e:
        raise _Failed("network_error", exchange) from e


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
        sent = response.request.post_data_buffer
        if len(data) > _JSON_BODY_MAX_BYTES or len(sent or b"") > _JSON_BODY_MAX_BYTES:
            continue
        try:
            headers = recorded(_header_list(await response.request.headers_array()))
        except PlaywrightError:
            headers = None  # the request is gone from the browser
        entry = NetworkBody(
            url=response.url,
            status=response.status,
            content_type=response.headers.get("content-type"),
            sha256=sha256_hex(data),
            file=network_file(len(captured)),
            method=response.request.method,
            request_body=_text_or_none(sent),
            request_headers=headers,
        )
        captured.append((entry, data))
    return tuple(captured)


def _text_or_none(data: bytes | None) -> str | None:
    try:
        return None if data is None else data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _navigation_error(error: PlaywrightError, rejected: RejectReason | None) -> str:
    if isinstance(error, PlaywrightTimeout):
        return "timeout"
    if rejected is not None:
        return str(SsrfRejected(rejected))
    match = _NET_ERROR.search(error.message)
    return f"network_error: {match.group()}" if match else "network_error"


def _header_list(headers: Sequence[Mapping[str, object]]) -> HeaderList:
    # Playwright's header arrays keep repeated names in order (RFC 9110 §5.3), as the bundle does.
    return tuple((str(h["name"]), str(h["value"])) for h in headers)


def _ms_until(deadline: float) -> float:
    # Playwright reads a timeout of 0 as "no timeout": a spent budget becomes the smallest positive one instead.
    return max(1.0, (deadline - time.monotonic()) * 1000)
