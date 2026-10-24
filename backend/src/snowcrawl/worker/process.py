"""The worker process: the task loop (`worker.loop`) and, with the engine's data files, the learner (`worker.learn`)
beside it, on one runtime."""

import asyncio

from snowcrawl.config_ir.learning import Hooks
from snowcrawl.core.settings import Settings
from snowcrawl.recurring.listing_diff import close_run
from snowcrawl.services.fetching import learning_replay
from snowcrawl.services.page_store import learning_extract
from snowcrawl.services.runtime import Runtime
from snowcrawl.services.scrape_paging import learning_render
from snowcrawl.worker.handlers.table import task_handlers
from snowcrawl.worker.learn import run_learner
from snowcrawl.worker.loop import run_worker


async def work(settings: Settings, runtime: Runtime, stop: asyncio.Event) -> None:
    """Run the worker on `runtime` until `stop` is set."""
    fetching, data, llm = runtime.fetching, runtime.engine_data, runtime.llm
    handlers = task_handlers(fetching, data, runtime.drift_margins, llm=llm)
    # A records crawl that completes is diffed against its earlier runs.
    running = [run_worker(settings, handlers, stop, ending=close_run)]
    if data is not None:  # learning reads the vocabulary from the data files
        learner = run_learner(
            runtime.database,
            fetching.store,
            llm,
            stop,
            vocabulary=data.vocabulary,
            max_chars=settings.llm_a_max_chars,
            hooks=Hooks(
                learning_replay(runtime.database, fetching),
                learning_render(runtime.database, fetching),
                learning_extract(data, llm),
            ),
        )
        running.append(learner)
    await asyncio.gather(*running)
