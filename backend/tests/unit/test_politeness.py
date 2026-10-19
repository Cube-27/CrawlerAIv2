"""Politeness (acquisition spec): the request interval, Retry-After, per-host admission and its adaptive spacing
(D-1327)."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta

import pytest

from crawlerai.acquire.politeness import (
    RECOVERY_FACTOR,
    RECOVERY_RUN,
    HostLimiter,
    interval,
    retry_after,
)
from crawlerai.acquire.types import AttemptRecord
from crawlerai.core.retry import FIRST_BACKOFF

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def _run[T](step: Coroutine[object, object, T]) -> T:
    return asyncio.run(step)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("crawl_delay_ms", "robots_delay", "expected"),
    [
        (None, None, timedelta(seconds=1)),
        (250, None, timedelta(milliseconds=250)),
        (0, None, timedelta(0)),
        (None, timedelta(seconds=10), timedelta(seconds=10)),
        (5000, timedelta(seconds=2), timedelta(seconds=5)),
        (250, timedelta(seconds=2), timedelta(seconds=2)),
    ],
)
def test_the_interval_is_the_site_setting_or_1s_never_below_the_robots_crawl_delay(
    crawl_delay_ms: int | None, robots_delay: timedelta | None, expected: timedelta
) -> None:
    assert interval(crawl_delay_ms, robots_delay) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("120", timedelta(seconds=120)),
        (" 0 ", timedelta(0)),
        ("Tue, 13 Oct 2026 12:05:00 GMT", timedelta(minutes=5)),
        ("Tue, 13 Oct 2026 12:05:00 -0000", timedelta(minutes=5)),
        ("Tue, 13 Oct 2026 11:00:00 GMT", timedelta(0)),
        ("-5", None),
        ("1.5", None),
        ("soon", None),
        # Beyond what a timedelta holds, or what int() parses: the longest pause there is.
        ("99999999999999", timedelta.max),
        ("9" * 5000, timedelta.max),
    ],
)
def test_retry_after_reads_seconds_or_an_http_date(value: str, expected: timedelta | None) -> None:
    assert retry_after((("Retry-After", value),), NOW) == expected


def test_the_limiter_admits_one_request_per_interval_per_host() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    second = timedelta(seconds=1)

    assert _run(limiter.admit("a.example.test", second)) == timedelta(0)
    assert _run(limiter.admit("b.example.test", second)) == timedelta(0)
    clock.now += 0.25
    assert _run(limiter.admit("a.example.test", second)) == timedelta(seconds=0.75)
    # A refused request does not take the slot.
    clock.now += 0.75
    assert _run(limiter.admit("a.example.test", second)) == timedelta(0)


def test_a_wait_after_a_pause_the_site_asked_for_goes_no_sooner_and_holds_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:  # time passes on the clock, not in the test
        slept.append(seconds)
        clock.now += seconds

    monkeypatch.setattr("crawlerai.acquire.politeness.asyncio.sleep", sleep)
    start = clock.now

    admitted = asyncio.run(
        limiter.wait("a.example.test", timedelta(seconds=1), timedelta(minutes=1), after=FIRST_BACKOFF)
    )

    assert admitted is True
    assert clock.now - start == pytest.approx(30)
    # The request it admitted took the host's turn: the next one waits the interval.
    assert _run(limiter.admit("a.example.test", timedelta(seconds=1))) == timedelta(seconds=1)


# --- adaptive spacing (D-1327) -----------------------------------------------------------------------------------

_HOST = "a.example.test"
_SECOND = timedelta(seconds=1)


def _answer(status: int, block_class: str = "ok", challenge: str | None = None) -> AttemptRecord:
    return AttemptRecord.model_validate(
        {"method": "http", "status": status, "block_class": block_class, "duration_ms": 1, "challenge": challenge}
    )


def test_a_slow_down_doubles_the_spacing_and_the_next_turn_comes_that_much_later() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    assert _run(limiter.admit(_HOST, _SECOND)) == timedelta(0)

    _run(limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")]))
    _run(limiter.observe(_HOST, _SECOND, [_answer(503, "blocked")]))
    clock.now += 1
    assert _run(limiter.admit(_HOST, _SECOND)) == 3 * _SECOND  # the slow-down pushed the reservation made at admission
    clock.now += 3
    assert _run(limiter.admit(_HOST, _SECOND)) == timedelta(0)

    assert limiter.spacing(_HOST, _SECOND) == 4 * _SECOND
    assert _run(limiter.admit(_HOST, _SECOND)) == 4 * _SECOND
    assert limiter.spacing("b.example.test", _SECOND) == _SECOND  # per host


def test_a_run_of_ok_answers_shrinks_the_spacing_back_to_the_interval_and_no_further() -> None:
    limiter = HostLimiter(Clock())
    _run(limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")]))  # 2 s

    _run(limiter.observe(_HOST, _SECOND, [_answer(200)] * (RECOVERY_RUN - 1)))
    assert limiter.spacing(_HOST, _SECOND) == 2 * _SECOND
    _run(limiter.observe(_HOST, _SECOND, [_answer(200)]))
    assert limiter.spacing(_HOST, _SECOND) == 2 * _SECOND * RECOVERY_FACTOR

    _run(limiter.observe(_HOST, _SECOND, [_answer(200)] * RECOVERY_RUN * 20))
    assert limiter.spacing(_HOST, _SECOND) == _SECOND
