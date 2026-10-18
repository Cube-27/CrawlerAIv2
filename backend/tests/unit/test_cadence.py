"""When a schedule runs (`crawlerai.core.cadence`): 5-field cron expressions in an IANA zone, intervals that keep their
phase, and missed runs made up once."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from crawlerai.core.cadence import Cadence, InvalidCadence, next_run

START = datetime(2026, 1, 1, tzinfo=UTC)


@given(
    interval=st.integers(min_value=60, max_value=86_400),
    elapsed=st.integers(min_value=0, max_value=10 * 86_400),
)
def test_an_interval_runs_next_at_its_first_due_time_after_now_on_its_phase(interval: int, elapsed: int) -> None:
    cadence = Cadence(None, interval, "UTC")
    now = START + timedelta(seconds=elapsed)

    due = next_run(cadence, now, anchor=START)

    assert now < due <= now + timedelta(seconds=interval)
    assert (due - START).total_seconds() % interval == 0


def test_a_cron_time_a_dst_change_skips_runs_at_the_first_minute_after_it() -> None:
    zone = ZoneInfo("America/New_York")  # 2026-03-08 02:00 -> 03:00
    cadence = Cadence("30 2 * * *", None, "America/New_York")

    due = next_run(cadence, datetime(2026, 3, 8, 0, 0, tzinfo=zone))

    assert due.astimezone(zone).replace(tzinfo=None) == datetime(2026, 3, 8, 3, 0)


@pytest.mark.parametrize(
    ("cron", "interval_s", "timezone"),
    [
        (None, None, "UTC"),
        ("* * * * *", 60, "UTC"),
        (None, 59, "UTC"),
        ("@hourly", None, "UTC"),
        ("0 0 * * * *", None, "UTC"),
        ("61 * * * *", None, "UTC"),
        ("0 0 31 2 *", None, "UTC"),
        ("* * * * *", None, "Mars/Olympus"),
    ],
)
def test_an_invalid_cadence_is_refused(cron: str | None, interval_s: int | None, timezone: str) -> None:
    with pytest.raises(InvalidCadence):
        Cadence(cron, interval_s, timezone)
