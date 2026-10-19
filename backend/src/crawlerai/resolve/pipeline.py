"""The extraction pipeline (resolution spec): one capture and one schema in,
every field's outcome out. `extract_page` is the one function the worker and the replay harness run (evaluation spec).

A page that was not served (`blocked`, `shell`, `not_found`, `error`) yields its block class as the outcome and nothing
else (INV-11). A served page is parsed once (INV-26); every collector reads that one parse, then resolution runs its
stages in order: ownership and intent, preference, derivations, evidence and confidence. A detail page's required fields
still missing after that go to role C once, and its candidates are resolved with the others. A listing's rows are its
stated rows (structured data's, `resolve.listing`, else the config's, else its captured calls') and the blocks of its
repeated items, bound into one row per item by the item layer (`collect.items.bind`, listings spec); each row resolves
its row-scoped fields, the page its page-scoped ones, and the next-page candidates are listed (§4.12). Role C is asked
once for the row fields a listing's block rows lack and for its missing page fields (listings spec, "Role C rows").
Resolution never publishes part of a page: if it raises, the outcome is `error` and no field is set (§4.14).

With the site's active config (learning-configs spec) a page is extracted in `config` mode: the config's
executor reads the same parse, its candidates enter resolution with the collectors' (in the bucket of the config
field's status, §10), and role C is asked only for fields the config does not run. A listing's rows are the structured
data's when it gives any, else the config's; role C never adds rows beside a config that runs row fields.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Final, Protocol, cast

from pydantic import BaseModel, ConfigDict

from crawlerai.collect.base import ARRAY_ROW, Candidate, Entity
from crawlerai.collect.config import ConfigExecutor
from crawlerai.collect.currencies import with_page_declarations
from crawlerai.collect.items.bind import Listing, RowBlock, bind
from crawlerai.collect.items.lines import BlockText, block_texts
from crawlerai.collect.run import Adapters, Collected, collect_page
from crawlerai.collect.schema_org_map import VOCABULARY_FILE, Vocabulary, canonical_urls, item_url_fields
from crawlerai.content.context import page_context
from crawlerai.content.metadata import canonical_link
from crawlerai.content.page import ParsedPage
from crawlerai.content.state import holds_state
from crawlerai.core.capture import BlockClass
from crawlerai.core.engine_version import CALIBRATION_FILE
from crawlerai.db.models import ExtractionMode, SourceKind
from crawlerai.normalize.base import Context
from crawlerai.resolve.derive import Derived, fill, is_page_url_field
from crawlerai.resolve.evidence import Calibration, assess, assess_fields, load_calibration
from crawlerai.resolve.intent import AmbiguousTarget, primary_types, select_target
from crawlerai.resolve.listing import listing_rows
from crawlerai.resolve.ownership import OFFER, EntityGraph
from crawlerai.resolve.page_state import out_of_stock, render_could_show, was_rendered
from crawlerai.resolve.pagination import next_page_candidate, next_page_links
from crawlerai.resolve.preference import (
    PRECEDENCE_FILE,
    PRECEDENCE_TYPES,
    Chosen,
    Orders,
    PageFacts,
    Preference,
    Resolver,
    intent_ambiguous,
    load_precedence,
)
from crawlerai.resolve.records import is_complete, record_confidence
from crawlerai.resolve.row_keys import keyed_rows
from crawlerai.resolve.rows import RowField, resolve_rows
from crawlerai.resolve.types import ExtractionResult, FieldSet, LLMCallRecord, Outcome, Probability
from crawlerai.schemas.types import FieldSpec, FieldType, SchemaDef, Scope
from crawlerai.storage.capture_bundle import CaptureBundle

log = logging.getLogger(__name__)
_FAILED = "extraction failed"
# The reason of a `missing` field the active config lists as absent (`config_ir.absent`, D-1341).
ABSENT: Final = "absent"

# D-0486: without a `source_precedence.yaml` no source kind is ranked, so text, long_text, url and image_url fields
# decline as `unranked` rather than follow an unmeasured order (C7). The repo commits resolution spec's order (D-0444).
UNRANKED: Orders = dict.fromkeys(PRECEDENCE_TYPES, ())
# INV-11: a capture whose block class is not `ok` is the page's outcome, with no candidates.
_NOT_SERVED: Mapping[BlockClass, Outcome] = {
    "blocked": "blocked",
    "shell": "shell",
    "not_found": "not_found",
    "auth_wall": "auth_wall",
    "soft_404": "soft_404",
    "geo_redirect": "geo_redirect",
    "redirected_to_listing": "redirected_to_listing",
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
    calibration, the active adapters, and the request's `min_confidence`: a calibrated bucket below it abstains
    (None: every chosen value publishes with its confidence)."""

    vocabulary: Vocabulary
    orders: Orders
    calibration: Calibration | None
    adapters: Adapters | None = None
    min_confidence: Probability | None = None

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

    def with_min_confidence(self, min_confidence: Probability | None) -> "EngineData":
        """This data for a request that asks values of at least `min_confidence` (None: no minimum)."""
        return replace(self, min_confidence=min_confidence)

    def pin(self) -> PinnedData:
        return PinnedData(orders=dict(self.orders), calibration=self.calibration)

    def pinned(self, pin: PinnedData) -> "EngineData":
        """This data with `pin`'s orders and calibration in place of its own."""
        return replace(self, orders=pin.orders, calibration=pin.calibration)


@dataclass(frozen=True, slots=True)
class GapRequest:
    """The fields of `target` that resolution left missing, for role C to read from the page text (llm spec, "When role
    C is asked")."""

    page: ParsedPage
    schema: SchemaDef
    ctx: Context
    target: Entity
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GapReply:
    """Role C's grounded candidates (`source_kind='llm'`, owned by the target) and the calls it made. `failure` is
    set when its call gave no valid reply (llm spec): the asked fields then stay `missing` with it as their
    reason. `diagnostics` join the page's (values dropped as ungrounded, truncation)."""

    candidates: tuple[Candidate, ...]
    llm_calls: tuple[LLMCallRecord, ...]
    failure: str | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ListingGapRequest:
    """Listings spec, "Role C rows": the `blocks` whose rows lack row fields (each with the fields to fill), and the
    page entity's `page_missing` fields, for role C to read from the page text."""

    page: ParsedPage
    schema: SchemaDef
    ctx: Context
    blocks: tuple[BlockText, ...]
    page_missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ListingGapReply(GapReply):
    """A listing's `GapReply`: `candidates` are owned by the blocks' rows or by the page entity. `failure`, the page
    fields' call's, leaves the asked page fields `missing` with it."""


class RoleC(Protocol):
    """The LLM hook (§4.13), filled by llm spec's role C; the caller binds the LLM client."""

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
    missing = _missing(schema, fields, page.config.covered)
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
    fields = await _unpublished_reasons(source, page.page, _absent(fields, page.config.absent))
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
    page_urls: tuple[str, ...]  # the request, final and canonical URLs, canonicalized (variants spec)

    @classmethod
    def read(cls, source: _Source) -> "_Page":
        """The page read from `source`; the one read already from the same parse for the same capture, schema, engine
        data and config, when there is one (`ParsedPage.derived`)."""
        page = ParsedPage.of(source.bundle) if source.parsed is None else source.parsed
        key = (source.bundle.manifest, source.schema, source.data, source.config)
        derived = page.derived.get(cls)
        if derived is not None and all(a is b for a, b in zip(derived[0], key, strict=True)):
            return cast(_Page, derived[1])
        read = cls._read(source, page)
        page.derived[cls] = (key, read)
        return read

    @classmethod
    def _read(cls, source: _Source, page: ParsedPage) -> "_Page":
        manifest, schema, data = source.bundle.manifest, source.schema, source.data
        ctx = page_context(
            page, manifest.final_url, manifest.fetched_at, request_url=manifest.url, headers=manifest.headers.response
        )
        ctx = with_page_declarations(ctx, page)
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
        """Preference (§4.7, §4.8) for `target`, derivations, then evidence and confidence. `page_values`: whether
        page-level candidates are the target's (`EntityGraph.owned_by`); `detail`: whether `target` is a detail page's,
        with the variant it shows, its variant fill and row-mapped fields (variants spec)."""
        schema = self.schema
        decisions: dict[str, Preference | Derived]
        rows: FieldSet = {}
        if isinstance(target, AmbiguousTarget):
            decisions = dict(intent_ambiguous(schema, candidates))
        else:
            resolver = Resolver(
                self.graph, target, self.facts, self.data.orders, page_values, detail=detail, confident=self._confident
            )
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
            if detail:
                rows = self._rows(target, candidates)
        return self._assess(decisions) | rows

    def _confident(self, name: str, spec: FieldSpec, chosen: Chosen) -> bool:
        """Whether a chosen value of the field publishes at the request's `min_confidence` (`resolve.evidence`)."""
        outcome = assess(
            spec.type,
            chosen,
            self.data.calibration,
            min_confidence=self.data.min_confidence,
            corroborated=name in self.config.corroborated,
        )
        return outcome.status == "published"

    def _assess(self, decisions: Mapping[str, Preference | Derived]) -> FieldSet:
        return assess_fields(
            self.schema,
            decisions,
            self.data.calibration,
            corroborated=self.config.corroborated,
            min_confidence=self.data.min_confidence,
        )

    def _rows(self, target: Entity, candidates: Sequence[Candidate]) -> FieldSet:
        """A detail target's row-mapped fields, resolved row by row (variants spec)."""
        return {
            name: resolve_rows(
                RowField(
                    name=name,
                    spec=spec,
                    graph=self.graph,
                    target=target,
                    page=self.facts,
                    orders=self.data.orders,
                    calibration=self.data.calibration,
                    min_confidence=self.data.min_confidence,
                    page_urls=self.page_urls,
                    variant_params=self.collected.variant_params,
                ),
                candidates,
            )
            for name, spec in self.schema.fields.items()
            if spec.row_mapped
        }


def _read_and_resolve(source: _Source) -> tuple[_Page, FieldSet]:
    page = _Page.read(source)
    return page, page.resolve(page.candidates)


# Why a listing gave no rows, as `no_rows: <cause>` (rest-api spec, "Scrape outcomes, not errors, for page failures"):
# structured data, the config, the captured calls and the item layer gave none, so role C, which fills the rows of
# blocks, was not asked for rows.
NO_ROWS: Final = "no_rows"
NOT_ASKED: Final = "not_asked"


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
    entities: tuple[Entity, ...] = ()  # the rows' entities, in `rows` order
    blocks: tuple[RowBlock, ...] = ()  # the rows' blocks, in the bound group's order

    @classmethod
    def read(cls, source: _Source) -> "_Listing":
        page = _Page.read(source)
        links = next_page_links(page.page, source.bundle.manifest.final_url)
        diagnostics = list(page.diagnostics)
        found = next_page_candidate(links, page.schema, page.ctx, diagnostics)
        candidates = (*page.candidates, *(() if found is None else (found,)))
        # learning-configs spec: the config's rows serve only where structured data gives none. Its row candidates
        # belong to its own row entities, so structured and config values never meet in one row.
        row_fields = {name for name, spec in page.schema.fields.items() if spec.scope == "row"}
        holders = frozenset(c.entity_id for c in page.collected.candidates if c.field in row_fields)
        structured = listing_rows(page.graph, page.primary, page.target, holders)
        # Appendix A #59: the rows of the page's captured calls are the stated rows where structured data and the
        # config give none; the rows of its state JSON where no source, blocks included, gives any (listings spec,
        # "Rows from page state"): their candidates join only then.
        stated = structured or page.config.rows or page.collected.rows
        # A config's row selector was validated against every item (learning-configs spec), so its rows stand alone.
        items = () if not structured and page.config.rows else page.collected.items
        if not stated and not items and page.collected.state.rows:
            stated = page.collected.state.rows
            candidates = (*candidates, *page.collected.state.candidates)
        # The item layer (listings spec, "Stated rows and blocks"): the blocks of the page's repeated items are the rows
        # where the stated rows are none or stubs, and extend them; state and call array rows bind to the rows by URL.
        bound = bind(
            Listing(
                page.page,
                page.ctx,
                page.schema,
                page.page_urls,
                items,
                stated,
                tuple(e for e in page.graph.entities.values() if ARRAY_ROW in e.types),
                candidates,
                partial(_holder, page.graph),
            )
        )
        diagnostics.extend(bound.diagnostics)
        fields, resolved = page.resolve_listing(bound.candidates, bound.rows)
        next_pages = tuple(link.url for link in links)
        return cls(
            page,
            fields,
            resolved,
            next_pages,
            bound.candidates,
            tuple(diagnostics),
            entities=bound.rows,
            blocks=bound.blocks,
        )

    def gap(self) -> ListingGapRequest | None:
        """The role C request (listings spec, "Role C rows"): the blocks whose rows lack row fields, each with the
        fields its row lacks, and the missing page fields when a required one is among them (`_gaps`); none of them a
        field the config runs, and no block beside a config that runs a row field (role C's values could not join its
        rows)."""
        schema = self.page.schema
        covered = self.page.config.covered
        row_fields = tuple(name for name, spec in schema.fields.items() if spec.scope == "row")
        blocks = () if covered.intersection(row_fields) else self._blocks(row_fields)
        page_missing = _gaps(schema, self.fields, covered)
        if not blocks and not page_missing:
            return None
        return ListingGapRequest(self.page.page, schema, self.page.ctx, blocks, page_missing)

    def _blocks(self, row_fields: Sequence[str]) -> tuple[BlockText, ...]:
        """The blocks whose rows lack a row field role C can claim, asked when some row lacks a required one or one is
        published on no row: never the item URL, the block's link, which its text does not show, nor an object."""
        schema = self.page.schema
        rows = dict(zip((entity.id for entity in self.entities), self.rows, strict=True))
        askable = _askable(schema, row_fields)
        lacking = {
            block.row: [name for name in askable if not _published(rows[block.row], name)] for block in self.blocks
        }
        unpublished = any(not any(_published(row, name) for row in self.rows) for name in askable)
        required = {name for name in askable if schema.fields[name].required}
        if not unpublished and not any(required.intersection(names) for names in lacking.values()):
            return ()
        return block_texts(self.page.page, self.blocks, lacking)

    def with_reply(self, reply: ListingGapReply, asked: tuple[str, ...]) -> "_Listing":
        """The listing with role C's candidates, owned by the blocks' rows and the page entity: the rows and the page
        fields resolve again with them."""
        candidates = (*self.candidates, *reply.candidates)
        fields, rows = self.page.resolve_listing(candidates, self.entities)
        if reply.failure is not None:
            fields = _unanswered(fields, asked, reply.failure)
        diagnostics = (*self.diagnostics, *reply.diagnostics)
        return replace(
            self, fields=fields, rows=rows, candidates=candidates, diagnostics=diagnostics, llm_calls=reply.llm_calls
        )

    def _records(self) -> list[FieldSet]:
        # Each row's record holds the page's fields too (`resolve.records.assemble_listing`).
        return [{**self.fields, **row} for row in self.rows]

    def _complete(self) -> bool:
        records = self._records()
        return bool(records) and all(is_complete(self.page.schema, record) for record in records)

    def result(self, mode: ExtractionMode) -> ExtractionResult:
        schema = self.page.schema
        keyed, session = keyed_rows(self.rows, item_url_fields(schema), self.page.page_urls)
        listing = replace(self, rows=keyed)
        records = listing._records()
        return ExtractionResult(
            outcome="extracted" if listing._complete() else "partial",
            entity=self.fields,
            rows=keyed,
            candidates=self.candidates,
            llm_calls=self.llm_calls,
            mode=mode,
            record_confidence=_least_confident(record_confidence(schema, record) for record in records),
            diagnostics=self.diagnostics,
            next_pages=self.next_pages,
            reason=None if self.rows else no_rows(NOT_ASKED),
            session_params=session,
        )


async def _extract_listing(source: _Source, role_c: RoleC | None, mode: ExtractionMode) -> ExtractionResult:
    try:
        listing = await asyncio.to_thread(_Listing.read, source)
    except Exception:  # §4.14, as for a detail page
        log.exception(_FAILED)
        return _result("error", mode)
    if role_c is not None and (request := await asyncio.to_thread(listing.gap)) is not None:
        reply = await role_c.listing(request)
        try:
            listing = await asyncio.to_thread(listing.with_reply, reply, request.page_missing)
        except Exception:
            log.exception(_FAILED)
            candidates = (*listing.candidates, *reply.candidates)
            diagnostics = (*listing.diagnostics, *reply.diagnostics)
            return _result("error", mode, candidates=candidates, llm_calls=reply.llm_calls, diagnostics=diagnostics)
    return listing.result(mode)


def _holder(graph: EntityGraph, candidate: Candidate) -> str:
    """The entity whose row fields `candidate` fills: its owner, or the item an Offer it is in offers (schema.org
    `offers`; atomic offers, resolution spec)."""
    owner = graph.owner_of(candidate)
    return owner.parent if owner.parent is not None and graph.is_a(owner, OFFER) else owner.id


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


def _missing(schema: SchemaDef, fields: FieldSet, covered: frozenset[str]) -> tuple[str, ...]:
    """The fields role C is asked for on a detail page (llm spec, "When role C is asked"), in schema order: every
    `missing` field, optional ones included, that the active config does not run, never a conflict or an abstention.
    An `object` field, and a list of objects (a row-mapped field included), is never asked: a claim is one verbatim
    span or element (llm spec, "Role C input, claims and candidates"), which cannot hold typed sub-fields."""
    return tuple(
        name
        for name, outcome in fields.items()
        if outcome.status == "missing" and name not in covered and not _holds_objects(schema.fields[name])
    )


def _gaps(schema: SchemaDef, fields: FieldSet, covered: frozenset[str]) -> tuple[str, ...]:
    """A listing's page fields role C is asked for (listings spec, "Role C rows"): the `_missing` ones, only when a
    required one is among them: a required field, or a member of a required group that no member fills yet."""
    published = {name for name, outcome in fields.items() if outcome.status == "published"}
    unmet = {name for group in schema.required_groups if not published.intersection(group) for name in group}
    missing = _missing(schema, fields, covered)
    if not any(schema.fields[name].required or name in unmet for name in missing):
        return ()
    return missing


def _askable(schema: SchemaDef, row_fields: Sequence[str]) -> list[str]:
    """The row fields role C can claim in a block: not the item URL, the block's link, which its text does not show,
    nor an object, whose sub-fields one verbatim span cannot hold."""
    urls = frozenset(item_url_fields(schema))
    return [name for name in row_fields if name not in urls and not _holds_objects(schema.fields[name])]


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


async def _unpublished_reasons(source: "_Source", page: ParsedPage, fields: FieldSet) -> FieldSet:
    """What the page's own evidence says of its unpublished fields (`page_state` module): a price missing from a page
    that states its item is not for sale is `out_of_stock`; a field missing from a page that was not rendered and whose
    document carries its data for its script to render (`content.state.holds_state`) is `interaction_required`
    (resolution spec): a render may show it, which a request asks for with `render_fields` (acquisition spec, "Browser
    on evidence"). A rendered page, or a field the outcome explains, stays `missing`."""
    fields = out_of_stock(source.schema, fields)
    rendered = was_rendered(source.bundle.manifest)
    holds = not rendered and await asyncio.to_thread(holds_state, page)
    return render_could_show(fields, rendered=rendered, holds_state=holds)


def _unanswered(fields: FieldSet, asked: tuple[str, ...], failure: str) -> FieldSet:
    """The fields after a role C call that gave no reply: each asked field still `missing` says why (llm spec)."""
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
