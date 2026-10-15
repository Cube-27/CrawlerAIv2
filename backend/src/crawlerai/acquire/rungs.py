"""Rung selection (SPEC-02 §4.4, ARCHITECTURE §7.1): HTTP by default, the browser on evidence, and the method that
worked remembered in `site.fetch_method`.

A URL an active adapter detects goes to that adapter (`crawlerai.adapters`) and no other rung. A site whose active
config has an API recipe is served by the recipe's rung (SPEC-09 §4.8), which the caller binds to the recipe: the
config IR sits above `acquire` (`.importlinter`). The browser rung is `crawlerai.acquire.browser.fetch_browser`.
Every rung is a function of (url, policy), so `acquire` decides and records only. The one exception is the HTTP rung's
conditional form, which also takes the validators a page last answered with (SPEC-11 §4.2).
"""

from collections.abc import Awaitable, Callable
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
from crawlerai.adapters.registry import Registry
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


async def acquire(
    url: str,
    policy: FetchPolicy,
    remembered: FetchMethod,
    rungs: Rungs,
    *,
    recipe: Rung | None = None,
    validators: Validators | None = None,
    admit_next: Admit | None = None,
) -> FetchResult:
    """Fetch `url` through the active adapter that detects it, if any. Otherwise through `recipe`, the active config's
    API recipe bound to its fetch (SPEC-09 §4.8), when the site has one: its result is kept when it is `ok` or asks
    for fewer requests, and otherwise the page is fetched as if there were no recipe (§4.10). Without a recipe, fetch
    it with `policy.method_hint`, or else the site's `remembered` method. In `auto`, an HTTP shell or block is fetched
    again in the browser, and the browser's outcome is kept only if it is `ok`. Each request after the first (the
    page after a recipe, the browser retry) waits for `admit_next` to admit it at the site's rate (SPEC-02 §4.6). The
    result lists every attempt, in its bundle's manifest too. `validators` go with the HTTP rung only (SPEC-11 §4.2):
    a 304 is `ok` and ends the fetch."""
    if (adapter := rungs.adapters.detect(url)) is not None:
        return await adapter.fetch(url, policy)
    served: FetchResult | None = None
    if recipe is not None:
        served = await recipe(url, policy)
        if served.block_class == "ok" or slow_down(served):
            return served
        if admit_next is not None:
            await admit_next()
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
    kept, attempts, duration_ms = result, result.attempts, result.duration_ms
    if policy.method_hint == "auto" and method == "http" and _browser_may_pass(result):
        if admit_next is not None:
            await admit_next()
        retry = await rungs.browser(url, policy)
        if retry.block_class == "ok":
            kept = retry
        attempts, duration_ms = attempts + retry.attempts, duration_ms + retry.duration_ms
    return kept, attempts, duration_ms


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
