"""Rung selection (acquisition spec): which rungs a fetch tries, which outcome it keeps, and what it records.

The rungs are stubs answering synthetic outcomes; no network.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import get_args

from crawlerai.acquire.api import JsonRequest
from crawlerai.acquire.memory import Remembered
from crawlerai.acquire.rungs import BROWSER_MIN_S, Rungs, acquire
from crawlerai.acquire.types import AttemptRecord, FetchPolicy, FetchResult
from crawlerai.adapters.base import AdapterMatch, PageRefs, Shape
from crawlerai.adapters.registry import Registry
from crawlerai.core.capture import BlockClass, CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.db.models import FetchMethod, PageKind
from crawlerai.storage.capture_bundle import CaptureBundle, CaptureManifest, Headers, sha256_hex

URL = "https://shop.example.test/item/1"
SHELL = b"<html><body><div id='app'></div></body></html>"
PAGE = b"<html><body><h1>Item</h1></body></html>"
# A status for each outcome a rung can report.
STATUS: dict[BlockClass, int] = {
    "ok": 200,
    "shell": 200,
    "blocked": 403,
    "not_found": 404,
    "error": 500,
    "auth_wall": 401,
    "soft_404": 200,
    "geo_redirect": 200,
    "redirected_to_listing": 200,
    "unsupported_media": 200,
}
BLOCK_CLASSES: tuple[BlockClass, ...] = ("ok", "blocked", "shell", "not_found", "error")
POLICY = FetchPolicy()


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
    challenge: str | None = None

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
            challenge=self.challenge,
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
        memory = Remembered(remembered)
        return asyncio.run(acquire(URL, policy or FetchPolicy(), memory, rungs, recipe=self.recipe))


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

    result = stubs.acquire(POLICY)

    assert (result.method, result.block_class, result.bundle.body) == ("browser", "ok", PAGE)
    assert _attempts(result) == [("http", http), ("browser", "ok")]
    assert stubs.browser.calls == [(URL, POLICY)]
    assert result.duration_ms == 2  # both rungs' time


def test_an_http_timeout_is_retried_in_the_browser_not_over_http_again() -> None:
    stubs = web("error", "ok")
    stubs.http.error = "timeout"

    result = stubs.acquire(POLICY)

    assert _attempts(result) == [("http", "error"), ("browser", "ok")]
    assert len(stubs.http.calls) == 1


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


# --- the API recipe rung (adapters spec) ------------------------------------------------------------------------


# --- acquisition spec "Browser on block or by field source": never for an HTTP `ok` page ----------------------------

# Whether an `auto` fetch retries each HTTP outcome in the browser (the a.3 table): a block, a shell (a challenge's or
# a script-only document's), an unanswered request; never an `ok` page, a 4xx class, a redirect class or a non-HTML
# answer.
RETRIED: dict[tuple[BlockClass, str | None], bool] = {
    ("ok", None): False,
    ("blocked", None): True,
    ("shell", None): True,
    ("error", "network_error: curl 92"): True,
    ("error", "timeout"): True,
    ("error", "http_error"): False,
    ("not_found", None): False,
    ("auth_wall", None): False,
    ("soft_404", None): False,
    ("geo_redirect", None): False,
    ("redirected_to_listing", None): False,
    ("unsupported_media", None): False,
}


def test_the_browser_is_tried_exactly_for_the_block_classes_of_the_table() -> None:
    assert {block_class for block_class, _ in RETRIED} == set(get_args(BlockClass))
    for (block_class, error), retried in RETRIED.items():
        for kind in ("detail", "listing"):
            stubs = web(block_class, "ok")
            stubs.http.error = error
            # The `ok` page states no JSON-LD, Open Graph tag or price (`PAGE`): still no render.
            stubs.acquire(FetchPolicy(page_kind=kind))
            assert bool(stubs.browser.calls) is retried, (block_class, error, kind)


def test_no_browser_retry_starts_too_close_to_the_deadline() -> None:
    stubs = web("shell", "ok")
    rungs = Rungs(http=stubs.http, browser=stubs.browser)
    deadline = time.monotonic() + BROWSER_MIN_S - 1

    result = asyncio.run(acquire(URL, FetchPolicy(), Remembered(), rungs, deadline=deadline))

    assert (result.method, stubs.browser.calls) == ("http", [])


# --- D-1261: an HTTP listing shell kept for want of a browser outcome is the fetch's last page ---


def test_the_last_rungs_shell_no_challenge_names_is_the_page() -> None:
    # Owner decision 2026-10-23: the browser's short page with no challenge is `ok`; one a challenge names is not, and
    # then the HTTP shell is kept as it is, not the last rung's page.
    shown = web("shell", "shell").acquire()
    challenged = web("shell", "shell")
    challenged.browser.challenge = "vendor"
    refused = challenged.acquire()
    # HTTP is the last rung when no browser attempt is made.
    http_only = web("shell", "ok").acquire(FetchPolicy(method_hint="http"))

    assert (shown.method, shown.block_class) == ("browser", "ok")
    assert _attempts(shown) == [("http", "shell"), ("browser", "shell")]
    assert (refused.method, refused.block_class) == ("http", "shell")
    assert (http_only.method, http_only.block_class) == ("http", "ok")


# --- D-1263: a 503 interstitial gets one browser attempt after the site's pause ---


# --- owner decision 2026-10-23: an HTTP 429 gets one browser attempt after the pause it asks for ---


def test_a_429_is_answered_once_in_the_browser_after_its_pause() -> None:
    stubs = web("blocked", "ok", http_status=429)
    stubs.http.retry_after = timedelta(seconds=7)
    pauses: list[timedelta] = []

    async def admit(*, after: timedelta = timedelta(0)) -> bool:
        pauses.append(after)
        return after <= timedelta(minutes=1)  # a caller waits in place this long at most

    rungs = Rungs(http=stubs.http, browser=stubs.browser)
    result = asyncio.run(acquire(URL, POLICY, Remembered(), rungs, admit_next=admit))

    assert _attempts(result) == [("http", "blocked"), ("browser", "ok")]
    assert pauses == [timedelta(seconds=7)]
    # A pause longer than the caller waits sends nothing more: the 429 is kept.
    stubs = web("blocked", "ok", http_status=429)
    stubs.http.retry_after = timedelta(minutes=5)
    rungs = Rungs(http=stubs.http, browser=stubs.browser)
    result = asyncio.run(acquire(URL, POLICY, Remembered(), rungs, admit_next=admit))
    assert (_attempts(result), stubs.browser.calls) == ([("http", "blocked")], [])


# --- adapters spec "Referral from a tenant's own host": a shell asks its referral before the render ---------------

PLATFORM = "https://jobs.example.test/board"


@dataclass
class Referrer:
    """A referring adapter of the platform at `PLATFORM`, which a page refers to by linking to it."""

    answer: Rung = field(default_factory=lambda: Rung("api", "ok"))
    name: str = "referrer"

    def detect(self, url: str) -> AdapterMatch | None:
        return AdapterMatch(tenant="board", page_kind="listing") if url == PLATFORM else None

    def serves(self, match: AdapterMatch, endpoint: str) -> bool:
        return True

    async def fetch(self, url: str, policy: FetchPolicy, send: object) -> FetchResult:
        return await self.answer(url, policy)

    def shapes(self, match: AdapterMatch, answer: object, /) -> tuple[Shape, ...]:
        return ()

    def referred(self, refs: PageRefs, kind: PageKind | None, types: tuple[str, ...], /) -> str | None:
        return PLATFORM if PLATFORM in refs.links else None


async def _unsent(request: JsonRequest, policy: FetchPolicy) -> FetchResult:
    raise AssertionError("the adapter stub sends nothing")


def test_a_script_only_shell_asks_its_referral_before_the_render() -> None:
    for challenge, rendered in ((None, False), ("structural", True)):
        stubs = web("shell", "ok")
        stubs.http.body = f"<html><body><div id='app'></div><a href='{PLATFORM}'>Jobs</a></body></html>".encode()
        stubs.http.challenge = challenge
        referrer = Referrer()
        rungs = Rungs(http=stubs.http, browser=stubs.browser, adapters=Registry([referrer]))

        result = asyncio.run(acquire(URL, POLICY, Remembered(), rungs, send=_unsent))

        assert bool(stubs.browser.calls) is rendered, challenge
        if not rendered:  # the referral serves the page: no render is paid for
            assert _attempts(result) == [("http", "shell"), ("api", "ok")]
            assert referrer.answer.calls == [(PLATFORM, POLICY)]
