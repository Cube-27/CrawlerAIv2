"""A custom recipe's calls sent by the browser (`sent_by = browser`): from a warm page of the site's own profile,
through the page's own `fetch`, so a call carries what the site's scripts add to their requests (a header a fetch hook
sets, the cookies they set) with the browser's identity, proxy and guard. Nothing is rendered per URL.

The warm page is one tab of the site's profile (`browser_session.OpenProfile.warm`), opened on the profile's first call
at the URL the caller names (a recipe's fixed warm-up, else the page the call stands for) and kept while the profile
is open (`_Profiles.keep`: its idle timer, its cap), so it closes with the profile's browser. A profile is taken for
the call like a page's render (`site_profile`), so a call waits for no tab and shares the profile with none;
the caller holds one of the shared session's slots (`SharedBrowser.render`). A call is a `fetch()` in the page's main
world (WHATWG Fetch, `credentials: "include"`) with the request's method, headers and body: the browser adds its own
headers (Fetch Metadata, `Origin`, `Referer`, cookies) and refuses the ones Fetch forbids a script to set. A site
that signs each request in its application code, rather than in a hook every `fetch` goes through, is not
reproduced: its endpoint refuses the call, and the answer's status says so. The answer is read as the JSON rung
reads one (`acquire.api.answer_class`), within the policy's decompressed-size cap.
"""

import asyncio
import base64
import contextlib
from collections.abc import Mapping
from typing import Final, TypedDict, cast

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import Page

from crawlerai.acquire.api import ACCEPT, JsonRequest, answer_class, answer_label
from crawlerai.acquire.browser import HeldProfile, Render, navigation_error, presented, site_profile
from crawlerai.acquire.browser_session import BrowserSession, Failed, context_key
from crawlerai.acquire.browser_wait import MainFrame, ms_until
from crawlerai.acquire.challenge import CHALLENGED, count
from crawlerai.acquire.headers import recorded
from crawlerai.acquire.outcome import Content, Exchange, report_proxy
from crawlerai.acquire.session import SessionScope
from crawlerai.acquire.ssrf import SafeConnector
from crawlerai.acquire.types import FetchPolicy, FetchResult
from crawlerai.core.proxy import ProxyPool
from crawlerai.storage.capture_bundle import HeaderList

__all__ = ["send_in_page"]

# RFC 9110 §15.5, §15.6: a warm page whose document has an error status is not one the site's scripts run in.
_ERROR_STATUS: Final = 400
# The page's own `fetch` (WHATWG Fetch §5.1), in its main world, so a hook the page set on it applies. The body comes
# back as base64 (RFC 4648 §4), the only lossless form a string carries bytes in; one past `cap` comes back as null.
_SEND_JS: Final = """async ([url, method, headers, body, cap]) => {
  const response = await fetch(url, {method, headers, body, credentials: "include"});
  const bytes = new Uint8Array(await response.arrayBuffer());
  const head = {status: response.status, url: response.url, headers: [...response.headers]};
  if (bytes.length > cap) return {...head, body: null};
  let text = "";
  for (let i = 0; i < bytes.length; i += 32768) text += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return {...head, body: btoa(text)};
}"""


class _Answer(TypedDict):
    status: int
    url: str
    headers: list[list[str]]
    body: str | None


async def send_in_page(
    request: JsonRequest,
    policy: FetchPolicy,
    warm_url: str,
    *,
    session: BrowserSession,
    engine_version: str,
    connector: SafeConnector | None = None,
    pools: Mapping[str, ProxyPool] | None = None,
    scope: SessionScope | None = None,
) -> FetchResult:
    """`request` sent from the warm page of its site's profile, opened at `warm_url` when the profile has none; an
    `api` result recorded under the request's `page_url`, as the JSON rung's is. `pools` are the configured proxy pools;
    `scope` the fetch's site state (`SiteSessions.scope_for`), which keeps the site's profile."""
    run = Render(request.page_url, policy, engine_version, scope)
    if run.route(pools):
        try:
            async with asyncio.timeout(policy.browser_timeout_s):
                async with site_profile(warm_url, policy, session, connector or SafeConnector(), run) as held:
                    page = await _warm(held, warm_url, policy, session, run)
                    held.keep = True
                    await _send(held, page, request, policy, run)
                    # A profile the site refused is not reused, as a render's is not (`Render.finish`).
                    held.keep = run.block_class != "blocked"
        except Failed as failed:
            run.failed(failed.error, failed.exchange)
        except TimeoutError:
            run.failed("timeout")
    result = run.result("api")
    count(run.challenge, "api")
    report_proxy(run.pool, run.proxy, result)
    if result.block_class == "blocked" and (key := context_key(warm_url, scope, run.proxy)) is not None:
        await session.profiles.discard(key)
    return result


async def _warm(held: HeldProfile, url: str, policy: FetchPolicy, session: BrowserSession, run: Render) -> Page:
    """The profile's warm page, opened at `url` when it has none, or the one it had left the site or closed."""
    page = held.context.warm
    if page is not None and not page.is_closed() and context_key(page.url, run.scope, run.proxy) == held.key:
        return page
    await _drop(held)
    page = await held.context.context.new_page()
    frame = MainFrame(page, url)
    page.on("request", frame.on_request)
    try:
        await presented(page, session)
        response = await page.goto(url, wait_until="load", timeout=ms_until(run.started + policy.browser_timeout_s))
    except Failed:
        await _close(page)
        raise
    except PlaywrightError as e:
        await _close(page)
        raise Failed(navigation_error(e, held.context.guard.rejection_for(frame.last_hop)), None) from e
    on_site = context_key(page.url, run.scope, run.proxy) == held.key
    if response is None or response.status >= _ERROR_STATUS or not on_site:
        await _close(page)
        raise Failed("warm_page_failed", None)
    held.context.warm = page
    return page


async def _send(held: HeldProfile, page: Page, request: JsonRequest, policy: FetchPolicy, run: Render) -> None:
    """`request` sent through the page's `fetch`, its answer read into `run`. A call `fetch` rejects (a network error,
    a CORS refusal, a header value it refuses) or that the page could not finish (it crashed or navigated away) is
    `call_rejected`, which tells nothing of the proxy endpoint (`report_proxy`): the page is dropped, and the next call
    opens it anew (`_warm`). The request headers recorded are the call's own: the browser drops those Fetch forbids
    and adds its own."""
    headers = _headers(request)
    args = [request.url, request.method, headers, request.body, policy.max_decompressed_bytes]
    try:
        answer = cast(_Answer, await page.evaluate(_SEND_JS, args, isolated_context=False))
    except PlaywrightError as e:
        await _drop(held)
        raise Failed("call_rejected", None) from e
    response_headers: HeaderList = tuple((name, value) for name, value in answer["headers"])
    exchange = Exchange(
        url=answer["url"] or request.url,
        status=answer["status"],
        request_headers=recorded(tuple(headers.items())),
        response_headers=recorded(response_headers),
    )
    if answer["body"] is None:
        raise Failed("body_cap", exchange)
    body = base64.b64decode(answer["body"])
    run.exchange, run.content = exchange, Content(body=body)
    run.block_class, run.error = await asyncio.to_thread(answer_class, exchange.status, body, request.raw)
    if run.block_class in CHALLENGED:
        run.challenge = await asyncio.to_thread(answer_label, exchange.status, response_headers, body, request.url)


def _headers(request: JsonRequest) -> dict[str, str]:
    """The request's headers as `fetch` takes them: `Accept` as the JSON rung sends it, the recipe's own last and
    winning (field names are case-insensitive, RFC 9110 §5.1)."""
    headers = {"accept": ACCEPT}
    headers.update((name.lower(), value) for name, value in request.headers)
    return headers


async def _drop(held: HeldProfile) -> None:
    """Close the profile's warm page, if it has one."""
    page, held.context.warm = held.context.warm, None
    if page is not None:
        await _close(page)


async def _close(page: Page) -> None:
    with contextlib.suppress(PlaywrightError):
        await page.close()
