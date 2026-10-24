"""Row identifiers: UUIDv7 per RFC 9562 §5.7, generated in Python.

The standard library gains `uuid.uuid7` only in Python 3.14; this project runs on 3.12.
"""

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

_lock = threading.Lock()
_last = (0, 0)  # (unix_ms, rand_a) of the previous value


def uuid7() -> uuid.UUID:
    """48-bit Unix time in milliseconds, then the version, 12 bits of `rand_a`, the variant and 62 random bits.

    Values from one process strictly increase, so rows sort by id in creation order (`job_event` is ordered by
    id). Within one millisecond `rand_a` is a counter (RFC 9562 §6.2, method 1) that starts at a random value in its
    lower half; when it overflows, or the clock goes back, the timestamp advances past the previous one.
    """
    global _last
    rand = int.from_bytes(os.urandom(10))
    seed = rand >> 62 & 0x7FF
    with _lock:
        unix_ms = time.time_ns() // 1_000_000
        last_ms, last_counter = _last
        if unix_ms > last_ms:
            counter = seed
        elif last_counter < 0xFFF:
            unix_ms, counter = last_ms, last_counter + 1
        else:
            unix_ms, counter = last_ms + 1, seed
        _last = (unix_ms, counter)
    value = (unix_ms & (1 << 48) - 1) << 80
    value |= 0x7 << 76 | counter << 64
    value |= 0b10 << 62 | rand & (1 << 62) - 1
    return uuid.UUID(int=value)


def uuid7_floor(at: datetime) -> uuid.UUID:
    """The least UUID whose 48-bit timestamp is `at`'s millisecond (RFC 9562 §5.7): UUIDv7s made before `at` sort below
    it and those made at or after it sort at or above it, so a time range is an id range."""
    unix_ms = (at - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(milliseconds=1)
    return uuid.UUID(int=(unix_ms & (1 << 48) - 1) << 80)
