"""The worker's learner (SPEC-08 §4.4 to §4.8, D-0624): run queued `learn` jobs, one at a time, beside the task loop.

A `learn` job has no `url_task`, so the task loop never claims one. The learner takes the oldest queued job
(`next_learn_job`) and runs it to its end (`run_learn_job`), which takes and commits its own transactions. Several
workers may poll at once: `run_learn_job` starts a job in one process only. An error outside a run (the database
gone) is logged, and the learner polls again.

A run makes role A calls of minutes each, so a stopping worker does not wait for it: the run is cancelled, and ends
as a failed run (`learning.SHUTDOWN`); the state learns again as after any failed run (SPEC-08 §4.8).
"""

import asyncio
import logging
from collections.abc import Coroutine
from contextlib import suppress
from datetime import timedelta
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.api_recipe.replay import Render, Replays
from crawlerai.config_ir.learning import next_learn_job, run_learn_job
from crawlerai.llm.client import LLMClient
from crawlerai.storage.base import ObjectStore

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
    replay: Replays | None,
    render: Render | None = None,
) -> None:
    """Run queued `learn` jobs until `stop` is set, which cancels the run in progress. `max_chars` is role A's HTML
    limit per page (`CRAWLERAI_LLM_A_MAX_CHARS`); `replay` sends the runs' recipe replays (SPEC-09 §4.6, §4.7), and
    `render` their browser renders (Appendix A #59)."""
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
                    replay=replay,
                    render=render,
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
