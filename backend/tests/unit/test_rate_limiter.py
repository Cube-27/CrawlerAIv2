"""The in-process token bucket in front of authentication (SPEC-07 §4.2): `burst` requests at once, then `rate` per
second, per bucket key."""

import pytest

from crawlerai.api.auth import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_full_bucket_admits_the_burst_then_refuses_with_the_wait_for_one_token() -> None:
    clock = Clock()
    limiter = RateLimiter(rate=20, burst=40, clock=clock)

    admitted = [limiter.take("a") for _ in range(40)]
    refused = limiter.take("a")

    assert admitted == [None] * 40
    assert refused == pytest.approx(0.05)  # one token at 20 per second


def test_tokens_refill_at_the_rate_up_to_the_burst() -> None:
    clock = Clock()
    limiter = RateLimiter(rate=20, burst=40, clock=clock)
    for _ in range(40):
        limiter.take("a")

    clock.now += 0.5  # 10 tokens
    after_half_a_second = [limiter.take("a") for _ in range(11)]
    clock.now += 60  # refills to the burst, no further
    after_a_minute = [limiter.take("a") for _ in range(41)]

    assert after_half_a_second.count(None) == 10
    assert after_a_minute.count(None) == 40


def test_buckets_are_independent() -> None:
    limiter = RateLimiter(rate=1, burst=1, clock=Clock())

    assert limiter.take("a") is None
    assert limiter.take("a") == pytest.approx(1.0)
    assert limiter.take("b") is None


def test_buckets_that_refilled_are_dropped_so_unknown_keys_do_not_accumulate() -> None:
    clock = Clock()
    limiter = RateLimiter(rate=20, burst=40, clock=clock)
    for n in range(1000):
        limiter.take(f"key-{n}")

    clock.now += 2  # 40 tokens at 20 per second: every bucket is full again
    limiter.take("another")

    assert len(limiter) == 1
