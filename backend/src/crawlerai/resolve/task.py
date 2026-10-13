"""The extraction step of a page task (SPEC-05 §4.10, ARCHITECTURE §6, INV-27): a fetched capture is extracted with
`extract_page`, and the result is stored as one `extraction` row, its `candidate` rows and the page's `record`.

A scrape task runs it after its fetch (SPEC-07 §4.4, inline or in a worker: one function), and so will batch, extract
and crawl tasks (SPEC-10). Storing only serializes what resolution decided (INV-27): each candidate keeps whether it
was chosen or why it was rejected, and the record holds the published values.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.collect.base import Candidate
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import Candidate as CandidateRow
from crawlerai.db.models import (
    CaptureId,
    Extraction,
    ExtractionId,
    ExtractionMode,
    NormalizeStatus,
    Record,
    RecordId,
    SiteId,
    TaskOutcome,
)
from crawlerai.db.queue import ClaimedTask
from crawlerai.normalize.base import Ambiguous, Invalid, Ok
from crawlerai.resolve.pipeline import EngineData, RoleC, extract_page
from crawlerai.resolve.records import RecordDraft, assemble
from crawlerai.resolve.types import ExtractionResult, FieldOutcome
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle


@dataclass(frozen=True, slots=True)
class Stored:
    """The task's outcome (`url_task.outcome`; a resolution `error` is `failed`), the rows written for it, and the
    record's content when it got one."""

    outcome: TaskOutcome
    extraction_id: ExtractionId
    record_id: RecordId | None
    record: RecordDraft | None
    result: ExtractionResult


async def extract_task(
    conn: AsyncConnection,
    task: ClaimedTask,
    *,
    capture_id: CaptureId,
    site_id: SiteId,
    bundle: CaptureBundle,
    schema: SchemaDef,
    data: EngineData,
    role_c: RoleC | None,
    mode: ExtractionMode,
    caller_supplied: bool,
) -> Stored:
    """Extract the task's capture and store the result in `conn`'s transaction. `caller_supplied` is true for
    `scrape`, `batch_scrape` and `extract` URLs: an incomplete page then keeps its record (`partial`), where a
    crawl-discovered one gets `no_match` and none (§4.10). The caller settles the task with the returned outcome."""
    result = await extract_page(bundle, schema, None, role_c, mode, data=data)
    return await store_extraction(
        conn, task, result, capture_id=capture_id, site_id=site_id, schema=schema, caller_supplied=caller_supplied
    )


async def store_extraction(
    conn: AsyncConnection,
    task: ClaimedTask,
    result: ExtractionResult,
    *,
    capture_id: CaptureId,
    site_id: SiteId,
    schema: SchemaDef,
    caller_supplied: bool,
) -> Stored:
    """Store `result`, `extract_page`'s for the task's capture, as `extract_task` does: for a caller that extracts
    before it opens the transaction (`scrape`, which holds no connection while the page resolves)."""
    extraction_id: ExtractionId = (
        await conn.execute(
            insert(Extraction)
            .values(
                url_task_id=task.id,
                capture_id=capture_id,
                engine_version=ENGINE_VERSION,
                config_version=None,
                mode=result.mode,
                llm_calls=len(result.llm_calls),
                diagnostics=list(result.diagnostics),
            )
            .returning(Extraction.id)
        )
    ).scalar_one()
    if result.candidates:
        await conn.execute(insert(CandidateRow), list(_candidate_rows(extraction_id, result)))
    if result.entity is None:
        return Stored("failed" if result.outcome == "error" else result.outcome, extraction_id, None, None, result)
    outcome, draft = assemble(
        schema, result.entity, site_id=site_id, canonical_url=task.canonical_url, caller_supplied=caller_supplied
    )
    record_id = None
    if draft is not None:
        record_id = (
            await conn.execute(
                insert(Record)
                .values(
                    extraction_id=extraction_id,
                    job_id=task.job_id,
                    site_id=site_id,
                    schema_id=schema.id,
                    schema_version=schema.version,
                    entity_key=draft.entity_key,
                    data=draft.data,
                    field_meta={name: meta.model_dump(mode="json") for name, meta in draft.field_meta.items()},
                    complete=draft.complete,
                    mode=result.mode,
                )
                .returning(Record.id)
            )
        ).scalar_one()
    return Stored(outcome, extraction_id, record_id, draft, result)


def _candidate_rows(extraction_id: ExtractionId, result: ExtractionResult) -> Iterator[dict[str, object]]:
    fields: Mapping[str, FieldOutcome] = result.entity or {}
    for candidate in result.candidates:
        status, value = _normalized(candidate)
        outcome = fields.get(candidate.field)
        yield {
            "extraction_id": extraction_id,
            "entity_ref": candidate.entity_id,
            "field": candidate.field,
            "raw_value": candidate.raw,
            "normalized_value": value,
            "normalize_status": status,
            "source_kind": candidate.source_kind,
            "independent": candidate.independent,
            "locator": candidate.locator,
            "chosen": outcome is not None and outcome.chosen == candidate,
            "reject_reason": None if outcome is None else _reject_reason(outcome, candidate),
        }


def _normalized(candidate: Candidate) -> tuple[NormalizeStatus, JsonValue]:
    match candidate.normalized:
        case Ok(value=value):
            return "ok", value
        case Ambiguous():
            return "ambiguous", None
        case Invalid():
            return "invalid", None


def _reject_reason(outcome: FieldOutcome, candidate: Candidate) -> str | None:
    return next((reason for rejected, reason in outcome.rejected if rejected == candidate), None)
