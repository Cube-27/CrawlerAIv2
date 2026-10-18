"""Rung selection (SPEC-02 §4.4): which rungs a fetch tries, which outcome it keeps, and what it records.

The rungs are stubs answering synthetic outcomes; no network.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.politeness import BACKOFF_MAX
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


def test_a_site_that_answers_over_http_is_fetched_over_http_only() -> None:
    stubs = web("ok")

    result = stubs.acquire()

    assert (result.method, result.block_class, result.bundle.body) == ("http", "ok", PAGE)
    assert _attempts(result) == [("http", "ok")]
    assert stubs.browser.calls == []


def test_a_shell_or_block_over_http_is_retried_in_the_browser_and_its_ok_kept() -> None:
    http: BlockClass = "shell"
    stubs = web(http, "ok")

    result = stubs.acquire(OVERRIDE)

    assert (result.method, result.block_class, result.bundle.body) == ("browser", "ok", PAGE)
    assert _attempts(result) == [("http", http), ("browser", "ok")]
    assert stubs.browser.calls == [(URL, OVERRIDE)]
    assert result.duration_ms == 2  # both rungs' time


def test_the_http_outcome_is_kept_when_the_browser_does_no_better() -> None:
    browser: BlockClass = "blocked"
    stubs = web("shell", browser)

    result = stubs.acquire()

    assert (result.method, result.block_class, result.bundle.body) == ("http", "shell", SHELL)
    assert _attempts(result) == [("http", "shell"), ("browser", browser)]


def test_a_request_to_slow_down_is_not_retried_in_the_browser() -> None:
    status = 429
    stubs = web("blocked", http_status=status)

    result = stubs.acquire()

    assert (result.method, result.bundle.manifest.status_code) == ("http", status)
    assert _attempts(result) == [("http", "blocked")]
    assert stubs.browser.calls == []


def test_a_missing_page_or_an_error_is_not_retried_in_the_browser() -> None:
    stubs = web("not_found")

    result = stubs.acquire()

    assert _attempts(result) == [("http", "not_found")]
    assert stubs.browser.calls == []


def test_a_network_error_over_http_is_retried_in_the_browser_and_its_ok_kept() -> None:
    stubs = Web(Rung("http", "error", error="network_error: curl 92"), Rung("browser", "ok"))

    result = stubs.acquire()

    assert (result.method, result.block_class, result.bundle.body) == ("browser", "ok", PAGE)
    assert _attempts(result) == [("http", "error"), ("browser", "ok")]


@pytest.mark.parametrize("error", ["timeout", "body_cap", "decode_error", "ssrf_rejected", None])
def test_an_error_other_than_a_network_error_is_not_retried_in_the_browser(error: str | None) -> None:
    stubs = Web(Rung("http", "error", error=error), Rung("browser", "ok"))

    result = stubs.acquire()

    assert _attempts(result) == [("http", "error")]
    assert stubs.browser.calls == []


def test_a_network_error_whose_render_fails_keeps_the_http_error() -> None:
    stubs = Web(Rung("http", "error", error="network_error: curl 92"), Rung("browser", "blocked"))

    result = stubs.acquire()

    assert (result.method, result.block_class, result.attempts[0].error) == ("http", "error", "network_error: curl 92")
    assert _attempts(result) == [("http", "error"), ("browser", "blocked")]


def test_a_site_remembered_as_browser_goes_straight_to_the_browser() -> None:
    stubs = web("ok", "shell")

    result = stubs.acquire(remembered="browser")

    assert _attempts(result) == [("browser", "shell")]
    assert stubs.http.calls == []


@pytest.mark.parametrize("remembered", ["http", "browser"])
def test_a_method_hint_overrides_the_remembered_method_and_never_falls_back(remembered: FetchMethod) -> None:
    stubs = web("shell", "shell")

    over_http = stubs.acquire(FetchPolicy(method_hint="http"), remembered)
    in_browser = stubs.acquire(FetchPolicy(method_hint="browser"), remembered)

    assert _attempts(over_http) == [("http", "shell")]
    assert _attempts(in_browser) == [("browser", "shell")]


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


Hint = Literal["auto", "http", "browser"]


@given(
    hint=st.sampled_from(["auto", "http", "browser"]),
    remembered=st.sampled_from(["http", "browser"]),
    http=st.sampled_from(BLOCK_CLASSES),
    browser=st.sampled_from(BLOCK_CLASSES),
)
def test_each_rung_runs_at_most_once_and_an_ok_attempt_is_always_kept(
    hint: Hint, remembered: FetchMethod, http: BlockClass, browser: BlockClass
) -> None:
    stubs = web(http, browser)

    result = stubs.acquire(FetchPolicy(method_hint=hint), remembered)

    methods = [attempt.method for attempt in result.attempts]
    assert len(methods) == len(set(methods))
    assert (len(stubs.http.calls), len(stubs.browser.calls)) == (methods.count("http"), methods.count("browser"))
    kept = (result.method, result.block_class)
    assert kept in _attempts(result)
    if any(attempt.block_class == "ok" for attempt in result.attempts):
        assert result.block_class == "ok"


# --- the API recipe rung (SPEC-09 §4.8, §4.10) ------------------------------------------------------------------------


def test_a_page_with_a_recipe_is_served_by_it_and_no_other_rung() -> None:
    stubs = web("ok", "ok", recipe="ok")

    result = stubs.acquire(remembered="browser")

    assert (result.method, result.block_class) == ("api", "ok")
    assert _attempts(result) == [("api", "ok")]
    assert (len(stubs.http.calls), len(stubs.browser.calls)) == (0, 0)


def test_a_failed_recipe_falls_back_to_the_configured_method_and_every_attempt_is_recorded() -> None:
    failed: BlockClass = "not_found"
    result = web("shell", "ok", recipe=failed).acquire()

    assert (result.method, result.block_class) == ("browser", "ok")
    assert _attempts(result) == [("api", failed), ("http", "shell"), ("browser", "ok")]
    recorded = result.bundle.manifest.fetch_policy["attempts"]
    assert isinstance(recorded, list)
    assert [attempt["method"] for attempt in recorded if isinstance(attempt, dict)] == ["api", "http", "browser"]
    assert result.duration_ms == 3


def test_a_recipe_asked_to_slow_down_is_kept_without_a_fallback() -> None:
    stubs = web("ok", recipe="blocked", recipe_status=503)

    result = stubs.acquire()

    assert _attempts(result) == [("api", "blocked")]
    assert len(stubs.http.calls) == 0


def _acquire_admitting(
    http: BlockClass, recipe: BlockClass | None = None, *, admits: bool = True
) -> tuple[list[str], FetchResult]:
    """`acquire` in auto with an `admit_next` that logs, alongside the rungs, when it runs, and answers `admits`."""
    log: list[str] = []

    async def admit_next(*, after: timedelta = timedelta(0)) -> bool:
        log.append("admit")
        return admits

    def logged(rung: Rung) -> Callable[[str, FetchPolicy], Awaitable[FetchResult]]:
        async def fetch(url: str, policy: FetchPolicy) -> FetchResult:
            log.append(rung.method)
            return await rung(url, policy)

        return fetch

    rungs = Rungs(http=logged(Rung("http", http)), browser=logged(Rung("browser", "ok")))
    api = None if recipe is None else logged(Rung("api", recipe))
    result = asyncio.run(acquire(URL, FetchPolicy(), "http", rungs, recipe=api, admit_next=admit_next))
    return log, result


@pytest.mark.parametrize("http", ["shell", "blocked"])
def test_the_browser_retry_waits_for_its_admission(http: BlockClass) -> None:
    log, result = _acquire_admitting(http)
    assert log == ["http", "admit", "browser"]
    assert result.method == "browser"


def test_the_page_after_a_failed_recipe_waits_for_its_admission() -> None:
    log, result = _acquire_admitting("ok", recipe="not_found")
    assert log == ["api", "admit", "http"]
    assert result.method == "http"


@pytest.mark.parametrize("recipe", [None, "ok"])
def test_a_fetch_of_one_request_asks_no_admission(recipe: BlockClass | None) -> None:
    log, _ = _acquire_admitting("ok", recipe=recipe)
    assert log == ["api" if recipe else "http"]


def test_a_browser_retry_not_admitted_in_time_is_skipped_and_the_http_outcome_kept() -> None:
    log, result = _acquire_admitting("shell", admits=False)

    assert log == ["http", "admit"]
    assert (result.method, result.block_class) == ("http", "shell")


def test_a_page_after_a_failed_recipe_not_admitted_in_time_keeps_the_recipe_outcome() -> None:
    log, result = _acquire_admitting("ok", recipe="not_found", admits=False)

    assert log == ["api", "admit"]
    assert (result.method, result.block_class) == ("api", "not_found")


# --- owner #49: the browser for an HTTP `ok` page the caller finds lacking --------------------------------------------


@dataclass
class Lacking:
    """A `needs_render` check that finds the captures of `methods` lacking, recording each one it was asked about."""

    methods: tuple[CaptureMethod, ...] = ()
    asked: list[CaptureMethod] = field(default_factory=list)

    async def __call__(self, result: FetchResult) -> bool:
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


@pytest.mark.parametrize(
    ("browser", "lacking"),
    [
        pytest.param("ok", ("http", "browser"), id="render-lacks-it-too"),
        pytest.param("blocked", ("http",), id="blocked"),
    ],
)
def test_the_http_page_is_kept_when_the_render_does_no_better(
    browser: BlockClass, lacking: tuple[CaptureMethod, ...]
) -> None:
    stubs = web("ok", browser)

    result = _acquire_checked(stubs, Lacking(lacking))

    assert (result.method, result.block_class) == ("http", "ok")
    assert _attempts(result) == [("http", "ok"), ("browser", browser)]


def test_an_ok_page_the_caller_finds_complete_is_not_rendered() -> None:
    stubs = web("ok")

    result = _acquire_checked(stubs, Lacking())

    assert _attempts(result) == [("http", "ok")]
    assert stubs.browser.calls == []


@pytest.mark.parametrize("hint", ["http", "browser"])
def test_only_auto_renders_a_lacking_page(hint: Literal["http", "browser"]) -> None:
    stubs = web("ok")
    check = Lacking(("http",))

    result = _acquire_checked(stubs, check, FetchPolicy(method_hint=hint))

    assert [a.method for a in result.attempts] == [hint]


def test_a_not_modified_answer_is_neither_checked_nor_rendered() -> None:
    stubs = web("ok", http_status=304)
    check = Lacking(("http",))

    result = _acquire_checked(stubs, check)

    assert _attempts(result) == [("http", "ok")]
    assert check.asked == []


# --- D-1261: an HTTP listing shell kept for want of a browser outcome is the fetch's last page ---

_HTML = (("content-type", "text/html"),)
# A listing page with the site's structure (text and links) but no repeated items: a shell by the listing rule alone.
_UNLISTED = (
    "<html><body><main><h1>Catalogue</h1><p>"
    + "Synthetic catalogue text. " * 20
    + "</p>"
    + "".join(f'<a href="/about/{i}">About {i}</a>' for i in range(6))
    + "</main></body></html>"
).encode()
LISTING = FetchPolicy(page_kind="listing")


def _listing_shell(body: bytes = _UNLISTED) -> Rung:
    return Rung("http", "shell", body=body, headers=_HTML)


@pytest.mark.parametrize("browser", ["blocked", "error", "shell"])
def test_a_listing_shell_whose_render_fails_is_kept_as_an_ok_page_to_extract(browser: BlockClass) -> None:
    stubs = Web(_listing_shell(), Rung("browser", browser))

    result = stubs.acquire(LISTING)

    assert (result.method, result.block_class, result.bundle.body) == ("http", "ok", _UNLISTED)
    assert _attempts(result) == [("http", "shell"), ("browser", browser)]  # the attempt keeps what HTTP said


def test_a_listing_shell_whose_render_is_not_admitted_is_kept_as_an_ok_page() -> None:
    rungs = Rungs(http=_listing_shell(), browser=Rung("browser", "ok"))

    async def refuse(*, after: timedelta = timedelta(0)) -> bool:
        return False

    result = asyncio.run(acquire(URL, LISTING, "http", rungs, admit_next=refuse))

    assert (result.method, result.block_class) == ("http", "ok")
    assert _attempts(result) == [("http", "shell")]


def test_a_listing_shell_whose_render_passes_keeps_the_render() -> None:
    stubs = Web(_listing_shell(), Rung("browser", "ok"))

    result = stubs.acquire(LISTING)

    assert (result.method, result.block_class) == ("browser", "ok")


@pytest.mark.parametrize(
    ("body", "policy"),
    [
        pytest.param(SHELL, LISTING, id="no-site-structure"),
        pytest.param(_UNLISTED, FetchPolicy(), id="not-fetched-as-a-listing"),
    ],
)
def test_a_shell_without_site_structure_or_outside_a_listing_stays_a_shell(body: bytes, policy: FetchPolicy) -> None:
    stubs = Web(_listing_shell(body), Rung("browser", "blocked"))

    result = stubs.acquire(policy)

    assert (result.method, result.block_class) == ("http", "shell")


# --- D-1263: a 503 interstitial gets one browser attempt after the site's pause ---

# A refusal standing in for the page: no site structure, and a script that may navigate on.
_CHALLENGE = b"<html><head><script src='/check.js'></script></head><body><p>One moment.</p></body></html>"
# A static refusal: nothing on it can navigate.
_STATIC = b"<html><body><p>Service unavailable.</p></body></html>"


def _acquire_slowed(
    status: int, body: bytes, retry_after: timedelta | None, *, admits: bool = True
) -> tuple[list[timedelta], Rung, FetchResult]:
    pauses: list[timedelta] = []

    async def admit_next(*, after: timedelta = timedelta(0)) -> bool:
        pauses.append(after)
        return admits

    http = Rung("http", "blocked", status, body=body, headers=_HTML, retry_after=retry_after)
    browser = Rung("browser", "ok")
    result = asyncio.run(acquire(URL, FetchPolicy(), "http", Rungs(http=http, browser=browser), admit_next=admit_next))
    return pauses, browser, result


@pytest.mark.parametrize(
    ("retry_after", "pause"),
    [(timedelta(seconds=7), timedelta(seconds=7)), (None, timedelta(seconds=30))],
)
def test_a_503_interstitial_is_rendered_once_after_its_retry_after_or_the_first_backoff(
    retry_after: timedelta | None, pause: timedelta
) -> None:
    pauses, browser, result = _acquire_slowed(503, _CHALLENGE, retry_after)

    assert pauses == [pause]
    assert len(browser.calls) == 1
    assert (result.method, result.block_class) == ("browser", "ok")
    assert _attempts(result) == [("http", "blocked"), ("browser", "ok")]


def test_a_503_interstitial_whose_pause_is_not_admitted_keeps_the_503() -> None:
    # A pause past the longest backoff is asked as the longest, which no caller waits for in place.
    pauses, browser, result = _acquire_slowed(503, _CHALLENGE, timedelta(hours=1), admits=False)

    assert pauses == [BACKOFF_MAX]
    assert browser.calls == []
    assert result.bundle.manifest.status_code == 503


@pytest.mark.parametrize(
    ("status", "body"),
    [pytest.param(503, _STATIC, id="static-503"), pytest.param(429, _CHALLENGE, id="429")],
)
def test_a_static_503_or_any_429_gets_no_browser_attempt(status: int, body: bytes) -> None:
    pauses, browser, result = _acquire_slowed(status, body, None)

    assert (pauses, browser.calls) == ([], [])
    assert result.bundle.manifest.status_code == status
