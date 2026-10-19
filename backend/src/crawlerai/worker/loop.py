"""The worker process (persistence-storage spec): claim tasks, run each with the handler of its job's kind, record the
result. Handlers are registered by later specs.

A worker runs up to `TASK_SLOTS` tasks at once, each on its own connection, and claims only as many as it has free
slots, so a claimed task never waits behind others while its lease runs. Pages of one host still go at the host's
rate: every task fetches through the process's one `HostLimiter`, which postpones a task whose turn is far off.

Each task runs in one transaction: the handler's writes and the task's result commit together, or not at all (a lost
lease, an exception). An exception is recorded on the task as a transient failure, and the loop continues. A task
still running at `TASK_DEADLINE` is cancelled and recorded as failed (`DEADLINE`), so no page holds its job open;
one whose cancellation does not end within `CANCEL_GRACE` is left behind, its result recorded all the same.

Database errors outside a handler propagate (§4.8), including one raised while recording a handler's exception, which
usually means the connection is gone: `run_worker` raises and the process exits. Nothing is lost: the tasks it still
had claimed, the one that failed included, go back to the queue when the scheduler finds their leases expired
(`release_expired_leases`), each counted as a transient failure.
"""

import asyncio
import logging
import os
import re
import secrets
import socket
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import Final, assert_never

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from crawlerai.core.settings import Settings
from crawlerai.db.models import CaptureId, FinishedOutcome, Job, JobKind, TaskOutcome
from crawlerai.db.queue import (
    LEASE,
    ClaimedTask,
    JobEnding,
    LeaseLost,
    cancel_task,
    claim_tasks,
    complete_task,
    fail_task,
    release_task,
    retried,
)

log = logging.getLogger(__name__)

# Tasks a worker runs at once. A task mostly waits (on the network, the browser, an LLM), so a few overlap well on one
# core; the browser's own limit (`BROWSER_CONTEXTS`) bounds how many render at once.
TASK_SLOTS: Final = 4
IDLE_POLL: Final = timedelta(seconds=1)
# A task's wall-clock limit: its result is recorded while its claim still holds the lease (`LEASE`), so no other worker
# runs it again meanwhile. It covers a host's turn waited for in place (`QUEUED`, half the lease) and the work after.
TASK_DEADLINE: Final = LEASE - timedelta(minutes=1)
# How long a task cancelled at its deadline may take to wind down (a browser context closing) before it is left.
CANCEL_GRACE: Final = timedelta(seconds=15)
DEADLINE: Final = "timeout: the task ran past its deadline"
# An absolute URI: an RFC 3986 §3.1 scheme followed by "://" and everything up to the next whitespace.
URL: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


@dataclass(frozen=True)
class Finished:
    outcome: FinishedOutcome
    reason: str | None = None  # why, when the outcome alone does not say: a `blocked` task's `robots`
    capture_id: CaptureId | None = None  # the page the task fetched, if it fetched one


@dataclass(frozen=True)
class Failed:
    """A failure (`fail_task`). `after` is the delay the target asked for before a retry (a `Retry-After`, acquisition
    spec §4.6); `exhausted` the outcome once no attempt is left; `capture_id` the page the attempt fetched, if any."""

    error: str
    transient: bool
    after: timedelta | None = None
    exhausted: TaskOutcome = "failed"
    capture_id: CaptureId | None = None


@dataclass(frozen=True)
class Postpone:
    """The task did not run, because its site is not admitted yet (acquisition spec): run it `after` from now, without
    spending an attempt. The worker moves on instead of sleeping."""

    after: timedelta


@dataclass(frozen=True)
class Skipped:
    """The task is not run, because its job no longer needs it: a scored crawl that spent its page limit."""


TaskResult = Finished | Failed | Postpone | Skipped
TaskHandler = Callable[[ClaimedTask, AsyncConnection], Awaitable[TaskResult]]


def ends_task(task: ClaimedTask, result: TaskResult) -> bool:
    """Whether `result` ends `task`, rather than leaving it to run again: postponed, or failed and retried."""
    match result:
        case Postpone():
            return False
        case Failed(transient=transient):
            return not retried(task, transient=transient)
        case _:
            return True


async def run_worker(
    settings: Settings,
    handlers: Mapping[JobKind, TaskHandler],
    stop: asyncio.Event,
    *,
    ending: JobEnding | None = None,
) -> None:
    """Work until `stop` is set; the tasks in progress then finish (each within its deadline). `ending` runs as a
    task's result ends its job (`settle_job`)."""
    worker = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
    # A connection per slot, one for claiming, and one to record a result beside a task left behind.
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_size=TASK_SLOTS + 2)
    log.info("worker %s: started; job kinds %s", worker, ", ".join(sorted(handlers)))
    running: set[asyncio.Task[None]] = set()
    stopping = asyncio.ensure_future(stop.wait())
    run = partial(_run_within_deadline, engine, handlers=handlers, ending=ending, redact_urls=settings.log_redact_urls)
    try:
        async with engine.connect() as conn:
            while not stop.is_set():
                free = TASK_SLOTS - len(running)
                tasks: list[ClaimedTask] = []
                if free:
                    async with conn.begin():
                        tasks = await claim_tasks(conn, worker, free)
                running.update(asyncio.create_task(run(task)) for task in tasks)
                if tasks and len(running) < TASK_SLOTS:
                    continue  # more may be due
                done, _ = await asyncio.wait(
                    {*running, stopping}, timeout=IDLE_POLL.total_seconds(), return_when=asyncio.FIRST_COMPLETED
                )
                running -= done
                for finished in done - {stopping}:
                    finished.result()  # a database error outside a handler ends the worker (§4.8)
        await asyncio.gather(*running)
    finally:
        stopping.cancel()
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await engine.dispose()
        log.info("worker %s: stopped", worker)


async def _run_within_deadline(
    engine: AsyncEngine,
    task: ClaimedTask,
    *,
    handlers: Mapping[JobKind, TaskHandler],
    ending: JobEnding | None,
    redact_urls: bool,
) -> None:
    """Run `task` on a connection of its own; at `TASK_DEADLINE`, cancel it and record it as failed (`DEADLINE`)."""

    async def run() -> None:
        async with engine.connect() as conn:
            await _run(conn, task, handlers, ending, redact_urls=redact_urls)

    work = asyncio.create_task(run())
    try:
        done, _ = await asyncio.wait({work}, timeout=TASK_DEADLINE.total_seconds())
    except asyncio.CancelledError:  # the worker is stopping at once: the task goes with it
        work.cancel()
        raise
    if done:
        return work.result()
    work.cancel()
    done, _ = await asyncio.wait({work}, timeout=CANCEL_GRACE.total_seconds())
    if done and not work.cancelled() and (error := work.exception()) is not None:
        log.warning("url_task %s: %s while it was cancelled", task.id, type(error).__name__)
    if not done:
        _LEFT_BEHIND.add(work)
        work.add_done_callback(_LEFT_BEHIND.discard)
        log.error("url_task %s: did not stop when cancelled at its deadline; left behind", task.id)
    log.warning("url_task %s: %s", task.id, DEADLINE)
    with suppress(LeaseLost):
        async with engine.begin() as conn:
            await fail_task(conn, task, DEADLINE, transient=False, ending=ending)


# The tasks left running past their deadline and cancellation (`_run_within_deadline`): referenced until they end,
# since the event loop keeps only weak references to tasks.
_LEFT_BEHIND: set[asyncio.Task[None]] = set()


async def _run(
    conn: AsyncConnection,
    task: ClaimedTask,
    handlers: Mapping[JobKind, TaskHandler],
    ending: JobEnding | None,
    *,
    redact_urls: bool,
) -> None:
    try:
        async with conn.begin():
            await _execute(conn, task, handlers, ending, redact_urls=redact_urls)
    except LeaseLost:
        log.warning("url_task %s: lease lost; its work was rolled back", task.id)
    except Exception as error:
        message = _error_text(f"{type(error).__name__}: {error}", redact_urls=redact_urls)
        log.warning("url_task %s: %s", task.id, message)
        with suppress(LeaseLost):
            async with conn.begin():
                await fail_task(conn, task, message, transient=True, ending=ending)


async def _execute(
    conn: AsyncConnection,
    task: ClaimedTask,
    handlers: Mapping[JobKind, TaskHandler],
    ending: JobEnding | None,
    *,
    redact_urls: bool,
) -> None:
    job = (await conn.execute(select(Job.kind, Job.cancel_requested).where(Job.id == task.job_id))).one()
    if job.cancel_requested:
        await cancel_task(conn, task, ending=ending)
        return
    handler = handlers.get(job.kind)
    if handler is None:
        await fail_task(conn, task, f"no handler for job kind {job.kind!r}", transient=False, ending=ending)
        return
    # A task can run for minutes (a crawl's start reads the site's sitemaps); its start shows what the worker is on.
    log.info("url_task %s: %s task of job %s: running", task.id, job.kind, task.job_id)
    match await handler(task, conn):
        case Finished(outcome, reason, capture_id):
            await complete_task(conn, task, outcome, reason=reason, capture_id=capture_id, ending=ending)
            # The task's id and job, never its URL, which `CRAWLERAI_LOG_REDACT_URLS` may keep out of the logs.
            log.info("url_task %s: %s task of job %s: %s", task.id, job.kind, task.job_id, outcome)
        case Failed(error, transient, after, exhausted, capture_id):
            text = _error_text(error, redact_urls=redact_urls)
            await fail_task(
                conn,
                task,
                text,
                transient=transient,
                after=after,
                exhausted=exhausted,
                capture_id=capture_id,
                ending=ending,
            )
            log.warning("url_task %s: %s task of job %s: failed: %s", task.id, job.kind, task.job_id, text)
        case Postpone(after):
            await release_task(conn, task, after=after)
        case Skipped():
            await cancel_task(conn, task, ending=ending)
        case unreachable:
            assert_never(unreachable)


def _error_text(text: str, *, redact_urls: bool) -> str:
    return URL.sub("<url>", text) if redact_urls else text
