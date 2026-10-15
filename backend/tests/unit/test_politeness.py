"""Politeness (SPEC-02 §4.6): the request interval, Retry-After and per-host admission."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.acquire.politeness import HostLimiter, interval, retry_after

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
