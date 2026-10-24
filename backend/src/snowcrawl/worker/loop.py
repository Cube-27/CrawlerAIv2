"""The worker process: claim tasks, run each with the handler of its job's kind, record the
result. Handlers are registered by later specs.

A worker runs up to `TASK_SLOTS` tasks at once, and claims only as many as it has free slots, so a claimed task never
waits behind others while its lease runs. Pages of one host still go at the host's rate: every task fetches through the
process's one `HostLimiter`, whose turns and holds every process shares through the database, and which postpones a task
whose turn is far off.

A task runs in two parts (`TaskHandler`). Its fetch, and what it reads and learns around it, run first, outside any
transaction of the task: each read or write there, site memory's included (`acquire.memory`), commits in a short
transaction of its own, so no task holds a site's rows while it fetches or extracts. Then its writes run in one
transaction: they and the task's result commit together, or not at all (a lost lease, an exception). An exception is
recorded on the task as a transient failure, and the loop continues. A task still running at `TASK_DEADLINE` is
cancelled and recorded as failed (`DEADLINE`), so no page holds its job open; one whose cancellation does not end within
`CANCEL_GRACE` is left behind, the session of its transaction, if one is open, ended (PostgreSQL rolls it back,
releasing its row locks), and its failure recorded all the same, before its lease can expire: the task is never claimed
again while work left behind runs, and that work sends no further request (`HostLimiter.admit`).

Database errors outside a handler propagate, including one raised while recording a handler's exception, which
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
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import timedelta
from functools import partial
from typing import Final, assert_never

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from snowcrawl.acquire.shared_browser import BROWSER_CONTEXTS
from snowcrawl.core.settings import Settings
from snowcrawl.db.models import Job, JobKind
from snowcrawl.db.queue import (
    TASK_DEADLINE,
    ClaimedTask,
    Failed,
    Finished,
    JobEnding,
    LeaseLost,
    Postpone,
    Skipped,
    TaskResult,
    cancel_task,
    claim_tasks,
    fail_task,
    release_task,
    settle_task,
)

log = logging.getLogger(__name__)

# Tasks a worker runs at once, set by its browser's capacity (owner plan 2026-10-19, P1): at most `BROWSER_CONTEXTS`
# render at once, and a task mostly waits (on the network, an LLM), so twice that keeps every context busy while as many
# other tasks fetch over HTTP or extract.
TASK_SLOTS: Final = 2 * BROWSER_CONTEXTS
IDLE_POLL: Final = timedelta(seconds=1)
# How long a task cancelled at its deadline may take to wind down (a browser context closing) before it is left.
CANCEL_GRACE: Final = timedelta(seconds=15)
DEADLINE: Final = "timeout: the task ran past its deadline"
# How long recording a task's deadline failure waits for a row lock. Work left behind holds none (its session is ended);
# another task's transaction ends within this: it commits, or is cancelled, or left behind, at its own deadline. A
# claim's deadline, grace and this wait end well inside its `LEASE`, so the failure lands while the claim holds.
_LOCK_WAIT: Final = TASK_DEADLINE + CANCEL_GRACE + timedelta(seconds=10)
# An absolute URI: an RFC 3986 §3.1 scheme followed by "://" and everything up to the next whitespace.
URL: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


# A task's writes, run in its transaction: they return the result it ends this run with.
Settle = Callable[[AsyncConnection], Awaitable[TaskResult]]
# A job kind's handler: runs the task up to its writes outside any transaction of the task, through the engine (its
# fetch; every read and write there in a short transaction of its own), and returns its writes, or the result it ends
# with when it has none.
TaskHandler = Callable[[ClaimedTask, AsyncEngine], Awaitable[Settle | TaskResult]]


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
    # Two connections per slot (a task's transaction, and a short one of site memory's beside it), one for claiming,
    # and one to record a result beside a task left behind.
    engine = create_async_engine(settings.database_url.get_secret_value(), pool_size=2 * TASK_SLOTS + 2)
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
                    finished.result()  # a database error outside a handler ends the worker
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
    """Run `task`; at `TASK_DEADLINE`, cancel it and record it as failed (`DEADLINE`)."""
    work = asyncio.create_task(_run(engine, task, handlers, ending, redact_urls=redact_urls))
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
    try:
        async with engine.begin() as conn:
            if not done:
                # Its transaction, if one is open, rolls back as its session ends, and its next database call fails;
                # work not yet in its transaction finds the task failed as it records a result, and rolls back.
                await conn.execute(_END_SESSION, {"name": _session_name(task)})
            # A lock another task's transaction holds is waited for only so long (`_LOCK_WAIT`); past it, the task is
            # left to its lease's expiry.
            await conn.execute(text(f"SET LOCAL lock_timeout = {int(_LOCK_WAIT.total_seconds() * 1000)}"))
            await fail_task(conn, task, DEADLINE, transient=False, exhausted="timeout", ending=ending)
    except LeaseLost:
        pass
    except DBAPIError:
        log.exception("url_task %s: its failure was not recorded; its lease will expire", task.id)


# The tasks left running past their deadline and cancellation (`_run_within_deadline`): referenced until they end,
# since the event loop keeps only weak references to tasks.
_LEFT_BEHIND: set[asyncio.Task[None]] = set()
# The session whose open transaction runs a claim (`_session_name`), ended: a session of the same role may be.
_END_SESSION: Final = text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name = :name")


def _session_name(task: ClaimedTask) -> str:
    """The `application_name` a claim's transaction runs under (SET LOCAL: the pooled session drops it at the end), so
    that its work, if left behind, can be found; at most 63 characters (NAMEDATALEN)."""
    return f"url_task {task.id.hex} {int(task.lease_until.timestamp() * 1_000_000)}"


async def _run(
    engine: AsyncEngine,
    task: ClaimedTask,
    handlers: Mapping[JobKind, TaskHandler],
    ending: JobEnding | None,
    *,
    redact_urls: bool,
) -> None:
    try:
        kind, settle = await _prepare(engine, task, handlers)
        async with _transaction(engine, task) as conn:
            await _record(conn, task, kind, await settle(conn), ending, redact_urls=redact_urls)
    except LeaseLost:
        log.warning("url_task %s: lease lost; its work was rolled back", task.id)
    except Exception as error:
        message = _error_text(f"{type(error).__name__}: {error}", redact_urls=redact_urls)
        log.warning("url_task %s: %s", task.id, message)
        with suppress(LeaseLost):
            async with _transaction(engine, task) as conn:
                await fail_task(conn, task, message, transient=True, ending=ending)


@asynccontextmanager
async def _transaction(engine: AsyncEngine, task: ClaimedTask) -> AsyncIterator[AsyncConnection]:
    """A transaction of the task's, under its session name (`_session_name`)."""
    async with engine.connect() as conn, conn.begin():
        await conn.execute(select(func.set_config("application_name", _session_name(task), True)))
        yield conn


async def _prepare(
    engine: AsyncEngine, task: ClaimedTask, handlers: Mapping[JobKind, TaskHandler]
) -> tuple[JobKind, Settle]:
    """The task's job kind and its writes: its handler's, run up to them; none of a cancelled job's task (`Skipped`)."""
    async with engine.connect() as conn:
        job = (await conn.execute(select(Job.kind, Job.cancel_requested).where(Job.id == task.job_id))).one()
    handler = handlers.get(job.kind)
    prepared: Settle | TaskResult
    if job.cancel_requested:
        prepared = Skipped()
    elif handler is None:
        prepared = Failed(f"no handler for job kind {job.kind!r}", transient=False)
    else:
        prepared = await handler(task, engine)
    return job.kind, prepared if callable(prepared) else partial(_ended, prepared)


async def _ended(result: TaskResult, _conn: AsyncConnection) -> TaskResult:
    return result


async def _record(
    conn: AsyncConnection,
    task: ClaimedTask,
    kind: JobKind,
    result: TaskResult,
    ending: JobEnding | None,
    *,
    redact_urls: bool,
) -> None:
    """Record the task's `result`."""
    match result:
        case Finished(outcome):
            await settle_task(conn, task, result, ending=ending)
            # The task's id and job, never its URL, which `SNOWCRAWL_LOG_REDACT_URLS` may keep out of the logs.
            log.info("url_task %s: %s task of job %s: %s", task.id, kind, task.job_id, outcome)
        case Failed(error):
            text = _error_text(error, redact_urls=redact_urls)
            await settle_task(conn, task, replace(result, error=text), ending=ending)
            log.warning("url_task %s: %s task of job %s: failed: %s", task.id, kind, task.job_id, text)
        case Postpone(after):
            await release_task(conn, task, after=after)
        case Skipped():
            await cancel_task(conn, task, ending=ending)
        case unreachable:
            assert_never(unreachable)


def _error_text(text: str, *, redact_urls: bool) -> str:
    return URL.sub("<url>", text) if redact_urls else text
