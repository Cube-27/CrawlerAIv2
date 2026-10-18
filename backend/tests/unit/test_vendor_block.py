"""A page a vendor's challenge keeps out is an outcome (master plan 2026-10-18 §3.1): `blocked` naming the vendor, a
worker task retried at most once after the back-off, and the eval import's fetch of a page not reached retried up to
three times with the closest capture kept. Results are synthetic (RFC 2606 hosts); nothing goes to the network."""

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from crawlerai.acquire.challenge import STRUCTURAL, vendor_block
from crawlerai.acquire.outcome import Content, Exchange, fetch_result
from crawlerai.acquire.types import AttemptRecord, BlockClass, FetchPolicy, FetchResult
from crawlerai.adapters.challenges import SIGNATURES
from crawlerai.core.capture import CaptureMethod
from crawlerai.core.ids import uuid7
from crawlerai.core.retry import FIRST_BACKOFF
from crawlerai.db.models import CaptureId, JobId, SiteId, UrlTaskId
from crawlerai.db.queue import ClaimedTask
from crawlerai.eval.label_file import best_fetch
from crawlerai.services.scrape_steps import SiteRow
from crawlerai.worker.handlers.steps import FetchedPage, unreached
from crawlerai.worker.loop import Failed, Finished

URL = "https://shop.example.test/item/1"
# Vendor labels come from the adapter package's signature data (C3).
VENDOR, OTHER = SIGNATURES[0].vendor, SIGNATURES[1].vendor


def _result(block_class: BlockClass, *labels: str | None) -> FetchResult:
    status = 200 if block_class == "ok" else 403
    result = fetch_result(
        url=URL,
        method="http",
        policy=FetchPolicy(),
        engine_version="test",
        fetched_at=datetime.now(UTC),
        started=time.monotonic(),
        exchange=Exchange(url=URL, status=status, request_headers=(), response_headers=()),
        content=Content(body=b"<html></html>"),
        block_class=block_class,
        error=None,
    )
    if not labels:
        return result
    method: tuple[CaptureMethod, CaptureMethod] = ("http", "browser")
    attempts = tuple(
        AttemptRecord(method=method[i % 2], status=status, block_class=block_class, duration_ms=1, challenge=label)
        for i, label in enumerate(labels)
    )
    return result.model_copy(update={"attempts": attempts})


@pytest.mark.parametrize(
    ("result", "vendor"),
    [
        pytest.param(_result("blocked", VENDOR, VENDOR), VENDOR, id="vendor"),
        pytest.param(_result("blocked", OTHER, STRUCTURAL), OTHER, id="latest-vendor-label"),
        pytest.param(_result("blocked", STRUCTURAL), None, id="structural"),
        pytest.param(_result("blocked", None), None, id="unlabelled"),
        pytest.param(_result("ok", VENDOR), None, id="reached"),
    ],
)
def test_a_vendor_block_is_a_blocked_fetch_whose_attempt_names_a_vendor(
    result: FetchResult, vendor: str | None
) -> None:
    assert vendor_block(result) == vendor


def _task(attempts: int) -> ClaimedTask:
    return ClaimedTask(
        id=UrlTaskId(uuid7()),
        job_id=JobId(uuid7()),
        url=URL,
        canonical_url=URL,
        page_kind="detail",
        attempts=attempts,
        priority=0,
        depth=0,
        score=None,
        parent_task_id=None,
        claimed_by="w",
        lease_until=datetime.now(UTC),
    )


def _fetched(result: FetchResult) -> FetchedPage:
    site = SiteRow(SiteId(uuid7()), "http", None, None, None)
    return FetchedPage(site, result, CaptureId(uuid7()), (), result.attempts, None)


def test_a_vendor_blocked_task_is_retried_once_after_the_back_off_then_ends_blocked_naming_the_vendor() -> None:
    page = _fetched(_result("blocked", VENDOR, VENDOR))

    first, second = unreached(page, _task(1)), unreached(page, _task(2))

    assert first == Failed(
        f"challenge: {VENDOR}", transient=True, after=FIRST_BACKOFF, exhausted="blocked", capture_id=page.capture_id
    )
    assert second == Finished("blocked", reason=f"challenge: {VENDOR}", capture_id=page.capture_id)


def test_a_block_no_vendor_names_ends_blocked_at_once() -> None:
    page = _fetched(_result("blocked", STRUCTURAL))

    assert unreached(page, _task(1)) == Finished("blocked", capture_id=page.capture_id)


class Fetches:
    """Answers each fetch with the next of `answers`, and records the waits between them."""

    def __init__(self, *answers: FetchResult | str) -> None:
        self.answers = list(answers)
        self.waits: list[float] = []
        self.fetched = 0

    async def fetch(self) -> FetchResult | str:
        self.fetched += 1
        return self.answers.pop(0)

    async def wait(self, seconds: float) -> None:
        self.waits.append(seconds)


def _best(fetches: Fetches) -> FetchResult | str:
    return asyncio.run(best_fetch(fetches.fetch, wait=fetches.wait))


def test_the_import_fetches_a_page_not_reached_again_after_the_back_off_and_keeps_the_reached_one() -> None:
    reached = _result("ok")
    fetches = Fetches(_result("blocked"), reached)

    assert _best(fetches) is reached
    assert (fetches.fetched, fetches.waits) == (2, [FIRST_BACKOFF.total_seconds()])


def test_the_import_tries_three_times_and_keeps_the_capture_closest_to_reached() -> None:
    shell = _result("shell")
    fetches = Fetches(_result("blocked"), shell, _result("blocked"))

    assert _best(fetches) is shell
    assert fetches.fetched == 3
    assert fetches.waits == [timedelta(seconds=30).total_seconds(), timedelta(seconds=60).total_seconds()]


def test_a_page_not_sent_is_not_fetched_again() -> None:
    fetches = Fetches("robots")

    assert _best(fetches) == "robots"
    assert fetches.fetched == 1
