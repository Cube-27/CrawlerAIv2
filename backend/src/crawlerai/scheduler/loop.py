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
from functools import partial

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.core.settings import Settings
from crawlerai.db.queue import release_expired_leases
from crawlerai.scheduler.retention import expire_candidates, expire_captures
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Periodic:
    name: str
    interval: timedelta
    run: Callable[[AsyncConnection], Awaitable[object]]


def periodic(store: ObjectStore) -> tuple[Periodic, ...]:
    """The scheduler's entries (SPEC-01 §4.3). `store` is the main object store, where production captures live."""
    return (
        Periodic("release_expired_leases", timedelta(minutes=1), release_expired_leases),
        Periodic("expire_captures", timedelta(hours=1), partial(expire_captures, store=store)),
        Periodic("expire_candidates", timedelta(hours=1), expire_candidates),
    )


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
