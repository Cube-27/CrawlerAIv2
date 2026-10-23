"""The scheduler process: periodic upkeep and the recurring schedules' runs, from a table of
entries that later specs extend.

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

from crawlerai.acquire.host_turns import EXPIRE_BATCH as HOST_TURN_BATCH
from crawlerai.acquire.host_turns import expire_host_turns
from crawlerai.acquire.rungs import Rung
from crawlerai.api.webhooks import DELIVERY_BATCH, Poster, deliver_webhooks
from crawlerai.config_ir.learning import EXPIRE_BATCH, expire_learn_runs
from crawlerai.config_ir.progressive import TRIGGER_BATCH, trigger_learning
from crawlerai.core.settings import Settings
from crawlerai.db.queue import LEASE_BATCH, STALLED_BATCH, fail_stalled_jobs, release_expired_leases
from crawlerai.db.webhook_outbox import FORM_BATCH, form_deliveries
from crawlerai.recurring.listing_diff import close_run
from crawlerai.scheduler.recheck import RECHECK_BATCH, recheck_fetch_method
from crawlerai.scheduler.retention import RETENTION_BATCH, expire_candidates, expire_captures, expire_webhooks
from crawlerai.services.schedules import SCHEDULE_BATCH, Submitting, run_due_schedules
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Periodic:
    name: str
    interval: timedelta
    run: Callable[[AsyncConnection], Awaitable[object]]
    batch: int | None = None


def periodic(store: ObjectStore, fetch: Rung, post: Poster, submitting: Submitting) -> tuple[Periodic, ...]:
    """The scheduler's entries. `store` is the main object store, where production captures
    live; `fetch` is the HTTP rung, for the fetch-method re-check; `post` sends webhooks;
    `submitting` is what the recurring schedules submit their jobs with (§22 "Recurring schedule storage")."""
    return (
        # A job its last expired lease ends is diffed as the worker would have.
        Periodic(
            "release_expired_leases",
            timedelta(minutes=1),
            partial(release_expired_leases, batch=LEASE_BATCH, ending=close_run),
            batch=LEASE_BATCH,
        ),
        Periodic(
            "fail_stalled_jobs",
            timedelta(minutes=1),
            partial(fail_stalled_jobs, batch=STALLED_BATCH),
            batch=STALLED_BATCH,
        ),
        Periodic(
            "expire_host_turns",
            timedelta(minutes=10),
            partial(expire_host_turns, batch=HOST_TURN_BATCH),
            batch=HOST_TURN_BATCH,
        ),
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
            "expire_webhooks",
            timedelta(hours=1),
            partial(expire_webhooks, batch=RETENTION_BATCH),
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
            "run_due_schedules",
            timedelta(seconds=10),
            partial(run_due_schedules, submitting=submitting, batch=SCHEDULE_BATCH),
            batch=SCHEDULE_BATCH,
        ),
        Periodic(
            "form_webhook_deliveries",
            timedelta(seconds=2),
            partial(form_deliveries, batch=FORM_BATCH),
            batch=FORM_BATCH,
        ),
        Periodic(
            "deliver_webhooks",
            timedelta(seconds=2),
            partial(deliver_webhooks, post=post, batch=DELIVERY_BATCH),
            batch=DELIVERY_BATCH,
        ),
    )


async def run_scheduler(settings: Settings, entries: Sequence[Periodic], stop: asyncio.Event) -> None:
    """Run `entries` until `stop` is set. An entry in progress finishes first."""
    engine = create_async_engine(settings.database_url.get_secret_value())
    clock = asyncio.get_running_loop().time
    due = [clock()] * len(entries)
    log.info("scheduler: started; entries %s", ", ".join(entry.name for entry in entries))
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
    # Most runs find nothing to do, and entries run every few seconds: only work done is logged at INFO.
    log.log(logging.INFO if result else logging.DEBUG, "scheduler: %s: %s", entry.name, result)
    return result
