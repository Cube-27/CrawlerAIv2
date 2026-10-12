"""Row identifiers (SPEC-01 §4.2): UUIDv7 per RFC 9562 §5.7, generated in Python.

The standard library gains `uuid.uuid7` only in Python 3.14; this project runs on 3.12.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """48-bit Unix time in milliseconds, then the version, 12 random bits, the variant and 62 random bits."""
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10))
    value = (unix_ms & (1 << 48) - 1) << 80
    value |= 0x7 << 76 | (rand >> 62 & 0xFFF) << 64
    value |= 0b10 << 62 | rand & (1 << 62) - 1
    return uuid.UUID(int=value)
