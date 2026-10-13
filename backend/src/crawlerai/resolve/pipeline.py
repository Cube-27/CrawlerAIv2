"""The extraction pipeline (SPEC-05 §4.1, §4.13, §4.14, ARCHITECTURE §8.2, §10, G7): one capture and one schema in,
every field's outcome out. `extract_page` is the one function the worker and the replay harness run (SPEC-03 §4.5).

A page that was not served (`blocked`, `shell`, `not_found`, `error`) yields its block class as the outcome and nothing
else (INV-11). A served page is parsed once (INV-26); every collector reads that one parse, then resolution runs its
stages in order: ownership and intent, preference, derivations, evidence and τ. In cold mode, a detail page's required
fields still missing after that go to role C once, and its candidates are resolved with the others. A listing resolves
each of its rows (`resolve.listing`) and its page-scoped fields, and lists its next-page candidates (§4.12); role C's
listing call is SPEC-06's. Resolution never publishes part of a page: if it raises, the outcome is `error` and no field
is set (§4.14).
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.run import Adapters, Collected, collect_page
from crawlerai.collect.schema_org_map import VOCABULARY_FILE, Vocabulary
from crawlerai.content.context import page_context
from crawlerai.content.metadata import canonical_link
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import ExtractionMode
from crawlerai.normalize.base import Context
from crawlerai.resolve.derive import Derived, fill, is_page_url_field
from crawlerai.resolve.evidence import Calibration, assess_fields, load_calibration
from crawlerai.resolve.intent import AmbiguousTarget, primary_types, select_target
from crawlerai.resolve.listing import listing_rows
from crawlerai.resolve.ownership import EntityGraph
from crawlerai.resolve.pagination import next_page_candidates
from crawlerai.resolve.preference import (
    PRECEDENCE_FILE,
    PRECEDENCE_TYPES,
    Orders,
    PageFacts,
    Preference,
    Resolver,
    intent_ambiguous,
    load_precedence,
)
from crawlerai.resolve.records import is_complete, record_confidence
from crawlerai.resolve.types import ExtractionResult, FieldSet, LLMCallRecord, Outcome
from crawlerai.schemas.types import SchemaDef, Scope
from crawlerai.storage.capture_bundle import CaptureBundle

log = logging.getLogger(__name__)

# D-0444: until an order is fitted on dev, no source kind is ranked, so text, long_text, url and image_url fields
# decline as `unranked` rather than follow an unmeasured order (C7).
UNRANKED: Orders = {type_: () for type_ in PRECEDENCE_TYPES}
# INV-11: a capture whose block class is not `ok` is the page's outcome, with no candidates.
_NOT_SERVED: Mapping[BlockClass, Outcome] = {
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "error": "error",
}


@dataclass(frozen=True, slots=True)
class EngineData:
    """What resolution reads besides the page: the schema.org vocabulary, the dev-fitted precedence orders and
    calibration (INV-02), and the active adapters."""

    vocabulary: Vocabulary
    orders: Orders
    calibration: Calibration | None
    adapters: Adapters | None = None

    @classmethod
    def load(cls, data_dir: Path, adapters: Adapters | None = None) -> "EngineData":
        """The data files under `data_dir`. The vocabulary is required; without a fitted precedence file every type is
        `UNRANKED`, and without a calibration every field is uncalibrated (`core.engine_version`: `cal.none`)."""
        precedence = data_dir / PRECEDENCE_FILE
        return cls(
            vocabulary=Vocabulary.read(data_dir / VOCABULARY_FILE),
            orders=load_precedence(precedence) if precedence.is_file() else UNRANKED,
            calibration=load_calibration(data_dir / CALIBRATION_FILE),
            adapters=adapters,
        )


@dataclass(frozen=True, slots=True)
class GapRequest:
    """§4.13: the required fields of `target` that resolution left missing, for role C to read from the page text."""

    page: ParsedPage
    schema: SchemaDef
    ctx: Context
    target: Entity
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GapReply:
    """Role C's grounded candidates (`source_kind='llm'`, owned by the target) and the calls it made."""

    candidates: tuple[Candidate, ...]
    llm_calls: tuple[LLMCallRecord, ...]


# The LLM hook (§4.13), filled by SPEC-06's role C; the caller binds the LLM client.
RoleC = Callable[[GapRequest], Awaitable[GapReply]]


class ModeNotSupported(ValueError):
    """A page this pipeline does not extract yet: config mode (SPEC-08's executor)."""


async def extract_page(
    bundle: CaptureBundle,
    schema: SchemaDef,
    config: object | None,
    role_c: RoleC | None,
    mode: ExtractionMode,
    *,
    data: EngineData,
    parsed: ParsedPage | None = None,
) -> ExtractionResult:
    """The page's outcome, fields and candidates. `extracted` when every required field and group publishes (on a
    listing: in each of at least one row), else `partial`: whether an incomplete page or row keeps its record is the
    caller's (`resolve.records.assemble`, `assemble_listing`). `parsed` is the bundle's parse when the caller already
    has one (a `scrape` shares it with its formats, INV-26)."""
    if config is not None or mode != "adhoc":
        raise ModeNotSupported("config mode runs SPEC-08's config executor, which is not wired yet")
    not_served = _NOT_SERVED.get(bundle.manifest.block_class)
    if not_served is not None:
        return _result(not_served, mode)
    if schema.page_kind == "listing":
        return await _extract_listing(bundle, schema, mode, data, parsed)
    try:
        # Parsing and resolution are CPU work: a thread keeps the event loop serving other tasks meanwhile.
        page, fields = await asyncio.to_thread(_read_and_resolve, bundle, schema, data, parsed)
    except Exception:  # §4.14: a resolution bug fails the page, never part of it
        log.exception("extraction failed")
        return _result("error", mode)
    candidates = page.collected.candidates
    llm_calls: tuple[LLMCallRecord, ...] = ()
    missing = _gaps(schema, fields)
    if role_c is not None and missing and isinstance(page.target, Entity):
        reply = await role_c(GapRequest(page.page, schema, page.ctx, page.target, missing))
        candidates, llm_calls = (*candidates, *reply.candidates), reply.llm_calls
        try:
            fields = await asyncio.to_thread(page.resolve, candidates)
        except Exception:
            log.exception("extraction failed")
            return _result(
                "error", mode, candidates=candidates, llm_calls=llm_calls, diagnostics=page.collected.diagnostics
            )
    return ExtractionResult(
        outcome="extracted" if is_complete(schema, fields) else "partial",
        entity=fields,
        rows=(),
        candidates=candidates,
        llm_calls=llm_calls,
        mode=mode,
        record_confidence=record_confidence(schema, fields),
        diagnostics=page.collected.diagnostics,
    )


@dataclass(frozen=True, slots=True)
class _Page:
    """One served page, parsed once (INV-26), with its context, every collector's result, and what resolution reads
    of it whatever the candidates: the entity graph, the target (§4.6) and the URL-parameter facts."""

    page: ParsedPage
    ctx: Context
    schema: SchemaDef
    data: EngineData
    canonical_url: str | None
    collected: Collected
    graph: EntityGraph
    primary: frozenset[str]
    target: Entity | AmbiguousTarget
    facts: PageFacts

    @classmethod
    def read(cls, bundle: CaptureBundle, schema: SchemaDef, data: EngineData, parsed: ParsedPage | None) -> "_Page":
        manifest = bundle.manifest
        page = ParsedPage.of(bundle) if parsed is None else parsed
        ctx = page_context(page, manifest.final_url, manifest.fetched_at)
        collected = collect_page(page, manifest, schema, ctx, vocabulary=data.vocabulary, adapters=data.adapters)
        canonical = canonical_link(page, manifest.final_url)
        graph = EntityGraph.of(collected.entities, data.vocabulary)
        primary = primary_types(schema, data.vocabulary)
        target = select_target(manifest.url, manifest.final_url, canonical, graph, primary)
        facts = PageFacts.of(manifest.url, page.visible_values.visible)
        return cls(page, ctx, schema, data, canonical, collected, graph, primary, target, facts)

    def resolve(self, candidates: Sequence[Candidate]) -> FieldSet:
        """A detail page's fields, for its target."""
        return self.resolve_for(self.target, candidates, page_values=True)

    def resolve_listing(self) -> tuple[FieldSet, tuple[FieldSet, ...]]:
        """A listing's page-scoped fields, for the page entity, and each row's row-scoped fields (§4.7)."""
        candidates = self.collected.candidates
        page_fields = self.resolve_for(self.graph.page, candidates, page_values=True)
        rows = listing_rows(self.graph, self.primary, self.target)
        return _scoped(self.schema, page_fields, "page"), tuple(
            _scoped(self.schema, self.resolve_for(row, candidates, page_values=False), "row") for row in rows
        )

    def resolve_for(
        self, target: Entity | AmbiguousTarget, candidates: Sequence[Candidate], *, page_values: bool
    ) -> FieldSet:
        """Preference (§4.7, §4.8) for `target`, derivations, then evidence and τ (§4.9). `page_values`: whether
        page-level candidates are the target's (`EntityGraph.owned_by`)."""
        schema = self.schema
        decisions: Mapping[str, Preference | Derived]
        if isinstance(target, AmbiguousTarget):
            decisions = intent_ambiguous(schema, candidates)
        else:
            resolver = Resolver(self.graph, target, self.facts, self.data.orders, page_values)
            preferences = resolver.prefer(schema, candidates)
            by_field: dict[str, list[Candidate]] = defaultdict(list)
            for candidate in candidates:
                by_field[candidate.field].append(candidate)
            decisions = {
                name: fill(
                    spec,
                    preferences[name],
                    by_field[name],
                    resolver,
                    self.ctx,
                    canonical_url=self.canonical_url,
                    page_url_field=is_page_url_field(schema, spec, self.primary),
                )
                for name, spec in schema.fields.items()
            }
        return assess_fields(schema, decisions, self.data.calibration, corroborated=frozenset())


def _read_and_resolve(
    bundle: CaptureBundle, schema: SchemaDef, data: EngineData, parsed: ParsedPage | None
) -> tuple[_Page, FieldSet]:
    page = _Page.read(bundle, schema, data, parsed)
    return page, page.resolve(page.collected.candidates)


@dataclass(frozen=True, slots=True)
class _Listing:
    page: _Page
    fields: FieldSet
    rows: tuple[FieldSet, ...]
    next_pages: tuple[str, ...]

    @classmethod
    def read(cls, bundle: CaptureBundle, schema: SchemaDef, data: EngineData, parsed: ParsedPage | None) -> "_Listing":
        page = _Page.read(bundle, schema, data, parsed)
        fields, rows = page.resolve_listing()
        return cls(page, fields, rows, next_page_candidates(page.page, bundle.manifest.final_url))


async def _extract_listing(
    bundle: CaptureBundle, schema: SchemaDef, mode: ExtractionMode, data: EngineData, parsed: ParsedPage | None
) -> ExtractionResult:
    try:
        listing = await asyncio.to_thread(_Listing.read, bundle, schema, data, parsed)
    except Exception:  # §4.14, as for a detail page
        log.exception("extraction failed")
        return _result("error", mode)
    # Each row's record holds the page's fields too (`resolve.records.assemble_listing`).
    records = [{**listing.fields, **row} for row in listing.rows]
    complete = bool(records) and all(is_complete(schema, record) for record in records)
    return ExtractionResult(
        outcome="extracted" if complete else "partial",
        entity=listing.fields,
        rows=listing.rows,
        candidates=listing.page.collected.candidates,
        llm_calls=(),
        mode=mode,
        record_confidence=_least_confident(record_confidence(schema, record) for record in records),
        diagnostics=listing.page.collected.diagnostics,
        next_pages=listing.next_pages,
    )


def _least_confident(confidences: Iterable[float | None]) -> float | None:
    """§10, per record: the page's is its least confident row's, `None` while any row's is (or there is no row)."""
    known = list(confidences)
    if not known or None in known:
        return None
    return min(c for c in known if c is not None)


def _scoped(schema: SchemaDef, fields: FieldSet, scope: Scope) -> FieldSet:
    return {name: outcome for name, outcome in fields.items() if schema.fields[name].scope == scope}


def _gaps(schema: SchemaDef, fields: FieldSet) -> tuple[str, ...]:
    """§4.13: the fields role C is asked for, in schema order: each required field that is `missing` (not a conflict
    or an abstention), and each `missing` member of a required group that no member fills yet."""
    published = {name for name, outcome in fields.items() if outcome.status == "published"}
    unmet = {name for group in schema.required_groups if not published.intersection(group) for name in group}
    return tuple(
        name
        for name, spec in schema.fields.items()
        if (spec.required or name in unmet) and fields[name].status == "missing"
    )


def _result(
    outcome: Outcome,
    mode: ExtractionMode,
    *,
    candidates: tuple[Candidate, ...] = (),
    llm_calls: tuple[LLMCallRecord, ...] = (),
    diagnostics: tuple[str, ...] = (),
) -> ExtractionResult:
    return ExtractionResult(
        outcome=outcome,
        entity=None,
        rows=(),
        candidates=candidates,
        llm_calls=llm_calls,
        mode=mode,
        record_confidence=None,
        diagnostics=diagnostics,
    )
