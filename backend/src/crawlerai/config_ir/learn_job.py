"""A `learn` job's lifecycle: from the queued job to an active config or a failed run.

The run reads the state's stored pages and hands them to the learning pipeline (`learning.learned`) as a `Learn`
request, or a `Locate` one when the job asks to locate or the state renders. What the pipeline validated is activated
(or left `pending_approval`) unless the run was overtaken meanwhile: its schema edited, its job cancelled or expired,
or an operator's config activated. A run takes two transactions, one to start the job and one to end it; none is open
while an LLM is called or a recipe replayed.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.memory import remembered
from crawlerai.acquire.types import RequestContext
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.activation import activate, store_pending
from crawlerai.config_ir.held_out import load_pages
from crawlerai.config_ir.learning import Hooks, Learn, Locate, Target, learned
from crawlerai.config_ir.model import ExtractionConfigIR
from crawlerai.config_ir.progressive import (
    LEARN_AFTER_PAGES,
    LocateRequest,
    NotLearning,
    StateKey,
    learning_failed,
    lock_state,
)
from crawlerai.config_ir.validation import Validated, ValidationReport
from crawlerai.core.redaction import REDACTED
from crawlerai.db.jobs import JOB_TRANSITIONS, lock_job, record_event, transition_job
from crawlerai.db.models import (
    ExtractionConfig,
    ExtractionConfigId,
    Job,
    JobId,
    JobStatus,
    ProgressiveState,
    Project,
    Site,
)
from crawlerai.db.queue import stuck_running_jobs
from crawlerai.llm.client import LLMClient, LLMFailure
from crawlerai.schemas import registry
from crawlerai.schemas.types import document_digest
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)

LEARNING_STARTED: Final = "learning_started"
LEARNING_FINISHED: Final = "learning_finished"
# The reason a run ends with when its schema was edited while it ran.
SCHEMA_EDITED: Final = "schema_edited"
# A run makes a few role A calls, each at most `llm.client.TIMEOUT_S["strong"]` per provider, plus a retry; a run still
# `running` an hour after it started has lost its process.
LEARN_RUN_TIMEOUT: Final = timedelta(hours=1)
# How many expired runs one scheduler turn ends; a full batch runs again at once (`scheduler.loop`).
EXPIRE_BATCH: Final = 100
EXPIRED: Final = "expired"
# The reason a completed run reports when its config waits for approval.
PENDING: Final = "pending_approval"
# The reason of a run cancelled because its worker stops (`run_learner`).
SHUTDOWN: Final = "shutdown"


@dataclass(frozen=True, slots=True)
class Learned:
    """How a run ended: the config it activated, or why it activated none."""

    config_id: ExtractionConfigId | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Locating:
    """What a started locate run asks for, the config its surface served, and the starting job's request context."""

    asked: LocateRequest
    serving: ExtractionConfigIR | None
    context: RequestContext | None


@dataclass(frozen=True, slots=True)
class _Run:
    """A started run: its state, what it learns for, the config the state served when it started, and what it
    locates when it is a locate run."""

    key: StateKey
    target: Target
    serving: ExtractionConfigId | None
    locating: _Locating | None

    @property
    def job_id(self) -> JobId:
        return self.target.job_id


async def next_learn_job(conn: AsyncConnection) -> JobId | None:
    """The oldest queued `learn` job, if any."""
    query = select(Job.id).where(Job.kind == "learn", Job.status == "queued").order_by(Job.id).limit(1)
    job_id: JobId | None = (await conn.execute(query)).scalar_one_or_none()
    return job_id


async def run_learn_job(
    engine: AsyncEngine,
    store: ObjectStore,
    client: LLMClient,
    job_id: JobId,
    *,
    vocabulary: Vocabulary,
    max_chars: int,
    hooks: Hooks,
) -> Learned | None:
    """Run the `learn` job `job_id` to its end and return how it ended; None when it is not queued (another process
    took it). `max_chars` is role A's HTML limit per page (`CRAWLERAI_LLM_A_MAX_CHARS`); `hooks` replay the run's
    recipes, whose replays count as its usage, and render and extract what it locates (`learning.Hooks`)."""
    try:
        async with engine.begin() as conn:
            run = await _start(conn, job_id)
    except Exception:  # a job that cannot start ends failed, or every poll would pick it again
        log.exception("learn job %s could not start", job_id)
        async with engine.begin() as conn:
            return await _abandon(conn, job_id, "error")
    if not isinstance(run, _Run):
        return run
    try:
        # The job is running and its row unlocked, so the bundle reads hold no lock anyone waits on.
        async with engine.connect() as conn:
            request = await _request(conn, store, run)
        validated = await learned(client, request, vocabulary, max_chars, hooks)
        async with engine.begin() as conn:
            return await _finish(conn, run, validated)
    except LLMFailure as e:
        async with engine.begin() as conn:
            return await _fail(conn, run, e.code)
    except asyncio.CancelledError:  # the worker stops: the run ends as one that cannot finish, then the cancel goes on
        async with engine.begin() as conn:
            await _abandon(conn, job_id, SHUTDOWN)
        raise
    except Exception:  # §4.8: a run that cannot finish leaves the state as a failed run would, never `learning`
        log.exception("learn job %s failed", job_id)
        async with engine.begin() as conn:
            return await _fail(conn, run, "error")


async def _start(conn: AsyncConnection, job_id: JobId) -> _Run | Learned | None:
    job = (
        await conn.execute(
            select(Job.status, Job.request, Job.cancel_requested)
            .where(Job.id == job_id, Job.kind == "learn")
            # One process starts the job: a second waits here, then sees it no longer queued.
            .with_for_update()
        )
    ).one_or_none()
    if job is None or job.status != "queued":
        return None
    key = StateKey.from_request(job.request)
    if job.cancel_requested:
        await learning_failed(conn, key)
        await transition_job(conn, job_id, "cancelled")
        return Learned(None, "cancelled")
    await transition_job(conn, job_id, "running")
    schema = await registry.get_by_id(conn, key.schema_id)
    host = (await conn.execute(select(Site.host).where(Site.id == key.site_id))).scalar_one()
    fetch = (await remembered(conn, key.site_id, key.page_kind, blocks=False)).method
    state = ProgressiveState
    found = (await conn.execute(select(state.active_config_id, state.render_mode).where(*key.where()))).one()
    await record_event(conn, job_id, LEARNING_STARTED)
    asked = StateKey.locate_of(job.request) or (LocateRequest() if found.render_mode != "off" else None)
    locating = None
    if asked is not None:
        serving = await _config_ir(conn, found.active_config_id)
        locating = _Locating(asked, serving, await _request_context(conn, asked))
    return _Run(key, Target(schema, host, fetch, job_id), found.active_config_id, locating)


async def _request(conn: AsyncConnection, store: ObjectStore, run: _Run) -> Learn | Locate:
    """The pipeline's request for a started run: the state's stored pages, and a locate run's surface."""
    schema = run.target.schema
    pages = await load_pages(conn, store, run.key.site_id, schema, limit=LEARN_AFTER_PAGES)
    learn = Learn(run.target, pages)
    if run.locating is None:
        return learn
    surface = pages
    # A listing's pages that listed nothing are the surface's too: a locate run renders them.
    if schema.page_kind == "listing":
        surface = await load_pages(conn, store, run.key.site_id, schema, limit=LEARN_AFTER_PAGES, listed_nothing=True)
    locating = run.locating
    return Locate(learn, locating.asked.fields, surface, locating.serving, locating.context)


async def _config_ir(conn: AsyncConnection, config_id: ExtractionConfigId | None) -> ExtractionConfigIR | None:
    if config_id is None:
        return None
    ir: dict[str, Any] = (
        await conn.execute(select(ExtractionConfig.ir).where(ExtractionConfig.id == config_id))
    ).scalar_one()
    return ExtractionConfigIR.model_validate(ir)


async def _request_context(conn: AsyncConnection, located: LocateRequest) -> RequestContext | None:
    """The headers of the request context of the job that started the locate run, as its stored request keeps them
    (an asynchronous job's keeps the values while it runs; a redacted one is none)."""
    if located.job_id is None:
        return None
    request: dict[str, Any] | None = (
        await conn.execute(select(Job.request).where(Job.id == located.job_id))
    ).scalar_one_or_none()
    fetch = (request or {}).get("fetch") or {}
    headers = fetch.get("headers") or {}
    kept = tuple(
        (name, SecretStr(value)) for name, value in headers.items() if isinstance(value, str) and value != REDACTED
    )
    return RequestContext(headers=kept) if kept else None


async def expire_learn_runs(conn: AsyncConnection, *, batch: int) -> int:
    """End up to `batch` runs that started more than `LEARN_RUN_TIMEOUT` ago as failed runs, and return how many: their
    process died, and the state would otherwise stay `learning`."""
    job_ids = await stuck_running_jobs(conn, kinds=("learn",), older_than=LEARN_RUN_TIMEOUT, batch=batch)
    for job_id in job_ids:
        await _abandon(conn, job_id, EXPIRED)
    return len(job_ids)


async def _abandon(conn: AsyncConnection, job_id: JobId, reason: str) -> Learned:
    """End a run that will not finish: its state as a failed run leaves it, and its job `failed`. A run that
    ended meanwhile is left as it ended: a stopping worker's cancel can come as the run's final transaction commits."""
    job = await lock_job(conn, job_id, Job.status, Job.request)
    if not JOB_TRANSITIONS[job.status]:
        return Learned(None, reason)
    if job.status == "queued":  # it failed to start: a job ends `failed` only from `running`
        await transition_job(conn, job_id, "running")
    # The state may have moved on already (an operator's config, a cancel), and then there is no run to end; a request
    # that names no state has none either, and its job still ends, or every poll would pick it again.
    with suppress(NotLearning, ValidationError):
        await learning_failed(conn, StateKey.from_request(job.request))
    await _end(conn, job_id, "failed", config_id=None, reason=reason, report=None)
    return Learned(None, reason)


async def _finish(conn: AsyncConnection, run: _Run, validated: Validated) -> Learned:
    await lock_state(conn, run.key)
    job = (await conn.execute(select(Job.status, Job.cancel_requested).where(Job.id == run.job_id))).one()
    if job.status != "running":  # `expire_learn_runs` gave the run up and ended it
        return Learned(None, EXPIRED)
    if await _schema_edited(conn, run):
        return await _edited(conn, run, validated.report)
    if job.cancel_requested:
        return await _fail(conn, run, "cancelled", validated.report, status="cancelled")
    if validated.ir is None:
        return await _fail(conn, run, validated.report.refused or "refused", validated.report)
    if await _operator_since(conn, run):
        return await _fail(conn, run, "operator_config", validated.report)
    if await _requires_approval(conn, run):
        config_id = await store_pending(conn, run.key, validated)
        await _end(conn, run.job_id, "completed", config_id=config_id, reason=PENDING, report=validated.report)
        return Learned(config_id, PENDING)
    config_id = await activate(conn, run.key, validated)
    await _end(conn, run.job_id, "completed", config_id=config_id, reason=None, report=validated.report)
    return Learned(config_id)


async def _requires_approval(conn: AsyncConnection, run: _Run) -> bool:
    """Whether the site's project makes a learned config wait for approval."""
    project = select(Site.project_id).where(Site.id == run.key.site_id).scalar_subquery()
    query = select(Project.require_config_approval).where(Project.id == project)
    return bool((await conn.execute(query)).scalar_one())


async def _operator_since(conn: AsyncConnection, run: _Run) -> bool:
    """Whether an operator's config became active while the run was in flight: the operator wrote it knowing
    the pages the run learns from, so the run does not replace it."""
    state, configs = ProgressiveState, ExtractionConfig
    query = (
        select(configs.origin)
        .join(state, state.active_config_id == configs.id)
        .where(*run.key.where(), configs.id.is_distinct_from(run.serving))
    )
    return (await conn.execute(query)).scalar_one_or_none() == "operator"


async def _schema_edited(conn: AsyncConnection, run: _Run) -> bool:
    """Whether the schema was edited since the run started: what it learned is for another document, and the edit
    already sent the state back to `cold` (`progressive.relearn_schema`), where a later run may now be in flight."""
    current = await registry.get_by_id(conn, run.key.schema_id)
    return document_digest(current) != document_digest(run.target.schema)


async def _edited(conn: AsyncConnection, run: _Run, report: ValidationReport | None) -> Learned:
    """End a run its schema's edit overtook, leaving the state, and any run started since, as they are."""
    await _end(conn, run.job_id, "failed", config_id=None, reason=SCHEMA_EDITED, report=report)
    return Learned(None, SCHEMA_EDITED)


async def _fail(
    conn: AsyncConnection,
    run: _Run,
    reason: str,
    report: ValidationReport | None = None,
    *,
    status: JobStatus = "failed",
) -> Learned:
    await lock_state(conn, run.key)
    if await _schema_edited(conn, run):
        return await _edited(conn, run, report)
    await learning_failed(conn, run.key)
    await _end(conn, run.job_id, status, config_id=None, reason=reason, report=report)
    return Learned(None, reason)


async def _end(
    conn: AsyncConnection,
    job_id: JobId,
    status: JobStatus,
    *,
    config_id: ExtractionConfigId | None,
    reason: str | None,
    report: ValidationReport | None,
) -> None:
    payload = {
        "config_id": None if config_id is None else str(config_id),
        "reason": reason,
        "report": None if report is None else report.model_dump(mode="json"),
    }
    await record_event(conn, job_id, LEARNING_FINISHED, payload)
    await transition_job(conn, job_id, status)
