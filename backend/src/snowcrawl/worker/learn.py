"""The worker's learner: run queued `learn` jobs, one at a time, beside the task loop.

A `learn` job has no `url_task`, so the task loop never claims one. The learner takes the oldest queued job
(`next_learn_job`) and runs it to its end (`run_learn_job`), which takes and commits its own transactions. Several
workers may poll at once: `run_learn_job` starts a job in one process only. An error outside a run (the database
gone) is logged, and the learner polls again.

A run makes role A calls of minutes each, so a stopping worker does not wait for it: the run is cancelled, and ends
as a failed run (`learn_job.SHUTDOWN`); the state learns again as after any failed run.
"""

import asyncio
import logging
from collections.abc import Coroutine
from contextlib import suppress
from datetime import timedelta
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncEngine

from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.config_ir.learn_job import next_learn_job, run_learn_job
from snowcrawl.config_ir.learning import Hooks
from snowcrawl.llm.client import LLMClient
from snowcrawl.storage.base import ObjectStore

log = logging.getLogger(__name__)

# Learn jobs are rare: the scheduler starts them once a minute (`trigger_learning`), so the learner polls at half that.
LEARN_POLL: Final = timedelta(seconds=30)


async def run_learner(
    engine: AsyncEngine,
    store: ObjectStore,
    client: LLMClient,
    stop: asyncio.Event,
    *,
    vocabulary: Vocabulary,
    max_chars: int,
    hooks: Hooks,
) -> None:
    """Run queued `learn` jobs until `stop` is set, which cancels the run in progress. `max_chars` is role A's HTML
    limit per page (`SNOWCRAWL_LLM_A_MAX_CHARS`); `hooks` send the runs' recipe replays and browser renders,
    and extract a locate run's renders."""
    while not stop.is_set():
        try:
            async with engine.connect() as conn:
                job_id = await next_learn_job(conn)
            if job_id is not None:
                run = run_learn_job(
                    engine,
                    store,
                    client,
                    job_id,
                    vocabulary=vocabulary,
                    max_chars=max_chars,
                    hooks=hooks,
                )
                await _until_stopped(run, stop)
                continue
        except Exception:
            log.exception("learner: polling for learn jobs failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), LEARN_POLL.total_seconds())


async def _until_stopped(work: Coroutine[Any, Any, object], stop: asyncio.Event) -> None:
    """Run `work` to its end, or until `stop` is set, which cancels it; then wait for it to wind down."""
    running = asyncio.ensure_future(work)
    stopping = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait((running, stopping), return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopping.cancel()
    running.cancel()  # no effect once it has ended
    with suppress(asyncio.CancelledError):
        await running
