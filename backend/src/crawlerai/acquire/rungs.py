"""Rung selection (SPEC-02 §4.4, ARCHITECTURE §7.1): HTTP by default, the browser on evidence, and the method that
worked remembered in `site.fetch_method`.

A URL an active adapter detects goes to that adapter (`crawlerai.adapters`) first, and to the page rungs when the
adapter does not serve it (SPEC-15 §4.6). A site whose active config has an API recipe is served by the recipe's rung
(SPEC-09 §4.8), which the caller binds to the recipe: the config IR sits above `acquire` (`.importlinter`). The browser
rung is `crawlerai.acquire.browser.fetch_browser`. Every rung is a function of (url, policy), so `acquire` decides and
records only. The one exception is the HTTP rung's conditional form, which also takes the validators a page last
answered with (SPEC-11 §4.2).
"""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.api import JsonFetcher
from crawlerai.acquire.politeness import SLOW_DOWN, Admit
from crawlerai.acquire.types import (
    AttemptRecord,
    BlockClass,
    FetchPolicy,
    FetchResult,
    Validators,
    policy_with_attempts,
)
from crawlerai.adapters.registry import Registry, platform_adapters
from crawlerai.db.models import FetchMethod, Site, SiteId

Rung = Callable[[str, FetchPolicy], Awaitable[FetchResult]]


class ConditionalRung(Protocol):
    """The HTTP rung sending `validators` (`crawlerai.acquire.http.fetch_http`)."""

    def __call__(self, url: str, policy: FetchPolicy, *, validators: Validators | None) -> Awaitable[FetchResult]: ...


# ARCHITECTURE §7.1: the HTTP outcomes that are evidence for the browser, which may pass where HTTP did not.
_BROWSER_EVIDENCE: frozenset[BlockClass] = frozenset({"shell", "blocked"})


@dataclass(frozen=True)
class Rungs:
    http: Rung
    browser: Rung
    adapters: Registry = field(default_factory=lambda: Registry((), active=()))
    # The HTTP rung in its conditional form, for fetches given validators; without it they are sent nowhere.
    conditional: ConditionalRung | None = None
    # JSON over HTTP (`acquire.api.fetch_json`), which an active config's API recipe sends its request with
    # (SPEC-09 §4.8); without it no recipe serves a page.
    json: JsonFetcher | None = None


def adapter_registry(disabled: Collection[str]) -> Registry:
    """The registry of every platform adapter, all running but the `disabled` ones (SPEC-15 §4.8), for the processes
    that fetch; it raises `ValueError` for a name no adapter has. One per process: it remembers the hosts its adapters
    declined."""
    adapters = platform_adapters()
    names = {adapter.name for adapter in adapters}
    if unknown := sorted(set(disabled) - names):
        raise ValueError(f"no adapter named {unknown}")
    return Registry(adapters, names - set(disabled))


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
) -> FetchResult:
    """Fetch `url` through the active adapter that detects it, if any, requesting its API with `send` (no adapter runs
    without it); a page an adapter does not serve skips the recipe (SPEC-15 §4.6). Otherwise through `recipe`, the
    active config's API recipe bound to its fetch (SPEC-09 §4.8), when the site has one. The adapter's result is kept
    when it is `ok`, the recipe's when it is `ok` or asks for fewer requests; otherwise the page is fetched as if there
    were neither (§4.10, INV-40). Without either, fetch it with `policy.method_hint`, or else the site's `remembered`
    method. In `auto`, an HTTP shell or block is fetched again in the browser, and the browser's outcome is kept only if
    it is `ok`. Each request after the first (the page after an adapter or a recipe, the browser retry) waits for
    `admit_next` to admit it at the site's rate (SPEC-02 §4.6), and is not sent when `admit_next` refuses it: the fetch
    keeps the outcome it has. The result lists every attempt, in its bundle's manifest too. `validators` go with the
    HTTP rung only (SPEC-11 §4.2): a 304 is `ok` and ends the fetch."""
    served = None if send is None else await rungs.adapters.serve(url, policy, send)
    # An adapter's endpoint is not the page: its slow-down holds back the page only by the pause it put on the host's
    # rate, which `admit_next` waits out (SPEC-15 §4.9). A recipe's may be the page's own (its HTML page request).
    by_recipe = served is None and recipe is not None
    if served is None and recipe is not None:
        served = await recipe(url, policy)
    if served is not None and (
        served.block_class == "ok" or (by_recipe and slow_down(served)) or not await _admitted(admit_next)
    ):
        return served
    kept, attempts, duration_ms = await _page(url, policy, remembered, rungs, validators, admit_next)
    if served is not None:
        attempts, duration_ms = served.attempts + attempts, served.duration_ms + duration_ms
    return with_attempts(kept, attempts, duration_ms)


async def _page(
    url: str,
    policy: FetchPolicy,
    remembered: FetchMethod,
    rungs: Rungs,
    validators: Validators | None,
    admit_next: Admit | None,
) -> tuple[FetchResult, tuple[AttemptRecord, ...], int]:
    """The page over HTTP or in the browser (`acquire`): the outcome kept, every attempt and their duration."""
    method = remembered if policy.method_hint == "auto" else policy.method_hint
    if method == "http" and rungs.conditional is not None:
        result = await rungs.conditional(url, policy, validators=validators)
    else:
        result = await (rungs.http if method == "http" else rungs.browser)(url, policy)
    retried = policy.method_hint == "auto" and method == "http" and _browser_may_pass(result)
    if not retried or not await _admitted(admit_next):
        return result, result.attempts, result.duration_ms
    retry = await rungs.browser(url, policy)
    kept = retry if retry.block_class == "ok" else result
    return kept, result.attempts + retry.attempts, result.duration_ms + retry.duration_ms


async def _admitted(admit_next: Admit | None) -> bool:
    """Whether a further request of the fetch may go: `admit_next` waits for its turn, or refuses one too far off."""
    return admit_next is None or await admit_next()


def _browser_may_pass(result: FetchResult) -> bool:
    return result.block_class in _BROWSER_EVIDENCE and not slow_down(result)


def slow_down(result: FetchResult) -> bool:
    # A 429 or 503 asks for fewer requests (RFC 6585 §4, RFC 9110 §15.6.4): another rung would be one more, inside
    # the backoff the politeness step is about to apply.
    return result.bundle.manifest.status_code in SLOW_DOWN


def with_attempts(result: FetchResult, attempts: tuple[AttemptRecord, ...], duration_ms: int) -> FetchResult:
    manifest = result.bundle.manifest
    fetch_policy = policy_with_attempts(manifest.fetch_policy, attempts)
    bundle = result.bundle.model_copy(update={"manifest": manifest.model_copy(update={"fetch_policy": fetch_policy})})
    return FetchResult(bundle=bundle, duration_ms=duration_ms, attempts=attempts)


async def remember_fetch_method(conn: AsyncConnection, site_id: SiteId, result: FetchResult) -> None:
    """Set the site to `browser` when `result` shows HTTP failing and the browser passing. Only the re-check
    (`crawlerai.scheduler.recheck`) sets it back to `http`, so `fetch_method_checked_at` starts its clock here."""
    http_failed = any(a.method == "http" and a.block_class in _BROWSER_EVIDENCE for a in result.attempts)
    if result.method == "browser" and result.block_class == "ok" and http_failed:
        await conn.execute(
            update(Site)
            .where(Site.id == site_id, Site.fetch_method != "browser")
            .values(fetch_method="browser", fetch_method_checked_at=func.now())
        )
