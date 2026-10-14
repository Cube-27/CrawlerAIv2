"""The scheduler process (SPEC-01 §4.3): periodic upkeep, from a table of entries that later specs extend.

Each entry runs once at start, then again `interval` after its previous run ended, in a transaction of its own. An
entry that raises is rolled back and logged, and runs again at its next turn: one failing entry, or the database
being down for a while, stops none of the others.

An entry with a `batch` handles at most that many items per run and returns how many it handled. A full batch means
more may be waiting, so the entry is due again at once: a backlog drains in short transactions, one per batch,
taking turns with the other entries, instead of one long transaction or one batch per interval.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.acquire.rungs import Rung
from crawlerai.api.webhooks import DELIVERY_BATCH, Poster, deliver_webhooks
from crawlerai.config_ir.learning import EXPIRE_BATCH, expire_learn_runs
from crawlerai.config_ir.progressive import TRIGGER_BATCH, trigger_learning
from crawlerai.core.settings import Settings
from crawlerai.db.queue import release_expired_leases
from crawlerai.recurring.listing_diff import close_run
from crawlerai.scheduler.recheck import RECHECK_BATCH, recheck_fetch_method
from crawlerai.scheduler.retention import RETENTION_BATCH, expire_candidates, expire_captures
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Periodic:
    name: str
    interval: timedelta
    run: Callable[[AsyncConnection], Awaitable[object]]
    batch: int | None = None


def periodic(store: ObjectStore, fetch: Rung, post: Poster) -> tuple[Periodic, ...]:
    """The scheduler's entries (SPEC-01 §4.3). `store` is the main object store, where production captures live;
    `fetch` is the HTTP rung, for the fetch-method re-check (SPEC-02 §4.4); `post` sends webhooks (SPEC-10 §4.2)."""
    return (
        # A job its last expired lease ends is diffed as the worker would have (SPEC-11 §4.5).
        Periodic("release_expired_leases", timedelta(minutes=1), partial(release_expired_leases, ending=close_run)),
        Periodic(
            "expire_captures",
            timedelta(hours=1),
            partial(expire_captures, store=store, batch=RETENTION_BATCH),
            batch=RETENTION_BATCH,
        ),
        Periodic(
            "expire_candidates",
            timedelta(hours=1),
            partial(expire_candidates, batch=RETENTION_BATCH),
            batch=RETENTION_BATCH,
        ),
        Periodic(
            "recheck_fetch_method",
            timedelta(hours=1),
            partial(recheck_fetch_method, fetch=fetch, batch=RECHECK_BATCH),
            batch=RECHECK_BATCH,
        ),
        Periodic(
            "trigger_learning",
            timedelta(minutes=1),
            partial(trigger_learning, batch=TRIGGER_BATCH),
            batch=TRIGGER_BATCH,
        ),
        Periodic(
            "expire_learn_runs",
            timedelta(minutes=5),
            partial(expire_learn_runs, batch=EXPIRE_BATCH),
            batch=EXPIRE_BATCH,
        ),
        Periodic(
            "deliver_webhooks",
            timedelta(seconds=5),
            partial(deliver_webhooks, post=post, batch=DELIVERY_BATCH),
            batch=DELIVERY_BATCH,
        ),
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
                    result = await _run(engine, entry)
                    backlog = entry.batch is not None and result == entry.batch
                    due[index] = clock() if backlog else clock() + entry.interval.total_seconds()
            wait = max(0.0, min(due) - clock()) if due else None
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), wait)
    finally:
        await engine.dispose()


async def _run(engine: AsyncEngine, entry: Periodic) -> object:
    """The entry's result, or None if it failed."""
    try:
        async with engine.begin() as conn:
            result = await entry.run(conn)
    except Exception:
        log.exception("scheduler: %s failed; it runs again in %s", entry.name, entry.interval)
        return None
    log.debug("scheduler: %s: %s", entry.name, result)
    return result
