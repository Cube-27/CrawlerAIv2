"""The in-process token bucket in front of authentication: `burst` requests at once, then `rate` per
second, per bucket key."""

import pytest

from snowcrawl.api.auth import RateLimiter


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
