"""When a schedule runs (§22 "Recurring schedule storage", admitted 2026-10-17): a 5-field cron expression read in an
IANA time zone, or a fixed interval.

A cron expression has the five fields of the POSIX crontab (IEEE Std 1003.1, `crontab`: minute, hour, day of month,
month, day of week), read by `cronsim` (which also takes the `L` and `#` day forms); its times are wall-clock times in
`timezone` (the IANA tz database, RFC 6557), so a daily run stays at its hour across a DST change, and a time a DST
change skips runs at the first minute after it. An interval runs every `interval_s` seconds, anchored on its first due
time, so it keeps its phase.

Missed runs (the scheduler was down, or busy): a schedule due more than once by the time it is read runs once, and its
next run is its first due time after now (`next_run`).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cronsim import CronSim, CronSimError

CRON_FIELDS: Final = 5
MIN_INTERVAL_S: Final = 60  # cron's own resolution: a minute (`crawlerai.services.schedules`)


class InvalidCadence(ValueError):
    pass


@dataclass(frozen=True)
class Cadence:
    """A cron expression in `timezone`, or an interval: exactly one of `cron` and `interval_s`."""

    cron: str | None
    interval_s: int | None
    timezone: str

    def __post_init__(self) -> None:
        if (self.cron is None) == (self.interval_s is None):
            raise InvalidCadence("give exactly one of `cron` and `interval_s`")
        zone(self.timezone)
        if self.interval_s is not None and self.interval_s < MIN_INTERVAL_S:
            raise InvalidCadence(f"`interval_s` is at least {MIN_INTERVAL_S}")
        if self.cron is not None:
            check_cron(self.cron)


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidCadence(f"{name!r} is not an IANA time zone") from e


def check_cron(expression: str) -> None:
    if len(expression.split()) != CRON_FIELDS:
        raise InvalidCadence("a cron expression has 5 fields: minute, hour, day of month, month, day of week")
    try:
        CronSim(expression, datetime(2000, 1, 1, tzinfo=ZoneInfo("UTC")))
    except CronSimError as e:
        raise InvalidCadence(f"not a cron expression: {e}") from e


def next_run(cadence: Cadence, now: datetime, anchor: datetime | None = None) -> datetime:
    """The first due time after `now` (timezone-aware). An interval counts from `anchor`, its last due time, when there
    is one, and from `now` otherwise."""
    if cadence.cron is not None:
        return next(CronSim(cadence.cron, now.astimezone(zone(cadence.timezone))))
    step = timedelta(seconds=cadence.interval_s or 0)
    if anchor is None:
        return now + step
    missed = max(0, (now - anchor) // step)
    due = anchor + step * missed
    return due if due > now else due + step
