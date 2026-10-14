"""The worker's learner (SPEC-08 §4.4 to §4.8, D-0624): run queued `learn` jobs, one at a time, beside the task loop.

A `learn` job has no `url_task`, so the task loop never claims one. The learner takes the oldest queued job
(`next_learn_job`) and runs it to its end (`run_learn_job`), which takes and commits its own transactions. Several
workers may poll at once: `run_learn_job` starts a job in one process only. An error outside a run (the database
gone) is logged, and the learner polls again.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncEngine

from crawlerai.collect.schema_org_map import Vocabulary
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
) -> None:
    """Run queued `learn` jobs until `stop` is set; the run in progress finishes first. `max_chars` is role A's HTML
    limit per page (`CRAWLERAI_LLM_A_MAX_CHARS`)."""
    while not stop.is_set():
        try:
            async with engine.connect() as conn:
                job_id = await next_learn_job(conn)
            if job_id is not None:
                await run_learn_job(engine, store, client, job_id, vocabulary=vocabulary, max_chars=max_chars)
                continue
        except Exception:
            log.exception("learner: polling for learn jobs failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), LEARN_POLL.total_seconds())
