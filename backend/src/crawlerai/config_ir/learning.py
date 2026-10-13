"""The learning run (SPEC-08 §4.4 to §4.8, ARCHITECTURE §8.3): what a `learn` job does, from a state's stored pages to
an active config or a failed run.

A run reads the state's `LEARN_AFTER_PAGES` most recent extracted pages (`held_out.load_pages`, §4.4). The
`SAMPLE_PAGES` with the most published required values are the learning sample, and the rest are held out. Induction
proposes selectors without an LLM (§4.5), role A synthesizes the fields it left (§4.6), and the config is validated on
the held-out pages (§4.7) and activated (§4.8). Every other end is a failed run (`progressive.learning_failed`):
validation refusing the config, an LLM failure (D-0588), a cancelled job, an error, or an operator's config activated
while the run was in flight, which a run that started before it does not replace.

A run takes two transactions: one starts the job, one ends it; the pages are read between them. None is open while
role A is called, because the LLM client commits usage on a connection of its own and must not wait on a write to the
job's row (D-0346). The job's start and end are recorded as `learning_started` and `learning_finished` events
(SPEC-10 §4.2).
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.activation import activate
from crawlerai.config_ir.held_out import StoredPage, load_pages
from crawlerai.config_ir.induction import Induction, SamplePage, induce
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, Provenance, SchemaRef
from crawlerai.config_ir.progressive import LEARN_AFTER_PAGES, StateKey, learning_failed, lock_state
from crawlerai.config_ir.synthesis import synthesize
from crawlerai.config_ir.validation import HeldOutPage, Validated, ValidationReport, validate
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.jobs import record_event, transition_job
from crawlerai.db.models import (
    ConfigOrigin,
    ExtractionConfig,
    ExtractionConfigId,
    FetchMethod,
    Job,
    JobId,
    JobStatus,
    ProgressiveState,
    Site,
)
from crawlerai.llm.client import LLMClient, LLMFailure
from crawlerai.schemas import registry
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)

# ARCHITECTURE §8.3: of the 8 pages a run reads, five are the learning sample and the rest are held out.
SAMPLE_PAGES: Final = 5
LEARNING_STARTED: Final = "learning_started"
LEARNING_FINISHED: Final = "learning_finished"


@dataclass(frozen=True, slots=True)
class Learned:
    """How a run ended: the config it activated, or why it activated none."""

    config_id: ExtractionConfigId | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Run:
    """A started run: its job and state, the schema version and site it learns, the config the state served when it
    started, and the pages it reads."""

    job_id: JobId
    key: StateKey
    schema: SchemaDef
    host: str
    fetch: FetchMethod
    serving: ExtractionConfigId | None
    pages: Sequence[StoredPage] = ()


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
) -> Learned | None:
    """Run the `learn` job `job_id` to its end and return how it ended; None when it is not queued (another process
    took it). `max_chars` is role A's HTML limit per page (`CRAWLERAI_LLM_A_MAX_CHARS`)."""
    async with engine.begin() as conn:
        run = await _start(conn, job_id)
    if not isinstance(run, _Run):
        return run
    try:
        # The job is running and its row unlocked, so the bundle reads hold no lock anyone waits on.
        async with engine.connect() as conn:
            pages = await load_pages(conn, store, run.key.site_id, run.schema, limit=LEARN_AFTER_PAGES)
        run = replace(run, pages=pages)
        ir, held_out = await _learn(client, run, vocabulary, max_chars)
        validated = await asyncio.to_thread(validate, ir, run.schema, held_out, vocabulary)
    except LLMFailure as e:
        async with engine.begin() as conn:
            return await _fail(conn, run, e.code)
    except Exception:  # §4.8: a run that cannot finish leaves the state as a failed run would, never `learning`
        log.exception("learn job %s failed", job_id)
        async with engine.begin() as conn:
            return await _fail(conn, run, "error")
    async with engine.begin() as conn:
        return await _finish(conn, run, validated)


async def _start(conn: AsyncConnection, job_id: JobId) -> _Run | Learned | None:
    job = (
        await conn.execute(
            select(Job.status, Job.request, Job.cancel_requested)
            .where(Job.id == job_id, Job.kind == "learn")
            # One process starts the job: a second waits here, then finds it no longer queued.
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
    site = (await conn.execute(select(Site.host, Site.fetch_method).where(Site.id == key.site_id))).one()
    serving = (await conn.execute(select(ProgressiveState.active_config_id).where(*key.where()))).scalar_one()
    await record_event(conn, job_id, LEARNING_STARTED)
    return _Run(job_id, key, schema, site.host, site.fetch_method, serving)


def split(schema: SchemaDef, pages: Sequence[StoredPage]) -> tuple[list[SamplePage], list[HeldOutPage]]:
    """The learning sample, the `SAMPLE_PAGES` pages with the most published required values (the most recent first
    on a tie), and the held-out pages, the rest (§4.4)."""
    required = {name for name, spec in schema.fields.items() if spec.required}

    def published(page: StoredPage) -> int:
        entities = (page.sample.published, *page.sample.rows)
        return sum(len(required.intersection(entity)) for entity in entities)

    ranked = sorted(pages, key=published, reverse=True)  # stable: `pages` are most recent first
    return [page.sample for page in ranked[:SAMPLE_PAGES]], [page.held_out for page in ranked[SAMPLE_PAGES:]]


async def _learn(
    client: LLMClient, run: _Run, vocabulary: Vocabulary, max_chars: int
) -> tuple[ExtractionConfigIR, list[HeldOutPage]]:
    """The config induction and synthesis learn from the sample, and the held-out pages to validate it on."""
    sample, held_out = split(run.schema, run.pages)
    induction = await asyncio.to_thread(induce, run.schema, sample, vocabulary)
    ir = _induced(run, induction)
    # Fields an adapter or API recipe maps keep coming from it: they need no steps (D-0556).
    targets = [name for name in induction.to_synthesize if name not in induction.mapped]
    if sample and targets:
        synthesis = await synthesize(
            client, ir, run.schema, sample, targets, vocabulary, max_chars=max_chars, job_id=run.job_id
        )
        ir = synthesis.ir
    return ir, held_out


def _induced(run: _Run, induction: Induction) -> ExtractionConfigIR:
    # SPEC-08 §4.5: a config whose fields an adapter maps is the adapter's.
    origin: ConfigOrigin = "adapter" if induction.mapped else "induced"
    return ExtractionConfigIR(
        ir_version="1",
        site=run.host,
        schema_=SchemaRef(name=run.schema.name, version=run.schema.version),
        page_kind=run.schema.page_kind,
        fetch=Fetch(method=run.fetch),
        fields=induction.fields,
        provenance=Provenance(
            origin=origin, validated_on=[], learned_at=datetime.now(UTC), engine_version=ENGINE_VERSION
        ),
    )


async def _finish(conn: AsyncConnection, run: _Run, validated: Validated) -> Learned:
    await lock_state(conn, run.key)
    cancelled = (await conn.execute(select(Job.cancel_requested).where(Job.id == run.job_id))).scalar_one()
    if cancelled:
        return await _fail(conn, run, "cancelled", validated.report, status="cancelled")
    if validated.ir is None:
        return await _fail(conn, run, validated.report.refused or "refused", validated.report)
    if await _operator_since(conn, run):
        return await _fail(conn, run, "operator_config", validated.report)
    config_id = await activate(conn, run.key, validated)
    await _end(conn, run, "completed", config_id=config_id, reason=None, report=validated.report)
    return Learned(config_id)


async def _operator_since(conn: AsyncConnection, run: _Run) -> bool:
    """Whether an operator's config became active while the run was in flight (§4.10): the operator wrote it knowing
    the pages the run learns from, so the run does not replace it."""
    state, configs = ProgressiveState, ExtractionConfig
    query = (
        select(configs.origin)
        .join(state, state.active_config_id == configs.id)
        .where(*run.key.where(), configs.id.is_distinct_from(run.serving))
    )
    return (await conn.execute(query)).scalar_one_or_none() == "operator"


async def _fail(
    conn: AsyncConnection,
    run: _Run,
    reason: str,
    report: ValidationReport | None = None,
    *,
    status: JobStatus = "failed",
) -> Learned:
    await learning_failed(conn, run.key)
    await _end(conn, run, status, config_id=None, reason=reason, report=report)
    return Learned(None, reason)


async def _end(
    conn: AsyncConnection,
    run: _Run,
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
    await record_event(conn, run.job_id, LEARNING_FINISHED, payload)
    await transition_job(conn, run.job_id, status)
