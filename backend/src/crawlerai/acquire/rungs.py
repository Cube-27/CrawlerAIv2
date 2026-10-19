"""Rung selection (acquisition spec): HTTP by default, the browser on evidence, and the method that
worked remembered per site and page kind in `site_fetch_method` (D-1380).

A URL an active adapter detects goes to that adapter (`crawlerai.adapters`) first, and to the page rungs when the
adapter does not serve it (adapters spec). A page whose own canonical link is its URL without the query, which an
adapter detects, or which an adapter says stands for one of its platform's pages, is then served by that adapter
(adapters spec). A site whose active config has an API recipe is
served by the recipe's rung (adapters spec), which the caller binds to the recipe: the config IR sits above `acquire`
(`.importlinter`). The browser rung is `crawlerai.acquire.browser.fetch_browser`. Every rung is a function of
(url, policy), so `acquire` decides and records only. The one exception is the HTTP rung's conditional form, which
also takes the validators a page last answered with (jobs spec), and the browser rung's exporting form, which also
hands the context's cookies to a site session (`acquire.session`, INV-29's exception).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final, Protocol
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.browser_tab import ListingRung
from crawlerai.acquire.challenge import block_class_of
from crawlerai.acquire.classify import interstitial
from crawlerai.acquire.page_refs import canonical_link, page_refs
from crawlerai.acquire.politeness import BACKOFF_MAX, SLOW_DOWN, Admit, backoff
from crawlerai.acquire.session import CookieExport, SiteSessions, identity
from crawlerai.acquire.types import (
    AttemptRecord,
    BlockClass,
    FetchPolicy,
    FetchResult,
    Validators,
    fetched_as,
    policy_with_attempts,
)
from crawlerai.adapters.registry import Registry, platform_adapters
from crawlerai.db.models import FetchMethod, PageKind, SiteFetchMethod, SiteId
from crawlerai.storage.capture_bundle import decode_body

Rung = Callable[[str, FetchPolicy], Awaitable[FetchResult]]


class RenderCheck(Protocol):
    """Whether an `ok` page lacks what the caller reads from it and a render may hold (offer data, owner #49; a
    listing's items, owner #54); asked of a render `over` the HTTP page it would replace, whether the render still
    lacks it compared with that page. The caller's, since what a page should hold depends on the schema, which sits
    above `acquire`."""

    def __call__(self, result: FetchResult, over: FetchResult | None = None, /) -> Awaitable[bool]: ...


# A fetch so far: the outcome kept, every attempt and their duration.
Fetched = tuple[FetchResult, tuple[AttemptRecord, ...], int]
# The adapter answer for the page a fetch has so far, when an adapter serves its canonical or referred URL; else that
# page (`_by_canonical`).
Refer = Callable[[Fetched], Awaitable[Fetched]]


class ConditionalRung(Protocol):
    """The HTTP rung sending `validators` (`crawlerai.acquire.http.fetch_http`)."""

    def __call__(self, url: str, policy: FetchPolicy, *, validators: Validators | None) -> Awaitable[FetchResult]: ...


class ExportingRung(Protocol):
    """The browser rung filling `export` with the context's cookies (`crawlerai.acquire.browser.fetch_browser`)."""

    def __call__(self, url: str, policy: FetchPolicy, *, export: CookieExport) -> Awaitable[FetchResult]: ...


_NOT_MODIFIED = 304
# owner plan 2026-10-19 P3: a render takes seconds (`FetchPolicy.browser_timeout_s` at most), so none starts with less
# than this left of the task's budget; the HTTP outcome is kept instead.
BROWSER_MIN_S: Final = 20.0
_UNAVAILABLE = 503  # RFC 9110 §15.6.4
# The HTTP outcomes that are evidence for the browser, which may pass where HTTP did not.
_BROWSER_EVIDENCE: frozenset[BlockClass] = frozenset({"shell", "blocked"})
# acquisition spec: the reason of a request a transport failure left unanswered (`curl_client.reason`), such as a reset
# HTTP/2 stream (curl 92) or connection. A filter may reset a client whose TLS or HTTP/2 fingerprint it does not trust;
# the browser's own network stack may pass (D-1472). A timeout (`policy.timeout_s`) counts too: a filter may hold a
# client it does not trust unanswered, and the same transport again would wait as long.
_UNANSWERED: Final = ("network_error", "timeout")


@dataclass(frozen=True)
class Rungs:
    http: Rung
    browser: Rung
    adapters: Registry = field(default_factory=lambda: Registry(()))
    # The HTTP rung in its conditional form, for fetches given validators; without it they are sent nowhere.
    conditional: ConditionalRung | None = None
    # JSON over HTTP (`acquire.api.fetch_json`), which an active config's API recipe sends its request with
    # (adapters spec); without it no recipe serves a page.
    json: JsonFetcher | None = None
    # A listing with browser actions (`acquire.browser_tab.fetch_listing`, owner #52); the API process sets it.
    listing: ListingRung | None = None
    # The site sessions of this process, which the HTTP and JSON rungs were bound to, and the browser rung's exporting
    # form that opens them; without both a browser retry opens none (INV-29 without its exception).
    sessions: SiteSessions | None = None
    exporting: ExportingRung | None = None


def adapter_registry(disabled: Collection[str]) -> Registry:
    """The registry of every platform adapter, all running but the `disabled` ones (adapters spec), for the processes
    that fetch; it raises `ValueError` for a name no adapter has. One per process: it remembers the hosts its adapters
    declined."""
    adapters = platform_adapters()
    names = {adapter.name for adapter in adapters}
    if unknown := sorted(set(disabled) - names):
        raise ValueError(f"no adapter named {unknown}")
    return Registry(adapter for adapter in adapters if adapter.name not in disabled)


async def acquire(
    url: str,
    policy: FetchPolicy,
    remembered: FetchMethod,
    rungs: Rungs,
    *,
    recipe: Rung | None = None,
    validators: Validators | None = None,
    admit_next: Admit | None = None,
    send: JsonFetcher | None = None,
    needs_render: RenderCheck | None = None,
    deadline: float | None = None,
) -> FetchResult:
    """Fetch `url` through the active adapter that detects it, if any, requesting its API with `send` (no adapter runs
    without it); a page an adapter does not serve skips the recipe (adapters spec). Otherwise through `recipe`, the
    active config's API recipe bound to its fetch (adapters spec), when the site has one. The adapter's result is kept
    when it is `ok`, the recipe's when it is `ok` or asks for fewer requests; otherwise the page is fetched as if there
    were neither (§4.10, INV-40). Without either, fetch it with `policy.method_hint`, or else the site's `remembered`
    method. In `auto`, an HTTP shell, block or network error is fetched again in the browser, and the browser's outcome
    is kept only if it is `ok`; so is an HTTP `ok` page `needs_render` holds true for, whose browser outcome is kept
    only if it is `ok` and `needs_render` no longer holds (owner #49, #54). Each request after the first (the page after
    an adapter or a recipe, the browser retry) waits for `admit_next` to admit it at the site's rate (acquisition spec),
    and is not sent when `admit_next` refuses it: the fetch keeps the outcome it has. The result lists every attempt, in
    its bundle's manifest too. `validators` go with the HTTP rung only (jobs spec): a 304 is `ok` and ends the fetch. A
    page no adapter detected whose canonical link is its URL without the query, which an adapter detects, is fetched
    again by that adapter on its own turn (adapters spec); an HTTP `ok` page that would be rendered only for lacking
    what the caller reads asks it before the render, which runs only when no adapter serves it (D-1388). A policy that
    captures the page (`screenshot`, `pdf`) uses neither an adapter nor a recipe. No browser retry starts with less than
    `BROWSER_MIN_S` left before `deadline` (on `time.monotonic`), the task's budget: the HTTP outcome is kept."""
    if policy.captures_page:
        send = recipe = None  # a screenshot or PDF is of the page itself, which an adapter's or a recipe's JSON is not
    served = None if send is None else await rungs.adapters.serve(url, policy, send)
    # An adapter's endpoint is not the page: its slow-down holds back the page only by the pause it put on the host's
    # rate, which `admit_next` waits out (adapters spec). A recipe's may be the page's own (its HTML page request).
    by_recipe = served is None and recipe is not None
    if served is None and recipe is not None:
        served = await recipe(url, policy)
    if served is not None and (
        served.block_class == "ok" or (by_recipe and slow_down(served)) or not await _admitted(admit_next)
    ):
        return served
    refer = None
    # A page no adapter detected (none answered, or only the recipe did) may name a URL one does (adapters spec,
    # "Referral from a tenant's own host").
    if send is not None and (served is None or by_recipe):
        asked: set[str] = set()

        async def refer(page: Fetched) -> Fetched:
            return await _by_canonical(url, page, policy, rungs, send, admit_next, asked)

    page = await _page(url, policy, remembered, rungs, _Retry(validators, admit_next, needs_render, deadline), refer)
    kept, attempts, duration_ms = page if refer is None else await refer(page)
    if served is not None:
        return with_attempts(kept, served.attempts + attempts, served.duration_ms + duration_ms)
    return with_attempts(kept, attempts, duration_ms)


async def _by_canonical(
    url: str,
    page: Fetched,
    policy: FetchPolicy,
    rungs: Rungs,
    send: JsonFetcher,
    admit_next: Admit | None,
    asked: set[str],
) -> Fetched:
    """The adapter's answer for the page's canonical URL (`_query_dropped`), or for the platform page the page on its
    own host stands for (`_referred`), when there is one, it is `ok` and the site's rate admits the request; else the
    page. Either way with every attempt. A URL in `asked` was asked already in this fetch, and is not asked again."""
    kept, attempts, duration_ms = page
    canonical = _query_dropped(url, kept, rungs.adapters) or _referred(kept, policy, rungs.adapters)
    if canonical is None or canonical in asked or not await _admitted(admit_next):
        return page
    asked.add(canonical)
    served = await rungs.adapters.serve(canonical, policy, send)
    if served is None:
        return page
    return (
        (served if served.block_class == "ok" else kept),
        attempts + served.attempts,
        duration_ms + served.duration_ms,
    )


def _query_dropped(url: str, page: FetchResult, adapters: Registry) -> str | None:
    """`url` without its query, when an adapter detects that URL and the page names it as its canonical (RFC 6596; HTML
    Standard §4.6.7.3, `link rel=canonical`): the page says the parameters it drops do not identify it. No list of
    parameter names decides it (C4). None otherwise."""
    parts = urlsplit(url)
    if not parts.query or page.block_class != "ok":
        return None
    bare = urlunsplit(parts._replace(query="", fragment=""))
    # A host its adapter declined is not asked again, so the request would take a turn at the site's rate for nothing.
    if not adapters.would_serve(bare) or (canonical := canonical_link(page)) is None:
        return None
    return bare if _same_resource(canonical, bare) else None


def _referred(page: FetchResult, policy: FetchPolicy, adapters: Registry) -> str | None:
    """The platform page an active adapter says the fetched page stands for, from what the page states (its redirect,
    canonical link, `og:url`, links; adapters spec): a site on a tenant's own host that the platform serves."""
    if page.block_class != "ok":
        return None
    return adapters.referred(lambda: page_refs(page), policy.page_kind)


def _same_resource(a: str, b: str) -> bool:
    """Equal scheme, host (both case-insensitive, RFC 3986 §6.2.2.1), port, path and query; the fragment names a part
    of the resource, not another one (§3.5)."""
    x, y = urlsplit(a), urlsplit(b)
    return (x.scheme.lower(), x.hostname, x.port, x.path, x.query) == (
        y.scheme.lower(),
        y.hostname,
        y.port,
        y.path,
        y.query,
    )


@dataclass(frozen=True)
class _Retry:
    """What decides the page rung's requests (`acquire`): the validators for HTTP, the admission of a further request,
    the caller's render check, and the deadline no browser retry starts too close to."""

    validators: Validators | None
    admit_next: Admit | None
    needs_render: RenderCheck | None
    deadline: float | None

    def in_budget(self) -> bool:
        return self.deadline is None or self.deadline - time.monotonic() >= BROWSER_MIN_S


async def _page(
    url: str, policy: FetchPolicy, remembered: FetchMethod, rungs: Rungs, retry: _Retry, refer: Refer | None = None
) -> Fetched:
    """The page over HTTP or in the browser (`acquire`): the outcome kept, every attempt and their duration. An HTTP
    page kept for want of a browser outcome is the fetch's last page (`_as_last_page`). An HTTP `ok` page that would
    be rendered only for lacking what the caller reads is first offered to `refer` (its adapter canonical or
    referral), whose `ok` answer is kept without the render (D-1388)."""
    needs_render = retry.needs_render
    method = remembered if policy.method_hint == "auto" else policy.method_hint
    if method == "http" and rungs.conditional is not None:
        result = await rungs.conditional(url, policy, validators=retry.validators)
    else:
        result = await (rungs.http if method == "http" else rungs.browser)(url, policy)
    retried = policy.method_hint == "auto" and method == "http" and await _browser_may_help(result, needs_render)
    page: Fetched = (result, result.attempts, result.duration_ms)
    if retried and refer is not None and result.block_class == "ok":
        page = await refer(page)
        if page[0] is not result:
            return page
    _, attempts, duration_ms = page
    if not retried or not retry.in_budget() or not await _admitted(retry.admit_next, after=_paused_by(result)):
        return await _as_last_page(result), attempts, duration_ms
    rendered = await _browser_retry(url, policy, rungs, result)
    kept = rendered if await _better(rendered, result, needs_render) else await _as_last_page(result)
    return kept, attempts + rendered.attempts, duration_ms + rendered.duration_ms


async def _browser_retry(url: str, policy: FetchPolicy, rungs: Rungs, result: FetchResult) -> FetchResult:
    """The browser attempt after the HTTP `result`. When HTTP was refused (`shell` or `blocked`) and the process keeps
    site sessions, the browser's `ok` opens the site's session with the context's cookies, challenge and clearance
    cookies left out, and the identity it sent (INV-29's exception), and its attempt says so (`site_session`)."""
    sessions, exporting = rungs.sessions, rungs.exporting
    # A fetch with the caller's own context opens no session (D-1432): its cookies are the caller's, not the site's.
    handoff = policy.context is None and result.block_class in _BROWSER_EVIDENCE
    if sessions is None or exporting is None or not handoff:
        return await rungs.browser(url, policy)
    export = CookieExport()
    retry = await exporting(url, policy, export=export)
    if retry.block_class != "ok" or sessions.open(url, policy.proxy_pool, export, identity(retry)) is None:
        return retry
    opened = tuple(a.model_copy(update={"site_session": True}) for a in retry.attempts)
    return retry.model_copy(update={"attempts": opened})


async def _browser_may_help(result: FetchResult, needs_render: RenderCheck | None) -> bool:
    if _browser_may_pass(result) or await _interstitial_unavailable(result):
        return True
    # RFC 9110 §15.4.5: a 304 has no content, so there is nothing to check.
    if result.block_class != "ok" or result.bundle.manifest.status_code == _NOT_MODIFIED or needs_render is None:
        return False
    return await needs_render(result)


async def _interstitial_unavailable(result: FetchResult) -> bool:
    """D-1263: a 503 (RFC 9110 §15.6.4) whose document stands in for the page until its script or refresh navigates
    on (`classify.interstitial`): the browser may pass it, once the site's pause is over (`_paused_by`). A 429 asks
    for fewer requests and nothing else, so it gets no browser attempt."""
    manifest = result.bundle.manifest
    if manifest.status_code != _UNAVAILABLE or manifest.method != "http":
        return False
    text = decode_body(result.bundle)
    return await asyncio.to_thread(
        interstitial, manifest.status_code, manifest.headers.response, text, manifest.final_url
    )


def _paused_by(result: FetchResult) -> timedelta:
    """The pause a slow-down `result` asks for before the browser attempt (`politeness.backoff`); none for another
    result. A pause past the longest backoff is longer than any caller waits in place, so the attempt is not sent."""
    if not slow_down(result):
        return timedelta(0)
    pause = backoff(result.attempts[-1])
    return BACKOFF_MAX if pause is None else pause


async def _as_last_page(result: FetchResult) -> FetchResult:
    """D-1261: an HTTP page kept with no browser outcome is the last page of the fetch, which is extracted whatever its
    links, as the browser's is (`browser.classified`): a listing shell by the listing rule alone (a page with site
    structure but no repeated items, `classify`) becomes `ok`, so the rows role C reads from it are kept; one showing a
    vendor's stand-in marker (`block_class_of`) stays as it is. Its attempt keeps the class HTTP gave it."""
    manifest = result.bundle.manifest
    if result.block_class != "shell" or manifest.method != "http" or fetched_as(manifest.fetch_policy) != "listing":
        return result
    text = decode_body(result.bundle)
    unlisted = await asyncio.to_thread(block_class_of, manifest.status_code, manifest.headers.response, text)
    if unlisted != "ok":
        return result
    bundle = result.bundle.model_copy(update={"manifest": manifest.model_copy(update={"block_class": "ok"})})
    return result.model_copy(update={"bundle": bundle})


async def _better(retry: FetchResult, result: FetchResult, needs_render: RenderCheck | None) -> bool:
    """Whether the browser's `retry` is kept over the HTTP `result`: it is `ok` and, when HTTP was `ok` too, it holds
    what HTTP lacked (`needs_render` asked of it over `result`)."""
    if retry.block_class != "ok":
        return False
    return result.block_class != "ok" or needs_render is None or not await needs_render(retry, result)


async def _admitted(admit_next: Admit | None, *, after: timedelta = timedelta(0)) -> bool:
    """Whether a further request of the fetch may go: `admit_next` waits for its turn, after the pause `after` the site
    asked for, or refuses one too far off. Without `admit_next` nothing is waited for (a caller that keeps no rate)."""
    if admit_next is None:
        return True
    return await (admit_next(after=after) if after else admit_next())


def _browser_may_pass(result: FetchResult) -> bool:
    return (result.block_class in _BROWSER_EVIDENCE and not slow_down(result)) or _unanswered(result)


def _unanswered(result: FetchResult) -> bool:
    error = result.attempts[-1].error
    return result.block_class == "error" and error is not None and error.startswith(_UNANSWERED)


def slow_down(result: FetchResult) -> bool:
    # A 429 or 503 asks for fewer requests (RFC 6585 §4, RFC 9110 §15.6.4): another rung would be one more, inside
    # the backoff the politeness step is about to apply.
    return result.bundle.manifest.status_code in SLOW_DOWN


def with_attempts(result: FetchResult, attempts: tuple[AttemptRecord, ...], duration_ms: int) -> FetchResult:
    manifest = result.bundle.manifest
    fetch_policy = policy_with_attempts(manifest.fetch_policy, attempts)
    bundle = result.bundle.model_copy(update={"manifest": manifest.model_copy(update={"fetch_policy": fetch_policy})})
    return result.model_copy(update={"bundle": bundle, "duration_ms": duration_ms, "attempts": attempts})


def remembered_as(kind: PageKind | None) -> PageKind:
    """The page kind whose remembered method a fetch of `kind` reads and writes (D-1380). A fetch with no page kind is
    classified as a detail page is (`classify` applies the listing rule to listings only), so it shares the detail
    pages' memory."""
    return kind or "detail"


async def remembered_method(conn: AsyncConnection, site_id: SiteId, kind: PageKind | None) -> FetchMethod:
    """The method remembered for the site's pages of `kind` (`remembered_as`): `http` when none is (acquisition
    spec)."""
    query = select(SiteFetchMethod.method).where(
        SiteFetchMethod.site_id == site_id, SiteFetchMethod.page_kind == remembered_as(kind)
    )
    method: FetchMethod | None = (await conn.execute(query)).scalar_one_or_none()
    return method or "http"


async def remember_fetch_method(conn: AsyncConnection, site_id: SiteId, result: FetchResult) -> None:
    """Remember `browser` for the site's pages of the kind `result` was fetched as when it kept a browser `ok` over an
    HTTP attempt of the same fetch: HTTP failed (a shell or a block), or HTTP was `ok` but lacked what the caller reads
    (D-1260, owner #49, #54), so the site's later fetches of that kind go straight to the browser instead of paying
    for both; its other kind keeps its own memory (D-1380). In `auto`, a kept browser outcome follows an HTTP attempt
    only on that evidence (`_page`). Only the re-check (`crawlerai.scheduler.recheck`) sets it back to `http`, so
    `checked_at` starts its clock here. A browser `ok` that opened a site session leaves the kind on HTTP (D-1353): its
    later fetches pass over HTTP with the session's cookies, and when the session ends the next refusal is solved in
    the browser again."""
    fetch_policy = result.bundle.manifest.fetch_policy
    # Only `auto` renders on evidence: a browser fetch asked for (`method_hint`) is no evidence about HTTP, even beside
    # an HTTP attempt of a recipe's page request.
    by_evidence = fetch_policy.get("method_hint") == "auto"
    by_http = any(a.method == "http" for a in result.attempts)
    handed_off = any(a.site_session for a in result.attempts)
    if result.method != "browser" or result.block_class != "ok" or not by_evidence or not by_http or handed_off:
        return
    row = {"site_id": site_id, "page_kind": remembered_as(fetched_as(fetch_policy)), "method": "browser"}
    insert = pg_insert(SiteFetchMethod).values(**row, checked_at=func.now())
    await conn.execute(
        insert.on_conflict_do_update(
            index_elements=[SiteFetchMethod.site_id, SiteFetchMethod.page_kind],
            set_={"method": "browser", "checked_at": func.now()},
            where=SiteFetchMethod.method != "browser",
        )
    )
