"""Politeness (SPEC-02 §4.6): the request interval, Retry-After, per-host admission and its adaptive spacing
(D-1327)."""

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.politeness import (
    BACKOFF_MAX,
    RECOVERY_FACTOR,
    RECOVERY_RUN,
    HostLimiter,
    asked_pause,
    interval,
    refuse,
    retry_after,
)
from crawlerai.acquire.types import AttemptRecord
from crawlerai.core.retry import FIRST_BACKOFF

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


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


def test_retry_after_is_none_without_the_header_and_uses_the_last_one_when_repeated() -> None:
    assert retry_after((("Content-Type", "text/html"),), NOW) is None
    assert retry_after((("retry-after", "10"), ("Retry-After", "20")), NOW) == timedelta(seconds=20)


def test_the_limiter_admits_one_request_per_interval_per_host() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    second = timedelta(seconds=1)

    assert limiter.admit("a.example.test", second) == timedelta(0)
    assert limiter.admit("b.example.test", second) == timedelta(0)
    clock.now += 0.25
    assert limiter.admit("a.example.test", second) == timedelta(seconds=0.75)
    # A refused request does not take the slot.
    clock.now += 0.75
    assert limiter.admit("a.example.test", second) == timedelta(0)


def test_a_wait_in_place_past_its_bound_is_refused_and_takes_no_turn() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    minute = timedelta(minutes=1)
    limiter.pause("a.example.test", timedelta(minutes=10))

    refused = asyncio.run(limiter.wait("a.example.test", timedelta(seconds=1), minute))
    clock.now += 600

    assert refused is False
    # The refused wait took no turn: the next request goes as the pause ends.
    assert asyncio.run(limiter.wait("a.example.test", timedelta(seconds=1), minute)) is True
    assert limiter.admit("a.example.test", timedelta(seconds=1)) == timedelta(seconds=1)


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
    assert limiter.admit("a.example.test", timedelta(seconds=1)) == timedelta(seconds=1)


def test_a_pause_longer_than_the_bound_is_refused_without_waiting() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)

    refused = asyncio.run(
        limiter.wait("a.example.test", timedelta(seconds=1), timedelta(minutes=1), after=timedelta(hours=1))
    )

    assert refused is False
    assert limiter.admit("a.example.test", timedelta(seconds=1)) == timedelta(0)  # left to the caller's backoff


@pytest.mark.parametrize(("asked", "expected"), [(timedelta(seconds=9), timedelta(seconds=9)), (None, FIRST_BACKOFF)])
def test_the_pause_a_slow_down_asks_for_is_its_retry_after_else_the_first_backoff(
    asked: timedelta | None, expected: timedelta
) -> None:
    attempt = AttemptRecord(method="http", status=503, block_class="blocked", duration_ms=1, retry_after=asked)
    assert asked_pause(attempt) == expected


def test_a_refusing_admission_refuses_after_a_pause_too() -> None:
    assert asyncio.run(refuse(after=timedelta(seconds=5))) is False


def test_a_pause_holds_the_host_and_a_shorter_one_does_not_cut_it() -> None:
    clock = Clock()
    limiter = HostLimiter(clock)

    limiter.pause("a.example.test", timedelta(seconds=120))
    limiter.pause("a.example.test", timedelta(seconds=30))

    assert limiter.admit("a.example.test", timedelta(seconds=1)) == timedelta(seconds=120)
    assert limiter.admit("b.example.test", timedelta(seconds=1)) == timedelta(0)
    clock.now += 120
    assert limiter.admit("a.example.test", timedelta(seconds=1)) == timedelta(0)


@given(
    gaps=st.lists(st.floats(min_value=0, max_value=5, allow_nan=False), min_size=1, max_size=50),
    interval_s=st.floats(min_value=0, max_value=3, allow_nan=False),
)
def test_admitted_requests_to_a_host_are_never_closer_than_the_interval(gaps: list[float], interval_s: float) -> None:
    clock = Clock()
    limiter = HostLimiter(clock)
    admitted: list[float] = []

    for gap in gaps:
        clock.now += gap
        if limiter.admit("a.example.test", timedelta(seconds=interval_s)) == timedelta(0):
            admitted.append(clock.now)

    assert admitted[0] == 1000.0 + gaps[0]
    assert all(later - earlier >= interval_s - 1e-6 for earlier, later in pairwise(admitted))


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
    assert limiter.admit(_HOST, _SECOND) == timedelta(0)

    limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")])
    limiter.observe(_HOST, _SECOND, [_answer(503, "blocked")])
    clock.now += 1
    assert limiter.admit(_HOST, _SECOND) == timedelta(0)

    assert limiter.spacing(_HOST, _SECOND) == 4 * _SECOND
    assert limiter.admit(_HOST, _SECOND) == 4 * _SECOND
    assert limiter.spacing("b.example.test", _SECOND) == _SECOND  # per host


def test_a_challenge_slows_the_host_as_a_slow_down_does() -> None:
    limiter = HostLimiter(Clock())

    limiter.observe(_HOST, _SECOND, [_answer(403, "blocked", challenge="structural")])

    assert limiter.spacing(_HOST, _SECOND) == 2 * _SECOND


def test_a_plain_refusal_or_error_leaves_the_spacing_as_it_is() -> None:
    limiter = HostLimiter(Clock())

    limiter.observe(_HOST, _SECOND, [_answer(403, "blocked"), _answer(500, "error"), _answer(404, "not_found")])

    assert limiter.spacing(_HOST, _SECOND) == _SECOND


def test_the_spacing_never_passes_the_longest_backoff() -> None:
    limiter = HostLimiter(Clock())

    limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")] * 30)

    assert limiter.spacing(_HOST, _SECOND) == BACKOFF_MAX


def test_a_run_of_ok_answers_shrinks_the_spacing_back_to_the_interval_and_no_further() -> None:
    limiter = HostLimiter(Clock())
    limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")])  # 2 s

    limiter.observe(_HOST, _SECOND, [_answer(200)] * (RECOVERY_RUN - 1))
    assert limiter.spacing(_HOST, _SECOND) == 2 * _SECOND
    limiter.observe(_HOST, _SECOND, [_answer(200)])
    assert limiter.spacing(_HOST, _SECOND) == 2 * _SECOND * RECOVERY_FACTOR

    limiter.observe(_HOST, _SECOND, [_answer(200)] * RECOVERY_RUN * 20)
    assert limiter.spacing(_HOST, _SECOND) == _SECOND


def test_a_slow_down_inside_a_run_of_ok_answers_starts_the_run_again() -> None:
    limiter = HostLimiter(Clock())
    limiter.observe(_HOST, _SECOND, [_answer(429, "blocked")])

    limiter.observe(_HOST, _SECOND, [_answer(200)] * (RECOVERY_RUN - 1) + [_answer(429, "blocked")])
    limiter.observe(_HOST, _SECOND, [_answer(200)] * (RECOVERY_RUN - 1))

    assert limiter.spacing(_HOST, _SECOND) == 4 * _SECOND


@given(
    answers=st.lists(st.sampled_from([200, 429, 503, 403]), max_size=200),
    interval_s=st.floats(min_value=0, max_value=1200, allow_nan=False),
)
def test_the_spacing_stays_between_the_interval_and_the_longest_backoff(answers: list[int], interval_s: float) -> None:
    limiter = HostLimiter(Clock())
    gap = timedelta(seconds=interval_s)

    for status in answers:
        limiter.observe(_HOST, gap, [_answer(status, "ok" if status == 200 else "blocked")])

    spacing = limiter.spacing(_HOST, gap)
    assert spacing >= gap
    assert spacing <= max(BACKOFF_MAX, gap)
