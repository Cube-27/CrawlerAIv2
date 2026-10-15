import time
import uuid
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from crawlerai.core.ids import uuid7, uuid7_floor


def test_uuid7_has_version_7_and_the_rfc_9562_variant() -> None:
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_leading_48_bits_are_the_creation_time_in_unix_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000

    assert before <= value.int >> 80 <= after


def test_uuid7_values_from_one_process_strictly_increase() -> None:
    values = [uuid7() for _ in range(10_000)]

    assert values == sorted(set(values))


def test_uuid7_floor_is_the_lowest_id_of_its_millisecond() -> None:
    at = datetime(2030, 1, 1, tzinfo=UTC)
    assert uuid7_floor(at) == uuid.UUID(int=1_893_456_000_000 << 80)


@given(st.integers(min_value=0, max_value=(1 << 76) - 1), st.integers(min_value=-5, max_value=5))
def test_an_id_made_in_a_millisecond_sorts_by_time_against_any_floor(low_bits: int, offset_ms: int) -> None:
    at = datetime(2030, 1, 1, tzinfo=UTC)
    made_at = at + timedelta(milliseconds=offset_ms)
    made = uuid.UUID(int=uuid7_floor(made_at).int | low_bits)
    assert (made >= uuid7_floor(at)) == (made_at >= at)
