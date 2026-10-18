"""Rung selection (SPEC-02 §4.4): which rungs a fetch tries, which outcome it keeps, and what it records.

The rungs are stubs answering synthetic outcomes; no network.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from crawlerai.acquire.rungs import Rungs, acquire
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import FetchMethod
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/item/1"
SHELL = b"<html><body><div id='app'></div></body></html>"
PAGE = b"<html><body><h1>Item</h1></body></html>"
# A status for each outcome a rung can report.
STATUS: dict[BlockClass, int] = {"ok": 200, "shell": 200, "blocked": 403, "not_found": 404, "error": 500}
BLOCK_CLASSES: tuple[BlockClass, ...] = ("ok", "blocked", "shell", "not_found", "error")
OVERRIDE = FetchPolicy(respect_robots=False, robots_override_reason="the site's operator asked for it")


@dataclass
class Rung:
    """Answers every URL with `block_class` (and `status`, when given) in 1 ms, and records the calls it got."""

    method: CaptureMethod
    block_class: BlockClass
    status: int | None = None
    calls: list[tuple[str, FetchPolicy]] = field(default_factory=list)
    body: bytes | None = None  # PAGE for `ok`, else SHELL, by default
    headers: tuple[tuple[str, str], ...] = ()
    retry_after: timedelta | None = None
    error: str | None = None

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append((url, policy))
        status = STATUS[self.block_class] if self.status is None else self.status
        body = self.body if self.body is not None else PAGE if self.block_class == "ok" else SHELL
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            method=self.method,
            status_code=status,
            block_class=self.block_class,
            headers=Headers(request=(), response=self.headers),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(body),
            network_bodies=(),
            fetch_policy=policy.model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(
            method=self.method,
            status=status,
            block_class=self.block_class,
            duration_ms=1,
            retry_after=self.retry_after,
            error=self.error,
        )
        bundle = CaptureBundle(manifest=manifest, body=body, network=())
        return FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))


@dataclass
class Web:
    http: Rung
    browser: Rung

    recipe: Rung | None = None

    def acquire(self, policy: FetchPolicy | None = None, remembered: FetchMethod = "http") -> FetchResult:
        rungs = Rungs(http=self.http, browser=self.browser)
        return asyncio.run(acquire(URL, policy or FetchPolicy(), remembered, rungs, recipe=self.recipe))


def web(
    http: BlockClass,
    browser: BlockClass = "ok",
    *,
    http_status: int | None = None,
    recipe: BlockClass | None = None,
    recipe_status: int | None = None,
) -> Web:
    api = None if recipe is None else Rung("api", recipe, recipe_status)
    return Web(Rung("http", http, http_status), Rung("browser", browser), api)


def _attempts(result: FetchResult) -> list[tuple[CaptureMethod, BlockClass]]:
    return [(attempt.method, attempt.block_class) for attempt in result.attempts]


def test_a_shell_or_block_over_http_is_retried_in_the_browser_and_its_ok_kept() -> None:
    http: BlockClass = "shell"
    stubs = web(http, "ok")

    result = stubs.acquire(OVERRIDE)

    assert (result.method, result.block_class, result.bundle.body) == ("browser", "ok", PAGE)
    assert _attempts(result) == [("http", http), ("browser", "ok")]
    assert stubs.browser.calls == [(URL, OVERRIDE)]
    assert result.duration_ms == 2  # both rungs' time


def test_the_bundle_records_every_attempt_beside_its_policy() -> None:
    result = web("shell", "ok").acquire()

    assert result.bundle.manifest.fetch_policy == {
        **FetchPolicy().model_dump(mode="json"),
        "attempts": [
            {
                "method": "http",
                "status": 200,
                "block_class": "shell",
                "duration_ms": 1,
                "error": None,
                "challenge": None,
                "steps": [],
            },
            {
                "method": "browser",
                "status": 200,
                "block_class": "ok",
                "duration_ms": 1,
                "error": None,
                "challenge": None,
                "steps": [],
            },
        ],
    }


# --- the API recipe rung (SPEC-09 §4.8, §4.10) ------------------------------------------------------------------------


# --- owner #49: the browser for an HTTP `ok` page the caller finds lacking --------------------------------------------


@dataclass
class Lacking:
    """A `needs_render` check that finds the captures of `methods` lacking, recording each one it was asked about."""

    methods: tuple[CaptureMethod, ...] = ()
    asked: list[CaptureMethod] = field(default_factory=list)

    async def __call__(self, result: FetchResult, _over: FetchResult | None = None) -> bool:
        self.asked.append(result.method)
        return result.method in self.methods


def _acquire_checked(stubs: Web, check: Lacking, policy: FetchPolicy | None = None) -> FetchResult:
    rungs = Rungs(http=stubs.http, browser=stubs.browser)
    return asyncio.run(acquire(URL, policy or FetchPolicy(), "http", rungs, needs_render=check))


def test_an_ok_page_lacking_what_the_caller_reads_is_rendered_and_the_render_kept_when_it_holds_it() -> None:
    stubs = web("ok", "ok")

    result = _acquire_checked(stubs, Lacking(("http",)))

    assert (result.method, result.block_class) == ("browser", "ok")
    assert _attempts(result) == [("http", "ok"), ("browser", "ok")]
    assert result.duration_ms == 2


# --- D-1261: an HTTP listing shell kept for want of a browser outcome is the fetch's last page ---


# --- D-1263: a 503 interstitial gets one browser attempt after the site's pause ---
