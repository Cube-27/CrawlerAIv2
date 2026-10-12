"""The scheduler process (SPEC-01 §4.3): periodic upkeep, from a table of entries that later specs extend.

Each entry runs once at start, then again `interval` after its previous run ended, in a transaction of its own. An
entry that raises is rolled back and logged, and runs again at its next turn: one failing entry, or the database
being down for a while, stops none of the others.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.core.settings import Settings
from crawlerai.db.queue import release_expired_leases

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Periodic:
    name: str
    interval: timedelta
    run: Callable[[AsyncConnection], Awaitable[object]]


# `expire_captures` and `expire_candidates` (1 h) arrive with the retention jobs (SPEC-01 PR 8).
PERIODIC: Final = (Periodic("release_expired_leases", timedelta(minutes=1), release_expired_leases),)


async def run_scheduler(settings: Settings, entries: Sequence[Periodic], stop: asyncio.Event) -> None:
    """Run `entries` until `stop` is set. An entry in progress finishes first."""
    engine = create_async_engine(settings.database_url.get_secret_value())
    clock = asyncio.get_running_loop().time
    due = [clock()] * len(entries)
    try:
        while not stop.is_set():
            for index, entry in enumerate(entries):
                if due[index] <= clock() and not stop.is_set():
                    await _run(engine, entry)
                    due[index] = clock() + entry.interval.total_seconds()
            wait = max(0.0, min(due) - clock()) if due else None
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), wait)
    finally:
        await engine.dispose()


async def _run(engine: AsyncEngine, entry: Periodic) -> None:
    try:
        async with engine.begin() as conn:
            result = await entry.run(conn)
    except Exception:
        log.exception("scheduler: %s failed; it runs again in %s", entry.name, entry.interval)
    else:
        log.debug("scheduler: %s: %s", entry.name, result)
