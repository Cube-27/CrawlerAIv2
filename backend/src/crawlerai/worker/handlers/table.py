"""The worker's task handlers, one per job kind that has tasks.

Every records job extracts its pages as a scrape does (a batch's handler is the scrape's steps), so
every handler binds role C on the worker's client, charged to the task's job and bounded by the job's `llm_calls`
budget.
"""

from crawlerai.config_ir.drift import DriftMargins
from crawlerai.db.models import JobKind
from crawlerai.llm.client import LLMClient
from crawlerai.resolve.pipeline import EngineData
from crawlerai.services.fetching import Fetching
from crawlerai.worker.handlers.crawl import crawl_handler
from crawlerai.worker.handlers.scrape import scrape_handler
from crawlerai.worker.loop import TaskHandler


def task_handlers(
    fetching: Fetching, data: EngineData | None, margins: DriftMargins | None, *, llm: LLMClient
) -> dict[JobKind, TaskHandler]:
    """The handler of each job kind with tasks, for a worker that fetches with `fetching`; `data` is None in a worker
    without the engine's data files, whose records tasks then fail. `margins` decide drift suspensions; role C runs on
    `llm`."""
    # An extract job's tasks run as a records batch's do (`worker.handlers.scrape`).
    scrape = scrape_handler(fetching, data, margins, llm=llm)
    return {"batch_scrape": scrape, "crawl": crawl_handler(fetching, data, margins, llm=llm), "extract": scrape}
