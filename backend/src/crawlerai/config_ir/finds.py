"""Role C finds written back (learning-configs spec, "Find recipes"): a value role C found and the page's evidence
verified becomes a step of the site's config, so the site's next pages read it without the LLM.

When a detail page publishes a role C value (`source_kind='llm'`) for a field the site's active config does not run,
induction generalizes that value's locator on the page (`induction.induce`, the sample being the page alone), and the
steps are validated as a learning run validates them (`validation.validate`, both executors) on the site's other stored
pages that published the field, at least `MIN_FIND_HELD_OUT` of them: the steps must reproduce the value the engine
published on every one. The kept fields join the active config as its next version (`store_find`, in `activation`), or,
without one, form a config of their own (origin `role_c`), which still learns in full once enough pages are extracted
(`progressive.trigger_learning`). Nothing is written while a learning run is in flight (it reads the same pages), nor
when the site's project requires approval of learned configs (learning-configs spec, "Activation and active-mode
extraction").

There is one recipe store: the config IR. A field the config then runs is never asked of role C (learning-configs spec,
"Activation and active-mode extraction"); drift suspends it when its yield or validity falls (§4.9).
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from crawlerai.acquire.memory import remembered
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.activation import store_find
from crawlerai.config_ir.held_out import StoredPage, load_pages, load_stored
from crawlerai.config_ir.induction import induce
from crawlerai.config_ir.model import ExtractionConfigIR, Fetch, FieldSteps, Provenance, SchemaRef
from crawlerai.config_ir.progressive import LEARN_AFTER_PAGES, StateKey, lock_state
from crawlerai.config_ir.validation import ValidationReport, validate
from crawlerai.core.engine_version import ENGINE_VERSION
from crawlerai.db.models import (
    CaptureId,
    ExtractionConfig,
    ExtractionConfigId,
    FetchMethod,
    ProgressiveState,
    Project,
    Site,
)
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef, document_digest
from crawlerai.storage.base import ObjectStore

# A find's steps must reproduce the published value on at least two other pages of the site: one page agreeing could
# be a coincidence of its layout.
MIN_FIND_HELD_OUT: Final = 2


@dataclass(frozen=True, slots=True)
class FindWriter:
    """What writing a find back reads: the stored captures, and the schema.org vocabulary induction types steps by."""

    store: ObjectStore
    vocabulary: Vocabulary


def found_fields(schema: SchemaDef, extraction: ExtractionResult) -> tuple[str, ...]:
    """The fields of a detail page that published a role C value, in schema order."""
    if schema.page_kind != "detail" or extraction.entity is None:
        return ()
    return tuple(
        name
        for name, outcome in extraction.entity.items()
        if outcome.status == "published" and outcome.source_kind == "llm"
    )


async def write_back(
    conn: AsyncConnection,
    writer: FindWriter,
    key: StateKey,
    schema: SchemaDef,
    extraction: ExtractionResult,
    capture_id: CaptureId,
) -> ExtractionConfigId | None:
    """Write the page's role C finds back to the site's config, after its extraction is stored on `conn`; the new
    config version's id, or None when no find's steps validated (or nothing may be written)."""
    found = found_fields(schema, extraction)
    if not found or await _held_back(conn, key):
        return None
    # The page's own task completes after its record is stored, so it is read by its capture.
    page = next(iter(await load_stored(conn, writer.store, schema, [capture_id])), None)
    if page is None:
        return None
    pages = await load_pages(conn, writer.store, key.site_id, schema, limit=LEARN_AFTER_PAGES)
    others = [p for p in pages if p.held_out.capture_id != capture_id]
    host, fetch = await _site(conn, key)
    # Induction and validation parse and run the stored pages: off the event loop.
    learned = await asyncio.to_thread(_learned, schema, found, page, others, writer.vocabulary, host, fetch)
    if learned is None:
        return None
    await lock_state(conn, key)
    if await _held_back(conn, key):  # a run started, or a config began to wait, meanwhile
        return None
    return await store_find(conn, key, *learned)


def _learned(
    schema: SchemaDef,
    found: Sequence[str],
    page: StoredPage,
    others: Sequence[StoredPage],
    vocabulary: Vocabulary,
    host: str,
    fetch: FetchMethod,
) -> tuple[ExtractionConfigIR, ValidationReport] | None:
    """The found fields' steps induced on `page` and kept by validation on the `others` that published them, as a
    config of those fields alone with its report; None when none is kept."""
    asked = schema.model_copy(update={"fields": {name: schema.fields[name] for name in found}})
    induced = induce(asked, [page.sample], vocabulary).fields
    held_out = [p.held_out for p in others if not induced.keys().isdisjoint(p.held_out.facts.published)]
    if not induced or len(held_out) < MIN_FIND_HELD_OUT:
        return None
    ir = ExtractionConfigIR(
        ir_version="1",
        site=host,
        schema_=SchemaRef(name=schema.name, digest=document_digest(schema)),
        page_kind=schema.page_kind,
        fetch=Fetch(method=fetch),
        fields=induced,
        provenance=Provenance(
            origin="role_c", validated_on=[], learned_at=datetime.now(UTC), engine_version=ENGINE_VERSION
        ),
    )
    validated = validate(ir, schema, held_out, vocabulary, min_held_out=MIN_FIND_HELD_OUT)
    report = validated.report
    kept: dict[str, FieldSteps] = {
        name: steps
        for name, steps in (validated.ir.fields if validated.ir is not None else {}).items()
        if report.fields[name].published >= MIN_FIND_HELD_OUT
    }
    if validated.ir is None or not kept:
        return None
    return validated.ir.model_copy(update={"fields": kept}), report


async def _held_back(conn: AsyncConnection, key: StateKey) -> bool:
    """Whether nothing may be written for `key` now: a learning run is in flight, a config waits for approval, or the
    project requires approval of learned configs (learning-configs spec, "Activation and active-mode extraction")."""
    state, configs = ProgressiveState, ExtractionConfig
    running = select(state.learning_started_at.is_not(None)).where(*key.where()).scalar_subquery()
    waiting = select(configs.id).where(*key.config_scope(), configs.status == "pending_approval").exists()
    project = select(Site.project_id).where(Site.id == key.site_id).scalar_subquery()
    approval = select(Project.require_config_approval).where(Project.id == project).scalar_subquery()
    row = (await conn.execute(select(running, waiting, approval))).one()
    return bool(row[0]) or bool(row[1]) or bool(row[2])


async def _site(conn: AsyncConnection, key: StateKey) -> tuple[str, FetchMethod]:
    """The site's host, and the fetch method its pages are read with (`acquire.memory.remembered`)."""
    host = (await conn.execute(select(Site.host).where(Site.id == key.site_id))).scalar_one()
    return host, (await remembered(conn, key.site_id, key.page_kind, blocks=False)).method
