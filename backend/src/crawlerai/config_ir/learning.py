"""The learning run (learning-configs spec): what a `learn` job does, from a state's stored pages to
an active config or a failed run.

A run reads the state's `LEARN_AFTER_PAGES` most recent extracted pages (`held_out.load_pages`, §4.4). The
`SAMPLE_PAGES` with the most published required values are the learning sample, and the rest are held out. Induction
proposes selectors without an LLM (§4.5), role A synthesizes the fields it left (§4.6), and the config is validated on
the held-out pages (§4.7) and activated (§4.8), with the API recipe its pages' browser captures show their values came
from when one is learned and validated (adapters spec, `api_recipe.learn`); when the site's project requires approval
(D-1342), the validated config waits as `pending_approval` instead (`store_pending`). Every other end is a
failed run
(`progressive.learning_failed`): validation refusing the config, an LLM failure (D-0588), a cancelled job, an error,
the worker stopping (`SHUTDOWN`), or an operator's config activated while the run was in flight, which a run that
started before it does not replace. A job that cannot start, its request naming no state included, and a run still
`running` after `LEARN_RUN_TIMEOUT` (its process died; `expire_learn_runs`), end failed too.

A run takes two transactions: one starts the job, one ends it; the pages are read between them. None is open while
role A or role D is called or a recipe is replayed: the LLM client commits usage on a connection of its own and must
not wait on a write to the job's row (D-0346). A worker that stops after the start, during the final transaction too,
ends the run (`SHUTDOWN`), so its job never waits for `expire_learn_runs`. The job's start and end are recorded as
`learning_started` and `learning_finished` events (jobs spec).
"""

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from crawlerai.acquire.rungs import remembered_method
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.absent import ABSENT, absent_fields
from crawlerai.config_ir.activation import activate, store_pending
from crawlerai.config_ir.api_recipe.learn import learn_recipe
from crawlerai.config_ir.api_recipe.replay import Render, Replays
from crawlerai.config_ir.api_recipe.validate import attach, refused
from crawlerai.config_ir.held_out import StoredPage, load_pages
from crawlerai.config_ir.induction import Induction, SamplePage, induce
from crawlerai.config_ir.listing_induction import ListingInduction, induce_listing
from crawlerai.config_ir.model import NEXT_PAGE_FIELD, ExtractionConfigIR, Fetch, Provenance, SchemaRef
from crawlerai.config_ir.progressive import (
    LEARN_AFTER_PAGES,
    NotLearning,
    StateKey,
    learning_failed,
    lock_state,
)
from crawlerai.config_ir.synthesis import synthesize
from crawlerai.config_ir.validation import HeldOutPage, Validated, ValidationReport, validate, with_unlearned
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.jobs import JOB_TRANSITIONS, record_event, transition_job
from crawlerai.db.models import (
    ConfigOrigin,
    ExtractionConfig,
    ExtractionConfigId,
    FetchMethod,
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
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.storage.base import ObjectStore

log = logging.getLogger(__name__)

# Of the 8 pages a run reads, five are the learning sample and the rest are held out.
SAMPLE_PAGES: Final = 5
LEARNING_STARTED: Final = "learning_started"
LEARNING_FINISHED: Final = "learning_finished"
# The reason a run ends with when its schema was edited while it ran (schemas spec).
SCHEMA_EDITED: Final = "schema_edited"
# A run makes a few role A calls, each at most `llm.client.TIMEOUT_S["strong"]` per provider, plus a retry; a run still
# `running` an hour after it started has lost its process.
LEARN_RUN_TIMEOUT: Final = timedelta(hours=1)
# How many expired runs one scheduler turn ends; a full batch runs again at once (`scheduler.loop`).
EXPIRE_BATCH: Final = 100
EXPIRED: Final = "expired"
# The reason a completed run reports when its config waits for approval (D-1342).
PENDING: Final = "pending_approval"
# The reason of a run cancelled because its worker stops (`run_learner`).
SHUTDOWN: Final = "shutdown"


@dataclass(frozen=True, slots=True)
class Learned:
    """How a run ended: the config it activated, or why it activated none."""

    config_id: ExtractionConfigId | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _Run:
    """A started run: its job and state, the schema and site it learns, the config the state served when it
    started, and the pages it reads."""

    job_id: JobId
    key: StateKey
    schema: SchemaDef
    host: str
    fetch: FetchMethod
    serving: ExtractionConfigId | None
    proxy_pool: str | None = None
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
    replay: Replays | None,
    render: Render | None = None,
) -> Learned | None:
    """Run the `learn` job `job_id` to its end and return how it ended; None when it is not queued (another process
    took it). `max_chars` is role A's HTML limit per page (`CRAWLERAI_LLM_A_MAX_CHARS`); without `replay`, the run
    learns no API recipe, with it, its recipe replays go through the site's proxy pool (D-1381); `render` renders the
    pages whose captures hold no calls to learn a recipe from."""
    try:
        async with engine.begin() as conn:
            run = await _start(conn, job_id)
    except Exception:  # D-0624: a job that cannot start ends failed, or every poll would pick it again
        log.exception("learn job %s could not start", job_id)
        async with engine.begin() as conn:
            return await _abandon(conn, job_id, "error")
    if not isinstance(run, _Run):
        return run
    try:
        # The job is running and its row unlocked, so the bundle reads hold no lock anyone waits on.
        async with engine.connect() as conn:
            pages = await load_pages(conn, store, run.key.site_id, run.schema, limit=LEARN_AFTER_PAGES)
        validated = await _learned(client, replace(run, pages=pages), vocabulary, max_chars, replay, render)
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
    site = (await conn.execute(select(Site.host, Site.proxy_pool).where(Site.id == key.site_id))).one()
    fetch = await remembered_method(conn, key.site_id, key.page_kind)
    serving = (await conn.execute(select(ProgressiveState.active_config_id).where(*key.where()))).scalar_one()
    await record_event(conn, job_id, LEARNING_STARTED)
    return _Run(job_id, key, schema, site.host, fetch, serving, site.proxy_pool)


async def expire_learn_runs(conn: AsyncConnection, *, batch: int) -> int:
    """End up to `batch` runs that started more than `LEARN_RUN_TIMEOUT` ago as failed runs, and return how many: their
    process died, and the state would otherwise stay `learning` (D-0624)."""
    job_ids = await stuck_running_jobs(conn, kinds=("learn",), older_than=LEARN_RUN_TIMEOUT, batch=batch)
    for job_id in job_ids:
        await _abandon(conn, job_id, EXPIRED)
    return len(job_ids)


async def _abandon(conn: AsyncConnection, job_id: JobId, reason: str) -> Learned:
    """End a run that will not finish: its state as a failed run leaves it (§4.8), and its job `failed`. A run that
    ended meanwhile is left as it ended: a stopping worker's cancel can come as the run's final transaction commits."""
    # FOR NO KEY UPDATE, as every lock of a job's row takes (`settle_job`).
    locked = select(Job.status, Job.request).where(Job.id == job_id).with_for_update(key_share=True)
    job = (await conn.execute(locked)).one()
    if not JOB_TRANSITIONS[job.status]:
        return Learned(None, reason)
    if job.status == "queued":  # it failed to start: a job ends `failed` only from `running`
        await transition_job(conn, job_id, "running")
    # The state may have moved on already (an operator's config, a cancel), and then there is no run to end; a request
    # that names no state has none either, and its job still ends, or every poll would pick it again (D-0624).
    with suppress(NotLearning, ValidationError):
        await learning_failed(conn, StateKey.from_request(job.request))
    await _end(conn, job_id, "failed", config_id=None, reason=reason, report=None)
    return Learned(None, reason)


def split(schema: SchemaDef, pages: Sequence[StoredPage]) -> tuple[list[StoredPage], list[StoredPage]]:
    """The learning sample, the `SAMPLE_PAGES` pages with the most published required values (the most recent first
    on a tie), and the held-out pages, the rest (§4.4)."""
    required = {name for name, spec in schema.fields.items() if spec.required}

    def published(page: StoredPage) -> int:
        entities = (page.sample.published, *page.sample.rows)
        return sum(len(required.intersection(entity)) for entity in entities)

    ranked = sorted(pages, key=published, reverse=True)  # stable: `pages` are most recent first
    return ranked[:SAMPLE_PAGES], ranked[SAMPLE_PAGES:]


# A validation report reason stays short: it is a table cell in the config view, not a log.
REASON_CHARS: Final = 200


async def _learned(
    client: LLMClient,
    run: _Run,
    vocabulary: Vocabulary,
    max_chars: int,
    replay: Replays | None,
    render: Render | None,
) -> Validated:
    """The config learned from the run's sample and validated on its held-out pages, with its API recipe."""
    sample, held_out = split(run.schema, run.pages)
    target = Target(run.schema, run.host, run.fetch, run.job_id)
    validated = await learn_config(
        client, target, sample, [page.held_out for page in held_out], vocabulary, max_chars, absent_from=run.pages
    )
    # A recipe enters a validated config only (`attach`, D-0583), so nothing is replayed for a refused one.
    if validated.ir is None or replay is None:
        return validated
    try:
        recipe = await learn_recipe(
            client,
            sample,
            held_out,
            run.schema,
            replay(run.job_id, run.proxy_pool),
            job_id=run.job_id,
            render=render,
        )
    except LLMFailure:
        raise  # D-0738: role D's failure ends the run as role A's does
    except SQLAlchemyError:
        # A database error is the run's, not the recipe's: a replay whose usage was not stored would go unaccounted
        # (adapters spec, "Held-out validation"), so the run ends failed rather than activating the config.
        raise
    except Exception as e:
        # D-1389: the recipe learner's own error refuses the recipe, not the config it would have joined.
        log.exception("learn job %s: recipe learning failed", run.job_id)
        recipe = refused(f"recipe_error: {type(e).__name__}")
    return attach(validated, recipe)


@dataclass(frozen=True, slots=True)
class Target:
    """What a run learns a config for: the schema, the site's host and fetch method, and the job role A is charged to
    (None for a simulated run, which no job pays for)."""

    schema: SchemaDef
    host: str
    fetch: FetchMethod
    job_id: JobId | None


async def learn_config(
    client: LLMClient,
    target: Target,
    sample: Sequence[StoredPage],
    held_out: Sequence[HeldOutPage],
    vocabulary: Vocabulary,
    max_chars: int,
    *,
    absent_from: Sequence[StoredPage],
) -> Validated:
    """The config induction, and role A where induction leaves a required field, learn from `sample`, validated on
    `held_out` (§4.5 to §4.7). `absent_from` are the pages the run read, which say what the site never states."""
    absent = absent_fields(target.schema, absent_from)
    ir, unlearned = await _learn(client, target, [page.sample for page in sample], vocabulary, max_chars, absent)
    # A field no page stated has no value to learn a step from; the config lists it instead (D-1341).
    ir = ir.model_copy(update={"absent": [name for name in absent if name in unlearned]})
    validated = await asyncio.to_thread(validate, ir, target.schema, held_out, vocabulary)
    return with_unlearned(validated, unlearned)


async def _learn(
    client: LLMClient,
    target: Target,
    sample: list[SamplePage],
    vocabulary: Vocabulary,
    max_chars: int,
    absent: Sequence[str],
) -> tuple[ExtractionConfigIR, dict[str, str]]:
    """The config induction, then synthesis, learn from the sample, and why each other schema field got no steps: the
    reason induction left it with and, when synthesis tried it too, synthesis's last diagnostics. Synthesis runs only
    when induction leaves a required field (or every member of a required group) that some page states, and then tries
    every field induction left; it does not try an `absent` field: no page states a value its selectors could find."""
    schema, row_fields = learnable(target.schema)
    induction = await asyncio.to_thread(induce, schema, sample, vocabulary)
    listed = ListingInduction()
    if schema.page_kind == "listing":
        listed = await asyncio.to_thread(induce_listing, schema, sample, vocabulary)
    ir, left = _induced(target, induction, listed)
    # Fields an adapter or API recipe maps keep coming from it: they need no steps (D-0556).
    reasons = {name: reason for name, reason in left.items() if name not in induction.mapped}
    for name in set(absent).intersection(reasons):
        reasons[name] = ABSENT
    tried = [name for name, reason in reasons.items() if reason != ABSENT]
    covered = {*_stepped(ir), *induction.mapped, *absent, *_unpublished(schema, sample)}
    if sample and tried and _uncovered(schema, covered):
        synthesis = await synthesize(
            client, ir, schema, sample, tried, vocabulary, max_chars=max_chars, job_id=target.job_id
        )
        ir = synthesis.ir
        for name, diagnostics in synthesis.unresolved.items():
            if name in reasons:
                reasons[name] += f"; synthesis: {_brief(diagnostics)}"
    learned = _stepped(ir)
    return ir, {name: reason for name, reason in reasons.items() if name not in learned} | row_fields


def _stepped(ir: ExtractionConfigIR) -> set[str]:
    """The fields a config runs steps for, a listing's next page's URL included."""
    listing = ir.listing
    if listing is None:
        return set(ir.fields)
    return {*ir.fields, *listing.fields, *((NEXT_PAGE_FIELD,) if listing.next is not None else ())}


def _unpublished(schema: SchemaDef, sample: Sequence[SamplePage]) -> set[str]:
    """The fields no sample page (nor any of its rows) published a value for: no step role A gives verifies for them,
    so they do not make role A run."""
    stated = {name for page in sample for name in page.published}
    stated |= {name for page in sample for row in page.rows for name in row}
    return set(schema.fields) - stated


def _uncovered(schema: SchemaDef, covered: set[str]) -> bool:
    """Whether a required field, or every member of a required group, is not `covered` (learned, mapped or absent):
    role A runs for what a record needs (§10), not for an optional field alone."""
    required = {name for name, spec in schema.fields.items() if spec.required}
    return bool(required - covered) or any(not covered.intersection(group) for group in schema.required_groups)


def learnable(schema: SchemaDef) -> tuple[SchemaDef, dict[str, str]]:
    """The schema learning learns steps for, and why each other field gets none. A row-mapped field gets none
    (`row_field`, variants spec): induction generalizes one locator per field per page, and a row field needs a row
    selector, sub-field selectors relative to it and row matching. The structured collectors still fill it in `config`
    mode, and drift does not track it."""
    row_fields = {name: "row_field" for name, spec in schema.fields.items() if spec.row_mapped}
    fields = {name: spec for name, spec in schema.fields.items() if name not in row_fields}
    return schema.model_copy(update={"fields": fields}), row_fields


def _brief(diagnostics: Sequence[str]) -> str:
    """Synthesis diagnostics, short enough for a report cell: the first two, cut at `REASON_CHARS`."""
    text = "; ".join(diagnostics[:2]) or "no steps"
    return text if len(text) <= REASON_CHARS else text[: REASON_CHARS - 1] + "…"


def _induced(
    target: Target, induction: Induction, listed: ListingInduction
) -> tuple[ExtractionConfigIR, dict[str, str]]:
    """The induced config, a listing's next page's URL as its listing's `next` step, and the fields it left with why."""
    fields = dict(induction.fields)
    left = {**induction.to_synthesize, **listed.to_synthesize}
    next_steps = fields.pop(NEXT_PAGE_FIELD, None) if target.schema.page_kind == "listing" else None
    listing = listed.listing
    if listing is not None and next_steps is not None:
        listing = listing.model_copy(update={"next": next_steps.steps[0]})
    elif next_steps is not None:
        left[NEXT_PAGE_FIELD] = "no_listing"
    # learning-configs spec: a config whose fields an adapter maps is the adapter's.
    origin: ConfigOrigin = "adapter" if induction.mapped else "induced"
    ir = ExtractionConfigIR(
        ir_version="1",
        site=target.host,
        schema_=SchemaRef(name=target.schema.name, digest=document_digest(target.schema)),
        page_kind=target.schema.page_kind,
        fetch=Fetch(method=target.fetch),
        fields=fields,
        listing=listing,
        provenance=Provenance(
            origin=origin, validated_on=[], learned_at=datetime.now(UTC), engine_version=ENGINE_VERSION
        ),
    )
    return ir, left


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
    """Whether the site's project makes a learned config wait for approval (D-1342)."""
    project = select(Site.project_id).where(Site.id == run.key.site_id).scalar_subquery()
    query = select(Project.require_config_approval).where(Project.id == project)
    return bool((await conn.execute(query)).scalar_one())


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


async def _schema_edited(conn: AsyncConnection, run: _Run) -> bool:
    """Whether the schema was edited since the run started: what it learned is for another document, and the edit
    already sent the state back to `cold` (`progressive.relearn_schema`), where a later run may now be in flight."""
    current = await registry.get_by_id(conn, run.key.schema_id)
    return document_digest(current) != document_digest(run.schema)


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
