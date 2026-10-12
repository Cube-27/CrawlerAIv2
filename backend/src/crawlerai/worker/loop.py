"""The worker process (SPEC-01 §4.3, §4.8): claim tasks, run each with the handler of its job's kind, record the
result. Handlers are registered by later specs.

Each task runs in one transaction: the handler's writes and the task's result commit together, or not at all (a lost
lease, an exception). An exception is recorded on the task as a transient failure, and the loop continues.
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
from typing import Final, assert_never

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from crawlerai.core.settings import Settings
from crawlerai.db.models import FinishedOutcome, Job, JobKind
from crawlerai.db.queue import ClaimedTask, LeaseLost, cancel_task, claim_tasks, complete_task, fail_task, release_task

log = logging.getLogger(__name__)

CLAIM_BATCH: Final = 10
IDLE_POLL: Final = timedelta(seconds=1)
# An absolute URI: an RFC 3986 §3.1 scheme followed by "://" and everything up to the next whitespace.
URL: Final = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")


@dataclass(frozen=True)
class Finished:
    outcome: FinishedOutcome


@dataclass(frozen=True)
class Failed:
    error: str
    transient: bool


TaskResult = Finished | Failed
TaskHandler = Callable[[ClaimedTask, AsyncConnection], Awaitable[TaskResult]]


async def run_worker(settings: Settings, handlers: Mapping[JobKind, TaskHandler], stop: asyncio.Event) -> None:
    """Work until `stop` is set. The task in progress finishes; claimed tasks that have not started go back."""
    worker = f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(4)}"
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with engine.connect() as conn:
            while not stop.is_set():
                async with conn.begin():
                    tasks = await claim_tasks(conn, worker, CLAIM_BATCH)
                if not tasks:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), IDLE_POLL.total_seconds())
                for index, task in enumerate(tasks):
                    if stop.is_set():
                        await _release(conn, tasks[index:])
                        break
                    await _run(conn, task, handlers, redact_urls=settings.log_redact_urls)
    finally:
        await engine.dispose()


async def _run(
    conn: AsyncConnection, task: ClaimedTask, handlers: Mapping[JobKind, TaskHandler], *, redact_urls: bool
) -> None:
    try:
        async with conn.begin():
            await _execute(conn, task, handlers, redact_urls=redact_urls)
    except LeaseLost:
        log.warning("url_task %s: lease lost; its work was rolled back", task.id)
    except Exception as error:
        message = _error_text(f"{type(error).__name__}: {error}", redact_urls=redact_urls)
        log.warning("url_task %s: %s", task.id, message)
        with suppress(LeaseLost):
            async with conn.begin():
                await fail_task(conn, task, message, transient=True)


async def _execute(
    conn: AsyncConnection, task: ClaimedTask, handlers: Mapping[JobKind, TaskHandler], *, redact_urls: bool
) -> None:
    job = (await conn.execute(select(Job.kind, Job.cancel_requested).where(Job.id == task.job_id))).one()
    if job.cancel_requested:
        await cancel_task(conn, task)
        return
    handler = handlers.get(job.kind)
    if handler is None:
        await fail_task(conn, task, f"no handler for job kind {job.kind!r}", transient=False)
        return
    match await handler(task, conn):
        case Finished(outcome):
            await complete_task(conn, task, outcome)
        case Failed(error, transient):
            await fail_task(conn, task, _error_text(error, redact_urls=redact_urls), transient=transient)
        case unreachable:
            assert_never(unreachable)


async def _release(conn: AsyncConnection, tasks: list[ClaimedTask]) -> None:
    for task in tasks:
        with suppress(LeaseLost):
            async with conn.begin():
                await release_task(conn, task)


def _error_text(text: str, *, redact_urls: bool) -> str:
    return URL.sub("<url>", text) if redact_urls else text
