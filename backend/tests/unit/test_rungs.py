"""Rung selection (SPEC-02 §4.4): which rungs a fetch tries, which outcome it keeps, and what it records.

The rungs are stubs answering synthetic outcomes; no network.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

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

    async def __call__(self, url: str, policy: FetchPolicy) -> FetchResult:
        self.calls.append((url, policy))
        status = STATUS[self.block_class] if self.status is None else self.status
        body = PAGE if self.block_class == "ok" else SHELL
        manifest = CaptureManifest(
            capture_id=uuid7(),
            url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            method=self.method,
            status_code=status,
            block_class=self.block_class,
            headers=Headers(request=(), response=()),
            timings_ms={"total": 1},
            html_sha256=sha256_hex(body),
            network_bodies=(),
            fetch_policy=policy.model_dump(mode="json"),
            engine_version="test",
        )
        attempt = AttemptRecord(method=self.method, status=status, block_class=self.block_class, duration_ms=1)
        bundle = CaptureBundle(manifest=manifest, body=body, network=())
        return FetchResult(bundle=bundle, duration_ms=1, attempts=(attempt,))


@dataclass
class Web:
    http: Rung
    browser: Rung

    def acquire(self, policy: FetchPolicy | None = None, remembered: FetchMethod = "http") -> FetchResult:
        rungs = Rungs(http=self.http, browser=self.browser)
        return asyncio.run(acquire(URL, policy or FetchPolicy(), remembered, rungs))


def web(http: BlockClass, browser: BlockClass = "ok", *, http_status: int | None = None) -> Web:
    return Web(Rung("http", http, http_status), Rung("browser", browser))


def _attempts(result: FetchResult) -> list[tuple[CaptureMethod, BlockClass]]:
    return [(attempt.method, attempt.block_class) for attempt in result.attempts]


def test_a_site_that_answers_over_http_is_fetched_over_http_only() -> None:
    stubs = web("ok")

    result = stubs.acquire()

    assert (result.method, result.block_class, result.bundle.body) == ("http", "ok", PAGE)
    assert _attempts(result) == [("http", "ok")]
    assert stubs.browser.calls == []


@pytest.mark.parametrize("http", ["shell", "blocked"])
def test_a_shell_or_block_over_http_is_retried_in_the_browser_and_its_ok_kept(http: BlockClass) -> None:
    stubs = web(http, "ok")

    result = stubs.acquire(OVERRIDE)

    assert (result.method, result.block_class, result.bundle.body) == ("browser", "ok", PAGE)
    assert _attempts(result) == [("http", http), ("browser", "ok")]
    assert stubs.browser.calls == [(URL, OVERRIDE)]
    assert result.duration_ms == 2  # both rungs' time


@pytest.mark.parametrize("browser", ["shell", "blocked", "not_found", "error"])
def test_the_http_outcome_is_kept_when_the_browser_does_no_better(browser: BlockClass) -> None:
    stubs = web("shell", browser)

    result = stubs.acquire()

    assert (result.method, result.block_class, result.bundle.body) == ("http", "shell", SHELL)
    assert _attempts(result) == [("http", "shell"), ("browser", browser)]


@pytest.mark.parametrize("status", [429, 503])
def test_a_request_to_slow_down_is_not_retried_in_the_browser(status: int) -> None:
    stubs = web("blocked", http_status=status)

    result = stubs.acquire()

    assert (result.method, result.bundle.manifest.status_code) == ("http", status)
    assert _attempts(result) == [("http", "blocked")]
    assert stubs.browser.calls == []


@pytest.mark.parametrize("http", ["not_found", "error"])
def test_a_missing_page_or_an_error_is_not_retried_in_the_browser(http: BlockClass) -> None:
    stubs = web(http)

    result = stubs.acquire()

    assert _attempts(result) == [("http", http)]
    assert stubs.browser.calls == []


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
            {"method": "http", "status": 200, "block_class": "shell", "duration_ms": 1, "error": None},
            {"method": "browser", "status": 200, "block_class": "ok", "duration_ms": 1, "error": None},
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
