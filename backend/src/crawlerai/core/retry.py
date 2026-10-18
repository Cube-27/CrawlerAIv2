"""What the retry rules of different layers share: the first backoff and the statuses that say "try again"."""

from datetime import timedelta
from typing import Final

# SPEC-02 §4.6: the first backoff of a host that asked for fewer requests, and the queue's before it retries a task
# that failed transiently (SPEC-01 D-0006); each retry doubles it.
FIRST_BACKOFF: Final = timedelta(seconds=30)


def backoff_delay(tries: int) -> timedelta:
    """The backoff after try `tries` (1 for the first) failed: `FIRST_BACKOFF`, doubled per try. The queue retries a
    task after it, and the polite fetch pauses a host by it (`acquire.politeness.backoff`)."""
    delay: timedelta = FIRST_BACKOFF * 2 ** (tries - 1)
    return delay


def is_transient(status: int) -> bool:
    """Whether an HTTP status says the server did not answer this time: 408 Request Timeout (RFC 9110 §15.5.9),
    429 Too Many Requests (RFC 6585 §4) or a 5xx server error (RFC 9110 §15.6). Other errors are the request's own
    fault (a bad key, an unknown model, a refused schema)."""
    return status in (408, 429) or 500 <= status <= 599
