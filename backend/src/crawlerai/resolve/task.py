"""The extraction step of a page task (SPEC-05 §4.10, ARCHITECTURE §6, INV-27): a fetched capture is extracted with
`extract_page`, and the result is stored as one `extraction` row, its `candidate` rows and the page's `record` (a
listing's: one per row).

A scrape task runs it after its fetch (SPEC-07 §4.4, inline or in a worker: one function), and so will batch, extract
and crawl tasks (SPEC-10). Storing only serializes what resolution decided (INV-27): each candidate keeps whether it
was chosen or why it was rejected, and the record holds the published values.
"""

from collections.abc import Iterator
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
from crawlerai.resolve.records import RecordDraft, assemble, assemble_listing
from crawlerai.resolve.types import ExtractionResult, FieldSet
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle


@dataclass(frozen=True, slots=True)
class StoredRecord:
    id: RecordId
    draft: RecordDraft


@dataclass(frozen=True, slots=True)
class Stored:
    """The task's outcome (`url_task.outcome`; a resolution `error` is `failed`), the rows written for it, and each
    record's content: at most one record for a detail page, one per kept row for a listing."""

    outcome: TaskOutcome
    extraction_id: ExtractionId
    records: tuple[StoredRecord, ...]
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
    crawl-discovered one gets `no_match` and none (§4.10). The caller settles the task with the returned outcome.

    `role_c` calls the LLM client before this step writes anything, and the client commits usage on its own
    connection (D-0346): `conn`'s transaction must not hold an uncommitted write to the job's row."""
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
        return Stored("failed" if result.outcome == "error" else result.outcome, extraction_id, (), result)
    outcome, drafts = _records(
        schema,
        result.entity,
        result.rows,
        site_id=site_id,
        page_url=task.canonical_url,
        caller_supplied=caller_supplied,
    )
    if not drafts:
        return Stored(outcome, extraction_id, (), result)
    values = [
        {
            "extraction_id": extraction_id,
            "job_id": task.job_id,
            "site_id": site_id,
            "schema_id": schema.id,
            "schema_version": schema.version,
            "entity_key": draft.entity_key,
            "data": draft.data,
            "field_meta": {name: meta.model_dump(mode="json") for name, meta in draft.field_meta.items()},
            "complete": draft.complete,
            "mode": result.mode,
        }
        for draft in drafts
    ]
    inserted = await conn.execute(insert(Record).returning(Record.id, sort_by_parameter_order=True), values)
    records = tuple(StoredRecord(record_id, draft) for record_id, draft in zip(inserted.scalars(), drafts, strict=True))
    return Stored(outcome, extraction_id, records, result)


def _records(
    schema: SchemaDef,
    fields: FieldSet,
    rows: tuple[FieldSet, ...],
    *,
    site_id: SiteId,
    page_url: str,
    caller_supplied: bool,
) -> tuple[TaskOutcome, tuple[RecordDraft, ...]]:
    if schema.page_kind == "listing":
        return assemble_listing(
            schema, fields, rows, site_id=site_id, page_url=page_url, caller_supplied=caller_supplied
        )
    outcome, draft = assemble(schema, fields, site_id=site_id, canonical_url=page_url, caller_supplied=caller_supplied)
    return outcome, (draft,) if draft is not None else ()


def _candidate_rows(extraction_id: ExtractionId, result: ExtractionResult) -> Iterator[dict[str, object]]:
    chosen, reasons = _marks(result)
    for candidate in result.candidates:
        status, value = _normalized(candidate)
        key = _key(candidate)
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
            "chosen": key in chosen,
            "reject_reason": None if key in chosen else reasons.get(key),
        }


# A candidate's identity on the page: one field's value, from one source, at one place, of one entity.
_CandidateKey = tuple[str, str, str, str]


def _key(candidate: Candidate) -> _CandidateKey:
    return candidate.field, candidate.entity_id, candidate.source_kind, candidate.locator


def _marks(result: ExtractionResult) -> tuple[set[_CandidateKey], dict[_CandidateKey, str]]:
    """The candidates some entity's field published, and why each other one did not. A listing resolves every row
    against all candidates, so a row's candidate is `not_owned` in every other row: the reason its own row gave says
    more, and is kept."""
    chosen: set[_CandidateKey] = set()
    reasons: dict[_CandidateKey, str] = {}
    for fields in (result.entity or {}, *result.rows):
        for outcome in fields.values():
            if outcome.chosen is not None:
                chosen.add(_key(outcome.chosen))
            for candidate, reason in outcome.rejected:
                if reasons.get(_key(candidate), "not_owned") == "not_owned":
                    reasons[_key(candidate)] = reason
    return chosen, reasons


def _normalized(candidate: Candidate) -> tuple[NormalizeStatus, JsonValue]:
    match candidate.normalized:
        case Ok(value=value):
            return "ok", value
        case Ambiguous():
            return "ambiguous", None
        case Invalid():
            return "invalid", None
