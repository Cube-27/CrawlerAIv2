import time
import uuid

from crawlerai.core.ids import uuid7


def test_uuid7_has_version_7_and_the_rfc_9562_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_leading_48_bits_are_the_creation_time_in_unix_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000

    assert before <= value.int >> 80 <= after


def test_uuid7_values_created_in_later_milliseconds_sort_after_earlier_ones() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()

    assert first < second


def test_uuid7_values_are_distinct_within_one_millisecond() -> None:
    values = {uuid7() for _ in range(10_000)}

    assert len(values) == 10_000


def test_uuid7_values_from_one_process_strictly_increase() -> None:
    values = [uuid7() for _ in range(10_000)]

    assert values == sorted(set(values))
