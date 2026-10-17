"""Browser fetch with Patchright headless Chromium (SPEC-02 §4.8, ARCHITECTURE §7.1): one navigation, bounded waits,
and the JSON bodies the page loads captured, the network data-source layer's input (Appendix A #59) and API
discovery's (§7.2 step 1).

One browser per worker process (`open_browser`), one fresh context per fetch. Every connection the context opens goes
through a `SocksGuard`, which applies the SSRF guard to every redirect hop, frame and worker (§4.5). As in
`fetch_http`, every failure becomes an `error` outcome with a short reason that never contains the URL (D-0128). A
`blocked` or `shell` document is labelled with the challenge it presents (`acquire.challenge`), and the pool endpoint
it went through is told how it went (`core.proxy_health`), as the HTTP rung does. Asked to export (`CookieExport`), the
fetch reads the context's cookies before the context closes, without changing them, for a site session (INV-29's
exception).
"""

import asyncio
import contextlib
import re
import time
from collections.abc import AsyncIterator, Awaitable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from patchright.async_api import Browser, BrowserContext, Frame, Page, Request, Response, async_playwright
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeout

from crawlerai.acquire.challenge import CHALLENGED, challenge_label, count
from crawlerai.acquire.classify import INTERSTITIAL_STATUS, classify, interstitial
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, Traffic, fetch_result, report_proxy
from crawlerai.acquire.session import CookieExport, SessionCookie, browser_cookies
from crawlerai.acquire.socks_guard import SocksGuard
from crawlerai.acquire.ssrf import RejectReason, SafeConnector, SsrfRejected, Target
from crawlerai.acquire.types import BlockClass, FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyEndpoint, ProxyPool, UnknownProxyPool, pool_endpoint, proxy_pool
from crawlerai.storage.capture_bundle import HeaderList, NetworkBody, network_file, network_json, sha256_hex

__all__ = [
    "DATA_REQUESTS",
    "BrowserSession",
    "DataCalls",
    "Failed",
    "Rendered",
    "challenge_of",
    "classified",
    "context_cookies",
    "fetch_browser",
    "json_bodies",
    "open_browser",
    "read_state",
    "rendered",
]

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
# SPEC-02 §4.8, D-0010: JSON bodies are captured up to 2 MB each and 50 per page; INV-30 (Appendix A #59): at most
# 10 MB of them per page in all.
_JSON_BODY_MAX_BYTES = 2_000_000
_JSON_BODIES_MAX = 50
_JSON_PAGE_MAX_BYTES = 10_000_000
# Fetch Standard §2.2.5: requests whose destination is the empty string (fetch() and XMLHttpRequest) or `document`
# carry data or a new document; Playwright names them `fetch`, `xhr` and `document`. Scripts, styles, images and fonts
# are the page's code and media, not data it loads.
DATA_REQUESTS = frozenset({"fetch", "xhr", "document"})
# WHATWG MIME Sniffing §4.6: the JSON MIME types are `application/json`, `text/json` and any type with the `+json`
# structured syntax suffix (RFC 6839 §3.1). A body labelled `text/plain`, or not labelled, may still be JSON: it is
# kept only when its bytes are (`network_json`, RFC 8259).
_SNIFFED_TYPES = frozenset({"text/plain", ""})
# The wait for the page to settle ends at this share of `browser_timeout_s`; the rest is for reading the DOM and the
# bodies.
_SETTLE_SHARE = 0.9
# D-1200: after `load` (HTML Standard §8.4.6), the page is read once its DOM's structure and text have not changed for
# this long (DOM Standard §4.3, a MutationObserver on `childList` and `characterData`), or once the network is idle.
# Attribute changes are left out: animations and style toggles change attributes, not content.
_QUIET_S = 2.0
_POLL_S = 0.25
# A page whose content is quiet while one of its fetch or XMLHttpRequest calls (Fetch Standard §2.2.5 destinations) is
# still in flight is waited for up to this much longer, so a data call that arrives late is kept; a call that never
# ends (a long poll) holds the read no longer than that.
_CALL_WAIT_S = 3.0
_CALLS = frozenset({"fetch", "xhr"})
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
# D-1206, D-1262: for a document `interstitial` judges to stand in for the page, the wait for the main frame to navigate
# on lasts up to this share of `browser_timeout_s`, not the 2 s DOM quiet, and ends as soon as a navigation commits.
# Nothing is clicked or typed.
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


class Failed(Exception):
    """A browser fetch that ends as an `error` outcome: the short reason, and the exchange when a response arrived."""

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
    pools: Mapping[str, ProxyPool] | None = None,
    export: CookieExport | None = None,
) -> FetchResult:
    """`pools` are the configured proxy pools; the one `policy.proxy_pool` names carries every connection. `export`,
    when given, receives the context's cookies and the endpoint, whatever the outcome; the caller decides whether a
    session opens."""
    fetched_at = datetime.now(UTC)
    started = time.monotonic()
    timings: dict[str, int] = {}
    error: str | None = None
    exchange: Exchange | None = None
    content = Content(body=b"")
    pool = proxy = None
    challenge: str | None = None
    traffic = Traffic()
    try:
        pool = proxy_pool(policy.proxy_pool, pools)
        proxy = pool_endpoint(pool, url)
        async with asyncio.timeout(policy.browser_timeout_s):
            guarded = rendered(url, policy, session, connector or SafeConnector(), proxy, started, timings, traffic)
            async with guarded as page:
                exchange, content = await read_state(page)
                cookies = await context_cookies(page.page.context)
        block_class = await classified(exchange, content)
        challenge = await challenge_of(block_class, exchange, content, url, cookies)
        if export is not None:
            export.cookies, export.proxy = cookies, proxy
    except Failed as failed:
        error, block_class, exchange = failed.error, "error", failed.exchange
    except UnknownProxyPool as unknown:
        error, block_class = str(unknown), "error"
    except TimeoutError:
        error, block_class = "timeout", "error"
    count(challenge, "browser")
    result = fetch_result(
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
        challenge=challenge,
        transferred=traffic.bytes,
    )
    report_proxy(pool, proxy, result)
    return result


async def context_cookies(context: BrowserContext) -> tuple[SessionCookie, ...]:
    """Every cookie the context holds, read without changing any (INV-42: nothing is set in the browser); none when
    the context is gone."""
    try:
        return browser_cookies(cast(list[Mapping[str, object]], await context.cookies()))
    except PlaywrightError:
        return ()


async def challenge_of(
    block_class: BlockClass, exchange: Exchange, content: Content, url: str, cookies: tuple[SessionCookie, ...]
) -> str | None:
    """The challenge label of a `CHALLENGED` document (`acquire.challenge`), from its response headers, the names of
    the cookies the context holds (its capture records no `Set-Cookie`) and its markup."""
    if block_class not in CHALLENGED:
        return None
    names = tuple(cookie.name for cookie in cookies)
    return await asyncio.to_thread(
        challenge_label, exchange.status, exchange.response_headers, content.body, url, names
    )


async def classified(exchange: Exchange, content: Content) -> BlockClass:
    """The block class of a rendered document. classify parses HTML synchronously; a thread keeps the event loop
    free. Without the page kind: the listing rule calls a page a shell for the browser to render, and the browser is
    the last rung, so its page is extracted whatever its links (rows from captured JSON are read then)."""
    return await asyncio.to_thread(classify, exchange.status, exchange.response_headers, content.body)


@dataclass
class DataCalls:
    """The data responses a page has received so far (when the policy captures them), in arrival order, each with how
    many browser actions the page had performed when it arrived; `actions` is that count now, which a listing's
    browser actions raise (`browser_tab`)."""

    responses: list[tuple[Response, int]] = field(default_factory=list)
    actions: int = 0
    in_flight: set[Request] = field(default_factory=set)  # the fetch and XMLHttpRequest calls not answered yet

    def on_request(self, request: Request) -> None:
        if request.resource_type in _CALLS:
            self.in_flight.add(request)

    def on_done(self, request: Request) -> None:
        self.in_flight.discard(request)

    def on_response(self, response: Response, main_frame: Frame) -> None:
        request = response.request
        # The main frame's navigation responses are the page itself, not data it loaded.
        if request.is_navigation_request() and request.frame == main_frame:
            return
        if request.resource_type in DATA_REQUESTS and _json_label(response) is not None:
            self.responses.append((response, self.actions))


@dataclass
class Rendered:
    """A page whose navigation has settled: the tab, its main frame's navigations, the first document's response, the
    policy it was fetched with, and the data responses it has loaded so far."""

    page: Page
    frame: "_MainFrame"
    response: Response
    policy: FetchPolicy
    calls: DataCalls = field(default_factory=DataCalls)


@asynccontextmanager
async def rendered(
    url: str,
    policy: FetchPolicy,
    session: BrowserSession,
    connector: SafeConnector,
    proxy: ProxyEndpoint | None,
    started: float,
    timings: dict[str, int],
    traffic: Traffic,
) -> AsyncIterator[Rendered]:
    """The page at `url` in a fresh context, once its navigation has settled; the context closes when the block ends,
    and its wall time is `timings["context"]`. The bytes the guard relays are added to `traffic`. Raises `Failed`."""
    try:
        first = await connector.check(url)  # also refuses `file:`, `data:` and other non-web schemes
    except SsrfRejected as e:
        raise Failed(str(e), None) from e
    async with SocksGuard(connector, checked=(first,), upstream=proxy, traffic=traffic) as guard:
        context = await session.browser.new_context(
            proxy={"server": guard.url, "bypass": _PROXY_ALL_LOOPBACK}, accept_downloads=False
        )
        opened = time.monotonic()
        try:
            page = await context.new_page()
            yield await _navigate(page, url, first, policy, guard, started)
        finally:
            await context.close()
            timings["context"] = round((time.monotonic() - opened) * 1000)


class _MainFrame:
    """The main frame's document navigations (D-1201): the latest request (one per redirect hop), whether one is in
    flight, the response of the latest document, which the frame shows once the navigation commits, and how many
    navigations have committed."""

    def __init__(self, page: Page, first_url: str) -> None:
        self._page = page
        self.last_hop = first_url
        self.pending = False
        self.latest: Response | None = None
        self.commits = 0
        self._committed = asyncio.Event()

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

    def on_navigated(self, frame: Frame) -> None:
        if frame == self._page.main_frame:
            self.commits += 1
            self._committed.set()

    async def next_commit(self) -> None:
        """Returns once the main frame commits a navigation after this call."""
        shown = self.commits
        self._committed.clear()  # no callback runs before the wait: the event loop is not yielded to in between
        while self.commits == shown:
            await self._committed.wait()
            self._committed.clear()


async def _navigate(
    page: Page, url: str, first: Target, policy: FetchPolicy, guard: SocksGuard, started: float
) -> Rendered:
    frame = _MainFrame(page, first.url)
    calls = DataCalls()
    page.on("request", frame.on_request)
    page.on("response", frame.on_response)
    page.on("requestfailed", frame.on_failed)
    page.on("framenavigated", frame.on_navigated)
    page.on("request", calls.on_request)
    page.on("requestfinished", calls.on_done)
    page.on("requestfailed", calls.on_done)
    if policy.capture_network_json:
        page.on("response", lambda response: calls.on_response(response, page.main_frame))

    budget_end = started + policy.browser_timeout_s
    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=_ms_until(budget_end))
    except PlaywrightError as e:
        raise Failed(_navigation_error(e, guard.rejection_for(frame.last_hop)), None) from e
    if response is None:  # only a same-document navigation has none, and a new page has no document yet
        raise Failed("no_response", None)
    # A page that never settles is read as it is when the wait ends.
    await _settle(
        page,
        frame,
        started + _SETTLE_SHARE * policy.browser_timeout_s,
        interstitial_deadline=started + _INTERSTITIAL_SHARE * policy.browser_timeout_s,
        calls=calls,
    )
    return Rendered(page, frame, response, policy, calls)


async def read_state(
    rendered: Rendered, *, url: str | None = None, calls: tuple[int, int | None] = (0, None)
) -> tuple[Exchange, Content]:
    """The document the page shows now, as an exchange and its content: the first document, or where a navigation
    ended (one it started itself, or a browser action's), under `url` when given (the response's URL otherwise), with
    the JSON bodies of the data responses in the `calls` slice (all of them by default). Raises `Failed` for a body
    past the policy's caps, or a response the browser no longer holds."""
    policy = rendered.policy
    response = rendered.frame.latest or rendered.response
    try:
        sent, received = await asyncio.gather(response.request.headers_array(), response.headers_array())
    except PlaywrightError as e:
        raise Failed("no_response", None) from e
    exchange = Exchange(
        url=url or response.url,
        status=response.status,
        request_headers=recorded(_header_list(sent)),
        response_headers=recorded(_header_list(received)),
    )
    # D-1265: the size the body arrived with is read before any body, so a body over `max_body_bytes` never enters
    # this process. The browser hands over bodies after content decoding, in full (Playwright has no streaming read):
    # the decompressed cap is checked once they are read, and bounds what is stored.
    if await _wire_size(response, exchange) > policy.max_body_bytes:
        raise Failed("body_cap", exchange)
    body, raw_body, network = await asyncio.gather(
        _rendered(rendered.page, exchange),
        _raw_body(response),
        json_bodies(rendered.calls.responses[slice(*calls)]),
    )
    if max(len(body), len(raw_body or b"")) > policy.max_decompressed_bytes:
        raise Failed("body_cap", exchange)
    return exchange, Content(body=body, raw_body=raw_body, network=network)


async def _settle(
    page: Page, frame: _MainFrame, deadline: float, *, interstitial_deadline: float, calls: DataCalls
) -> None:
    """Wait for `load`, then, while the document is an interstitial, for the next one (until `interstitial_deadline`),
    then until the content is quiet (`_QUIET_JS`) with no data call in flight (`_CALL_WAIT_S` at most) or, for a
    document that is no error, the network is idle (no connection for 500 ms), whichever comes first; at most until
    `deadline`."""
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("load", timeout=_ms_until(deadline))
    while time.monotonic() < interstitial_deadline and await _interstitial(page, frame):
        if not await _next_document(page, frame, interstitial_deadline):
            break
    waits = [asyncio.create_task(_content_quiet(page, frame, calls))]
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
    if shown is None or shown.status not in INTERSTITIAL_STATUS:
        return False
    try:
        body = (await page.content()).encode()
    except PlaywrightError:
        return False  # the document is being replaced: the waits that follow see the next one
    # classify's rules parse HTML synchronously; a thread keeps the event loop free.
    return await asyncio.to_thread(interstitial, shown.status, tuple(shown.headers.items()), body, shown.url)


async def _next_document(page: Page, frame: _MainFrame, deadline: float) -> bool:
    """Whether the main frame committed another navigation and its document loaded before `deadline`. The commit, not
    the response: until then the frame still shows the interstitial, whose `load` has fired."""
    try:
        async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
            await frame.next_commit()
    except TimeoutError:
        return False
    with contextlib.suppress(PlaywrightTimeout):
        await page.wait_for_load_state("load", timeout=_ms_until(deadline))
    return True


async def _content_quiet(page: Page, frame: _MainFrame, calls: DataCalls) -> None:
    """Returns once no navigation is in flight and the document's structure and text have not changed for `_QUIET_S`,
    nor for `_CALL_WAIT_S` more while a data call is in flight."""
    while True:
        await asyncio.sleep(_POLL_S)
        if frame.pending:
            continue
        try:
            quiet = cast(float, await page.evaluate(_QUIET_JS))
        except PlaywrightError:
            continue  # the document is being replaced, and its observer with it
        if quiet >= (_QUIET_S + _CALL_WAIT_S if calls.in_flight else _QUIET_S):
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
        raise Failed("render_error", exchange) from e


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
        raise Failed("network_error", exchange) from e


async def _json_size(response: Response) -> int:
    """A JSON body's size before it is read: its `Content-Length` (RFC 9110 §8.6), else its size on the wire (D-1265);
    0 when the browser no longer holds the request, whose body then can't be read either."""
    declared = response.headers.get("content-length", "")
    if declared.isdigit():
        return int(declared)
    try:
        return (await response.request.sizes())["responseBodySize"]
    except PlaywrightError:
        return 0


def _json_label(response: Response) -> bool | None:
    """True when the response is labelled with a JSON MIME type, False when its label leaves its body to be sniffed,
    None when it names another kind of body (`_SNIFFED_TYPES`). The essence is compared, lower-cased, parameters
    dropped (WHATWG MIME Sniffing §2.1)."""
    essence = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if essence in ("application/json", "text/json") or essence.endswith("+json"):
        return True
    return False if essence in _SNIFFED_TYPES else None


async def json_bodies(responses: list[tuple[Response, int]]) -> tuple[tuple[NetworkBody, bytes], ...]:
    """The JSON bodies of `responses` (each with the action count it arrived at) a capture keeps, within its caps."""
    captured: list[tuple[NetworkBody, bytes]] = []
    total = 0
    for response, action in responses:
        if len(captured) == _JSON_BODIES_MAX:
            break
        data = await _json_body(response)
        if data is None or total + len(data) > _JSON_PAGE_MAX_BYTES:
            continue
        sent = response.request.post_data_buffer
        if len(sent or b"") > _JSON_BODY_MAX_BYTES:
            continue
        entry = NetworkBody(
            url=response.url,
            status=response.status,
            content_type=response.headers.get("content-type"),
            sha256=sha256_hex(data),
            file=network_file(len(captured)),
            method=response.request.method,
            request_body=_text_or_none(sent),
            request_headers=await _headers(response.request.headers_array()),
            response_headers=await _headers(response.headers_array()),
            resource_type=response.request.resource_type,
            action=action,
        )
        captured.append((entry, data))
        total += len(data)
    return tuple(captured)


async def _json_body(response: Response) -> bytes | None:
    """The response's body when it is not empty, within the per-body cap, and JSON: labelled so, or sniffed as JSON
    text holding an object or an array (`network_json`)."""
    if await _json_size(response) > _JSON_BODY_MAX_BYTES:
        return None
    try:
        data = await response.body()
    except PlaywrightError:
        return None  # no body to read: a redirect, or a request that failed or was evicted
    if not data or len(data) > _JSON_BODY_MAX_BYTES:
        return None  # an empty body (a 204, RFC 9110 §15.3.5) holds no JSON text
    return data if _json_label(response) or _sniffed(data) else None


def _sniffed(data: bytes) -> bool:
    try:
        return isinstance(network_json(data), (dict, list))
    except ValueError:
        return False


async def _headers(read: Awaitable[Sequence[Mapping[str, object]]]) -> HeaderList | None:
    """A request's or response's headers as a capture records them (no credentials); None when the browser no longer
    holds them."""
    try:
        return recorded(_header_list(await read))
    except PlaywrightError:
        return None


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
