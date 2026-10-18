"""The extraction pipeline (SPEC-05 §4.1, §4.13, §4.14, ARCHITECTURE §8.2, §10, G7): one capture and one schema in,
every field's outcome out. `extract_page` is the one function the worker and the replay harness run (SPEC-03 §4.5).

A page that was not served (`blocked`, `shell`, `not_found`, `error`) yields its block class as the outcome and nothing
else (INV-11). A served page is parsed once (INV-26); every collector reads that one parse, then resolution runs its
stages in order: ownership and intent, preference, derivations, evidence and τ. A detail page's required fields still
missing after that go to role C once, and its candidates are resolved with the others. A listing resolves each of its
rows (`resolve.listing`) and its page-scoped fields, and lists its next-page candidates (§4.12). A listing whose
structured data gives no rows asks role C for them (ARCHITECTURE §8.6), with its missing page fields; its rows are then
the reply's. Resolution never publishes part of a page: if it raises, the outcome is `error` and no field is set
(§4.14).

With the site's active config (ARCHITECTURE §8.4, SPEC-08 §4.8) a page is extracted in `config` mode: the config's
executor reads the same parse, its candidates enter resolution with the collectors' (in the bucket of the config
field's status, §10), and role C is asked only for fields the config does not run. A listing's rows are the structured
data's when it gives any, else the config's; role C never adds rows beside a config that runs row fields.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

from crawlerai.collect.base import Candidate, Entity
from crawlerai.collect.config import ConfigExecutor
from crawlerai.collect.currencies import with_stated_currencies
from crawlerai.collect.item_links import item_url_fields, row_links
from crawlerai.collect.run import Adapters, Collected, collect_page
from crawlerai.collect.schema_org_map import VOCABULARY_FILE, Vocabulary, canonical_urls
from crawlerai.content.context import page_context
from crawlerai.content.metadata import canonical_link
from crawlerai.content.page import ParsedPage
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import ExtractionMode, SourceKind
from crawlerai.normalize.base import Context
from crawlerai.resolve.call_rows import with_call_rows
from crawlerai.resolve.derive import Derived, fill, is_page_url_field
from crawlerai.resolve.evidence import Calibration, assess_fields, load_calibration, required_fields
from crawlerai.resolve.intent import AmbiguousTarget, primary_types, select_target
from crawlerai.resolve.listing import listing_rows
from crawlerai.resolve.ownership import OFFER, EntityGraph
from crawlerai.resolve.pagination import next_page_candidate, next_page_links
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
from crawlerai.resolve.rows import RowField, resolve_rows
from crawlerai.resolve.types import ExtractionResult, FieldSet, LLMCallRecord, Outcome
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, Scope
from crawlerai.storage.capture_bundle import CaptureBundle

log = logging.getLogger(__name__)
_FAILED = "extraction failed"
# The reason of a `missing` field the active config lists as absent (`config_ir.absent`, D-1341).
ABSENT: Final = "absent"

# D-0486: without a `source_precedence.yaml` no source kind is ranked, so text, long_text, url and image_url fields
# decline as `unranked` rather than follow an unmeasured order (C7). The repo commits SPEC-05 §4.7's order (D-0444).
UNRANKED: Orders = dict.fromkeys(PRECEDENCE_TYPES, ())
# INV-11: a capture whose block class is not `ok` is the page's outcome, with no candidates.
_NOT_SERVED: Mapping[BlockClass, Outcome] = {
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "error": "error",
}


class PinnedData(BaseModel):
    """What a job pins of `EngineData` when it is submitted (INV-28): the precedence orders and the calibration. Its
    pages resolve with these, whatever the files of the process that runs them say by then."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orders: dict[FieldType, tuple[SourceKind, ...]]
    calibration: Calibration | None


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

    def pin(self) -> PinnedData:
        return PinnedData(orders=dict(self.orders), calibration=self.calibration)

    def pinned(self, pin: PinnedData) -> "EngineData":
        """This data with `pin`'s orders and calibration in place of its own."""
        return replace(self, orders=pin.orders, calibration=pin.calibration)


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
    """Role C's grounded candidates (`source_kind='llm'`, owned by the target) and the calls it made. `failure` is
    set when its call gave no valid reply (SPEC-06 §4.7): the asked fields then stay `missing` with it as their
    reason. `diagnostics` join the page's (values dropped as ungrounded, truncation)."""

    candidates: tuple[Candidate, ...]
    llm_calls: tuple[LLMCallRecord, ...]
    failure: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ListingGapRequest:
    """ARCHITECTURE §8.6: a listing whose structured data gives no rows. Role C reads the rows, with `row_fields`
    each, and the page entity's `page_missing` fields from the page text."""

    page: ParsedPage
    schema: SchemaDef
    ctx: Context
    row_fields: tuple[str, ...]
    page_missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListingGapReply(GapReply):
    """A listing's `GapReply`: `rows` are the entities of the rows role C read, in page order, and `candidates` are
    owned by them or by the page entity. `failure` leaves the asked page fields `missing` with it."""

    rows: tuple[Entity, ...] = ()


class RoleC(Protocol):
    """The LLM hook (§4.13), filled by SPEC-06's role C; the caller binds the LLM client."""

    async def detail(self, request: GapRequest) -> GapReply: ...

    async def listing(self, request: ListingGapRequest) -> ListingGapReply: ...


async def extract_page(
    bundle: CaptureBundle,
    schema: SchemaDef,
    config: ConfigExecutor | None,
    role_c: RoleC | None,
    *,
    data: EngineData,
    parsed: ParsedPage | None = None,
) -> ExtractionResult:
    """The page's outcome, fields and candidates: in `config` mode with `config`, the site's active config for the
    schema and page kind, else `adhoc` (cold). `extracted` when every required field and group publishes (on a
    listing: in each of at least one row), else `partial`: whether an incomplete page or row keeps its record is the
    caller's (`resolve.records.assemble`, `assemble_listing`). `parsed` is the bundle's parse when the caller already
    has one (a `scrape` shares it with its formats, INV-26)."""
    mode: ExtractionMode = "adhoc" if config is None else "config"
    not_served = _NOT_SERVED.get(bundle.manifest.block_class)
    if not_served is not None:
        return _result(not_served, mode)
    source = _Source(bundle, schema, data, parsed, config)
    if schema.page_kind == "listing":
        return await _extract_listing(source, role_c, mode)
    try:
        # Parsing and resolution are CPU work: a thread keeps the event loop serving other tasks meanwhile.
        page, fields = await asyncio.to_thread(_read_and_resolve, source)
    except Exception:  # §4.14: a resolution bug fails the page, never part of it
        log.exception(_FAILED)
        return _result("error", mode)
    candidates, diagnostics = page.candidates, page.diagnostics
    llm_calls: tuple[LLMCallRecord, ...] = ()
    missing = _gaps(schema, fields, page.config.covered)
    if role_c is not None and missing and isinstance(page.target, Entity):
        reply = await role_c.detail(GapRequest(page.page, schema, page.ctx, page.target, missing))
        candidates, llm_calls = (*candidates, *reply.candidates), reply.llm_calls
        diagnostics = (*diagnostics, *reply.diagnostics)
        if reply.candidates:  # without new candidates, resolution would decide the same
            try:
                fields = await asyncio.to_thread(page.resolve, candidates)
            except Exception:
                log.exception(_FAILED)
                return _result("error", mode, candidates=candidates, llm_calls=llm_calls, diagnostics=diagnostics)
        if reply.failure is not None:
            fields = _unanswered(fields, missing, reply.failure)
    fields = _absent(fields, page.config.absent)
    return ExtractionResult(
        outcome="extracted" if is_complete(schema, fields) else "partial",
        entity=fields,
        rows=(),
        candidates=candidates,
        llm_calls=llm_calls,
        mode=mode,
        record_confidence=record_confidence(schema, fields),
        diagnostics=diagnostics,
    )


@dataclass(frozen=True, slots=True)
class _Source:
    """What a page is extracted from: the capture, its parse when the caller has one, and the active config."""

    bundle: CaptureBundle
    schema: SchemaDef
    data: EngineData
    parsed: ParsedPage | None
    config: ConfigExecutor | None


@dataclass(frozen=True, slots=True)
class _Config:
    """What the active config proposed for the page. `covered`: the fields it runs or lists as absent, which role C is
    not asked for (§8.4, D-1341); `corroborated`: those whose values take the `config_corroborated` bucket (§10);
    `absent`: those the site's pages do not state (`config_ir.absent`)."""

    rows: tuple[Entity, ...] = ()
    candidates: tuple[Candidate, ...] = ()
    diagnostics: tuple[str, ...] = ()
    covered: frozenset[str] = frozenset()
    corroborated: frozenset[str] = frozenset()
    absent: frozenset[str] = frozenset()

    @classmethod
    def run(cls, config: ConfigExecutor | None, page: ParsedPage, schema: SchemaDef, ctx: Context) -> "_Config":
        if config is None:
            return cls()
        executed = config.execute(page, schema, ctx)
        status = config.field_status
        return cls(
            rows=executed.rows,
            candidates=executed.candidates,
            diagnostics=executed.diagnostics,
            covered=frozenset(status),
            corroborated=frozenset(name for name, s in status.items() if s == "corroborated"),
            absent=frozenset(name for name, s in status.items() if s == "absent"),
        )


@dataclass(frozen=True, slots=True)
class _Page:
    """One served page, parsed once (INV-26), with its context, every collector's result and the config's, and what
    resolution reads of it whatever the candidates: the entity graph, the target (§4.6) and the URL-parameter facts."""

    page: ParsedPage
    ctx: Context
    schema: SchemaDef
    data: EngineData
    canonical_url: str | None
    collected: Collected
    config: _Config
    graph: EntityGraph
    primary: frozenset[str]
    target: Entity | AmbiguousTarget
    facts: PageFacts
    page_urls: tuple[str, ...]  # the request, final and canonical URLs, canonicalized (SPEC-13 §4.4)

    @classmethod
    def read(cls, source: _Source) -> "_Page":
        manifest, schema, data = source.bundle.manifest, source.schema, source.data
        page = ParsedPage.of(source.bundle) if source.parsed is None else source.parsed
        ctx = with_stated_currencies(page_context(page, manifest.final_url, manifest.fetched_at), page)
        learned = None if source.config is None else source.config.learned_calls
        collected = collect_page(
            page, manifest, schema, ctx, vocabulary=data.vocabulary, adapters=data.adapters, learned=learned
        )
        config = _Config.run(source.config, page, schema, ctx)
        canonical = canonical_link(page, manifest.final_url)
        page_urls = canonical_urls((manifest.url, manifest.final_url, canonical), ctx)
        graph = EntityGraph.of((*collected.entities, *config.rows), data.vocabulary, page_urls)
        # The candidates of an entity merged into another item's are that item's (`resolve.identity`).
        collected = replace(
            collected,
            candidates=graph.adopt(collected.candidates),
            diagnostics=(*collected.diagnostics, *graph.merges()),
        )
        primary = primary_types(schema, data.vocabulary)
        target = select_target(manifest.url, manifest.final_url, canonical, graph, primary)
        facts = PageFacts.of(manifest.url, page.visible_values.visible)
        return cls(page, ctx, schema, data, canonical, collected, config, graph, primary, target, facts, page_urls)

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        return (*self.collected.candidates, *self.config.candidates)

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return (*self.collected.diagnostics, *self.config.diagnostics)

    def resolve(self, candidates: Sequence[Candidate]) -> FieldSet:
        """A detail page's fields, for its target."""
        return self.resolve_for(self.target, candidates, page_values=True, detail=self.schema.page_kind == "detail")

    def resolve_listing(
        self, candidates: Sequence[Candidate], rows: Sequence[Entity]
    ) -> tuple[FieldSet, tuple[FieldSet, ...]]:
        """A listing's page-scoped fields, for the page entity, and each row's row-scoped fields (§4.7)."""
        page_fields = self.resolve_for(self.graph.page, candidates, page_values=True)
        return _scoped(self.schema, page_fields, "page"), tuple(
            _scoped(self.schema, self.resolve_for(row, candidates, page_values=False), "row") for row in rows
        )

    def resolve_for(
        self,
        target: Entity | AmbiguousTarget,
        candidates: Sequence[Candidate],
        *,
        page_values: bool,
        detail: bool = False,
    ) -> FieldSet:
        """Preference (§4.7, §4.8) for `target`, derivations, then evidence and τ (§4.9). `page_values`: whether
        page-level candidates are the target's (`EntityGraph.owned_by`); `detail`: whether `target` is a detail page's,
        with its variant fill and row-mapped fields (SPEC-13 §4.3 to §4.6)."""
        schema = self.schema
        decisions: Mapping[str, Preference | Derived]
        if isinstance(target, AmbiguousTarget):
            decisions = intent_ambiguous(schema, candidates)
        else:
            resolver = Resolver(self.graph, target, self.facts, self.data.orders, page_values, variant_fill=detail)
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
        fields = assess_fields(schema, decisions, self.data.calibration, corroborated=self.config.corroborated)
        if detail and isinstance(target, Entity):
            fields |= self._rows(target, candidates)
        return fields

    def _rows(self, target: Entity, candidates: Sequence[Candidate]) -> FieldSet:
        """A detail target's row-mapped fields, resolved row by row (SPEC-13 §4.3 to §4.5)."""
        required = required_fields(self.schema)
        return {
            name: resolve_rows(
                RowField(
                    name=name,
                    spec=spec,
                    required=name in required,
                    graph=self.graph,
                    target=target,
                    page=self.facts,
                    orders=self.data.orders,
                    calibration=self.data.calibration,
                    page_urls=self.page_urls,
                ),
                candidates,
            )
            for name, spec in self.schema.fields.items()
            if spec.row_mapped
        }


def _read_and_resolve(source: _Source) -> tuple[_Page, FieldSet]:
    page = _Page.read(source)
    return page, page.resolve(page.candidates)


# D-1475: why a listing gave no rows, as `no_rows: <cause>`: structured data, the config and the captured calls gave
# none and role C was not asked (`NOT_ASKED`: no hook, a schema without row fields, or a config that runs a row field),
# gave no valid reply (its failure's reason: `llm_unavailable`, `llm_budget`, ...), or listed none it could ground
# (`NONE_LISTED`).
NO_ROWS: Final = "no_rows"
NOT_ASKED: Final = "not_asked"
NONE_LISTED: Final = "none_listed"


def no_rows(cause: str) -> str:
    return f"{NO_ROWS}: {cause}"


@dataclass(frozen=True, slots=True)
class _Listing:
    page: _Page
    fields: FieldSet
    rows: tuple[FieldSet, ...]
    next_pages: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    diagnostics: tuple[str, ...]
    llm_calls: tuple[LLMCallRecord, ...] = ()
    network: bool = False  # the rows are those of the page's captured calls (Appendix A #59)
    role_c: str = NOT_ASKED  # what role C did when the listing has no rows (`no_rows`)

    @classmethod
    def read(cls, source: _Source) -> "_Listing":
        page = _Page.read(source)
        links = next_page_links(page.page, source.bundle.manifest.final_url)
        diagnostics = list(page.diagnostics)
        found = next_page_candidate(links, page.schema, page.ctx, diagnostics)
        candidates = (*page.candidates, *(() if found is None else (found,)))
        # SPEC-08 §4.8: the config's rows serve only where structured data gives none. Its row candidates belong to its
        # own row entities, so structured and config values never meet in one row.
        row_fields = {name for name, spec in page.schema.fields.items() if spec.scope == "row"}
        holders = frozenset(c.entity_id for c in page.collected.candidates if c.field in row_fields)
        rows = listing_rows(page.graph, page.primary, page.target, holders) or page.config.rows
        # Appendix A #59: the rows of the page's captured calls serve where neither gives any; beside them, a call row
        # fills the row of its item and extends the listing (`resolve/call_rows.py`).
        network = not rows and bool(page.collected.rows)
        if rows:
            call = (page.collected.rows, page.candidates, page.page, page.ctx.base_url)
            rows, joined = with_call_rows(page.graph, page.schema, rows, *call)
            candidates = (*candidates, *joined)
        fields, resolved = page.resolve_listing(candidates, rows or page.collected.rows)
        next_pages = tuple(link.url for link in links)
        return cls(page, fields, resolved, next_pages, candidates, tuple(diagnostics), network=network)

    def gap(self) -> ListingGapRequest | None:
        """The role C request when structured data gives no rows (ARCHITECTURE §8.6): every row field, and the page
        fields still `missing` that the config does not run; None with rows (but for rows of captured calls that leave
        a record incomplete, which role C's rows replace), for a schema without row fields, or when the config runs a
        row field (§8.4; role C's rows could not join the config's)."""
        schema = self.page.schema
        covered = self.page.config.covered
        row_fields = tuple(name for name, spec in schema.fields.items() if spec.scope == "row")
        if (self.rows and not (self.network and not self._complete())) or not row_fields:
            return None
        if covered.intersection(row_fields):
            return None
        page_missing = tuple(
            name for name, outcome in self.fields.items() if outcome.status == "missing" and name not in covered
        )
        return ListingGapRequest(self.page.page, schema, self.page.ctx, row_fields, page_missing)

    def with_reply(self, reply: ListingGapReply, asked: tuple[str, ...]) -> "_Listing":
        """The listing with role C's rows: each row entity joins the graph and resolves its row fields from the
        candidates, with the item URLs of their repeated item blocks (`row_links`, §8.6), and the page fields resolve
        again with the reply's."""
        page = self.page
        graph = EntityGraph.of((*page.graph.entities.values(), *reply.rows), page.data.vocabulary, page.page_urls)
        page = replace(page, graph=graph)
        links = row_links(page.page, page.schema, page.ctx, reply.rows, reply.candidates)
        candidates = (*self.candidates, *reply.candidates, *links)
        # Rows of captured calls stand when role C reads none.
        network = self.network and not reply.rows
        fields, rows = page.resolve_listing(candidates, page.collected.rows if network else reply.rows)
        if reply.failure is not None:
            fields = _unanswered(fields, asked, reply.failure)
        diagnostics = (*self.diagnostics, *reply.diagnostics)
        if not network:
            rows, unplaced = _placed(page.schema, rows)
            if unplaced:
                diagnostics = (*diagnostics, f"role C: rows without their item URL left out: {unplaced}")
        return replace(
            self,
            page=page,
            fields=fields,
            rows=rows,
            candidates=candidates,
            diagnostics=diagnostics,
            llm_calls=reply.llm_calls,
            network=network,
            role_c=reply.failure or NONE_LISTED,
        )

    def _records(self) -> list[FieldSet]:
        # Each row's record holds the page's fields too (`resolve.records.assemble_listing`).
        return [{**self.fields, **row} for row in self.rows]

    def _complete(self) -> bool:
        records = self._records()
        return bool(records) and all(is_complete(self.page.schema, record) for record in records)

    def result(self, mode: ExtractionMode) -> ExtractionResult:
        schema = self.page.schema
        records = self._records()
        return ExtractionResult(
            outcome="extracted" if self._complete() else "partial",
            entity=self.fields,
            rows=self.rows,
            candidates=self.candidates,
            llm_calls=self.llm_calls,
            mode=mode,
            record_confidence=_least_confident(record_confidence(schema, record) for record in records),
            diagnostics=self.diagnostics,
            next_pages=self.next_pages,
            reason=None if self.rows else no_rows(self.role_c),
        )


async def _extract_listing(source: _Source, role_c: RoleC | None, mode: ExtractionMode) -> ExtractionResult:
    try:
        listing = await asyncio.to_thread(_Listing.read, source)
    except Exception:  # §4.14, as for a detail page
        log.exception(_FAILED)
        return _result("error", mode)
    if role_c is not None and (request := listing.gap()) is not None:
        reply = await role_c.listing(request)
        try:
            listing = await asyncio.to_thread(listing.with_reply, reply, request.page_missing)
        except Exception:
            log.exception(_FAILED)
            candidates = (*listing.candidates, *reply.candidates)
            diagnostics = (*listing.diagnostics, *reply.diagnostics)
            return _result("error", mode, candidates=candidates, llm_calls=reply.llm_calls, diagnostics=diagnostics)
    return listing.result(mode)


def _placed(schema: SchemaDef, rows: tuple[FieldSet, ...]) -> tuple[tuple[FieldSet, ...], int]:
    """Role C's rows that publish every required item URL field (`item_url_fields`), and how many were left out. A row
    whose item block gives no URL is not told apart from the page's other text: its record would be keyed by its
    position, not by the item it names (D-1491)."""
    required = [name for name in item_url_fields(schema) if schema.fields[name].required]
    kept = tuple(row for row in rows if all(_published(row, name) for name in required))
    return kept, len(rows) - len(kept)


def _published(fields: FieldSet, name: str) -> bool:
    outcome = fields.get(name)
    return outcome is not None and outcome.status == "published"


def _least_confident(confidences: Iterable[float | None]) -> float | None:
    """§10, per record: the page's is its least confident row's, `None` while any row's is (or there is no row)."""
    known = list(confidences)
    if not known or None in known:
        return None
    return min(c for c in known if c is not None)


def _scoped(schema: SchemaDef, fields: FieldSet, scope: Scope) -> FieldSet:
    return {name: outcome for name, outcome in fields.items() if schema.fields[name].scope == scope}


def _gaps(schema: SchemaDef, fields: FieldSet, covered: frozenset[str]) -> tuple[str, ...]:
    """§4.13: the fields role C is asked for, in schema order. Only `missing` fields the active config does not run
    are asked (ARCHITECTURE §8.4), never a conflict or an abstention, and only when a required one is among them: a
    required field, or a member of a required group that no member fills yet. Missing optional fields then ride along
    in the same call (SPEC-06 §4.4, D-0025). An `object` field, and a list of objects (a row-mapped field included), is
    never asked: a claim is one verbatim span, which cannot hold typed sub-fields (SPEC-13 §4.9)."""
    published = {name for name, outcome in fields.items() if outcome.status == "published"}
    unmet = {name for group in schema.required_groups if not published.intersection(group) for name in group}
    missing = [
        name
        for name, outcome in fields.items()
        if outcome.status == "missing" and name not in covered and not _holds_objects(schema.fields[name])
    ]
    if not any(schema.fields[name].required or name in unmet for name in missing):
        return ()
    return tuple(missing)


def _holds_objects(spec: FieldSpec) -> bool:
    return spec.type is FieldType.OBJECT or (spec.item is not None and spec.item.type is FieldType.OBJECT)


def _absent(fields: FieldSet, absent: frozenset[str]) -> FieldSet:
    """The fields with each `missing` one the config lists as absent saying so (D-1341): the site's pages do not state
    it, so role C was not asked for it."""
    return {
        name: outcome.model_copy(update={"reason": ABSENT})
        if name in absent and outcome.status == "missing"
        else outcome
        for name, outcome in fields.items()
    }


def _unanswered(fields: FieldSet, asked: tuple[str, ...], failure: str) -> FieldSet:
    """The fields after a role C call that gave no reply: each asked field still `missing` says why (SPEC-06 §4.7)."""
    return {
        name: outcome.model_copy(update={"reason": failure})
        if name in asked and outcome.status == "missing"
        else outcome
        for name, outcome in fields.items()
    }


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


def lacks_offer_data(
    bundle: CaptureBundle,
    schema: SchemaDef,
    data: EngineData,
    *,
    config: ConfigExecutor | None = None,
    parsed: ParsedPage | None = None,
) -> bool:
    """Whether a reached detail page for a schema that requires a `money` field holds nothing an offer could be read
    from: no Offer entity (schema.org `Offer` or a subtype) and no candidate for any `money` field, from any collector.
    A render may hold what the page's scripts fill in (owner #49, D-1202). A page that fails to read is never one.
    `config` is the site's active config, whose candidates count as the collectors' do; `parsed` is the bundle's
    parse when the caller has one (INV-26)."""
    money = {name for name, spec in schema.fields.items() if spec.type is FieldType.MONEY}
    if schema.page_kind != "detail" or not any(schema.fields[name].required for name in money):
        return False
    try:
        page = _Page.read(_Source(bundle, schema, data, parsed, config))
    except Exception:  # §4.14: the extraction that follows reports the failure
        log.exception(_FAILED)
        return False
    if any(page.graph.is_a(entity, OFFER) for entity in page.graph.entities.values()):
        return False
    return not any(candidate.field in money for candidate in page.candidates)


def lacks_rows(extraction: ExtractionResult) -> bool:
    """Whether a reached listing's extraction (structured rows, the site's config's rows, role C's) gave no rows: a
    render may hold the rows the page's scripts fill in (owner #54, D-1246). A failed extraction gave none (D-1248), so
    a render whose extraction fails is never kept over the HTTP page."""
    return not extraction.rows
