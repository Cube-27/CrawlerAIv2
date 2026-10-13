"""Rung selection (SPEC-02 §4.4, ARCHITECTURE §7.1): HTTP by default, the browser on evidence, and the method that
worked remembered in `site.fetch_method`.

The adapter and API-recipe rungs come before these once they exist (SPEC-02 PR 8, SPEC-09); the browser rung's
implementation is SPEC-02 PR 6. Every rung is a function of (url, policy), so `acquire` decides and records only.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.politeness import SLOW_DOWN
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult, policy_with_attempts
from crawlerai.db.models import FetchMethod, Site, SiteId

Rung = Callable[[str, FetchPolicy], Awaitable[FetchResult]]

# ARCHITECTURE §7.1: the HTTP outcomes that are evidence for the browser, which may pass where HTTP did not.
_BROWSER_EVIDENCE: frozenset[BlockClass] = frozenset({"shell", "blocked"})


@dataclass(frozen=True)
class Rungs:
    http: Rung
    browser: Rung


async def acquire(url: str, policy: FetchPolicy, remembered: FetchMethod, rungs: Rungs) -> FetchResult:
    """Fetch `url` with `policy.method_hint`, or else the site's `remembered` method. In `auto`, an HTTP shell or
    block is fetched again in the browser, and the browser's outcome is kept only if it is `ok`. The result lists
    every attempt, in its bundle's manifest too."""
    method = remembered if policy.method_hint == "auto" else policy.method_hint
    result = await (rungs.http if method == "http" else rungs.browser)(url, policy)
    kept, attempts, duration_ms = result, result.attempts, result.duration_ms
    if policy.method_hint == "auto" and method == "http" and _browser_may_pass(result):
        retry = await rungs.browser(url, policy)
        if retry.block_class == "ok":
            kept = retry
        attempts, duration_ms = attempts + retry.attempts, duration_ms + retry.duration_ms
    return _with_attempts(kept, attempts, duration_ms)


def _browser_may_pass(result: FetchResult) -> bool:
    # A 429 or 503 asks for fewer requests (RFC 6585 §4, RFC 9110 §15.6.4): another rung would be one more, inside
    # the backoff the politeness step is about to apply.
    return result.block_class in _BROWSER_EVIDENCE and result.bundle.manifest.status_code not in SLOW_DOWN


def _with_attempts(result: FetchResult, attempts: tuple[AttemptRecord, ...], duration_ms: int) -> FetchResult:
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
