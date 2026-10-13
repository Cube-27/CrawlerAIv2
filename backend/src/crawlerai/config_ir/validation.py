"""Held-out validation and corroboration (SPEC-08 §4.7, ARCHITECTURE §8.3 steps 3, 4): which fields of a learned config
may activate, each field's status, and the `validation_report` that drift (§4.9) measures against.

Both executors run the config on every held-out page. A field is kept only if, on every page where the engine
published it, the config matches it and the engine executor and the independent release executor (§12.3) both give
the published value (`equal`), and every value it matches on any page is valid by its normalizer. A single-valued
field that matches more than once is invalid (§4.3), so "exactly one match" is part of validity. A field the engine
published on no held-out page cannot be checked and is dropped. A listing keeps its rows only if `row` selects at
least 3 on every page; its row fields are checked row by row against the engine's rows, in document order.

A kept field is `corroborated` when the config's values equal the structured-data or adapter values on the comparable
held-out pages (§8.3 step 4); a field an operator confirmed or corrected stays `operator`.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from crawlerai.collect.base import PAGE, Candidate
from crawlerai.collect.schema_org_map import Vocabulary
from crawlerai.config_ir.executor import EngineExecutor, row_id
from crawlerai.config_ir.model import NEXT_PAGE_FIELD, ExtractionConfigIR, FieldSteps, ListingSpec, Ratio, Step
from crawlerai.config_ir.release_executor import Released, ReleasePage, Value, release_run
from crawlerai.config_ir.release_rules import release_rules
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import CaptureId, FieldStatus
from crawlerai.normalize.base import Context, Ok
from crawlerai.normalize.dispatch import equal, normalize
from crawlerai.schemas.types import FieldSpec, SchemaDef

# ARCHITECTURE §8.3: at least three pages are held out, a listing has at least 3 rows, and a field needs at least 3
# comparable pages to be corroborated; its values must match on every comparable page while there are fewer than 10,
# and on at least 90% from 10 on.
MIN_HELD_OUT: Final = 3
MIN_ROWS: Final = 3
MIN_COMPARABLE: Final = 3
EVERY_PAGE_BELOW: Final = 10
CORROBORATION_SHARE: Final = Fraction(9, 10)


@dataclass(frozen=True, slots=True)
class Facts:
    """What the engine stored for one entity of a held-out page (the page, or one listing row): the value it published
    for each field, and for each field the valid values its structured collectors or an adapter proposed, which
    corroboration compares the config with (§8.3 step 4)."""

    published: Mapping[str, JsonValue] = field(default_factory=dict)
    references: Mapping[str, Sequence[JsonValue]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HeldOutPage:
    """A held-out capture: its parsed page and context, the page entity's facts, and a listing's rows in document
    order."""

    capture_id: CaptureId
    page: ParsedPage
    ctx: Context
    facts: Facts
    rows: Sequence[Facts] = ()


class _Report(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True)


class FieldReport(_Report):
    """One field on the held-out pages. `pages`: held-out pages; `matched`/`valid`: pages where the config matched and
    where every match was valid; `published`/`reproduced`: pages where the engine published the field and where both
    executors gave that value; `comparable`/`corroborated_on`: pages with a structured or adapter value and where the
    config's value equals it. `status` is None for a dropped field, with the check it failed in `dropped`."""

    pages: int
    matched: int
    valid: int
    published: int
    reproduced: int
    comparable: int
    corroborated_on: int
    status: FieldStatus | None
    yield_: Ratio = Field(alias="yield")
    validity: Ratio | None
    dropped: str | None = None


class ListingReport(_Report):
    """`rows_ok`: held-out pages where `row` selected at least `MIN_ROWS` rows; when some page has fewer, the listing is
    dropped (`dropped`) and its fields with it."""

    rows_ok: int
    fields: dict[str, FieldReport]
    next: FieldReport | None
    dropped: str | None = None


class RecipeFieldReport(_Report):
    """One field of an API recipe's map (SPEC-09 §4.7). `published`: held-out pages where the engine published the
    field; `reproduced`: those where the replayed response gave that value."""

    published: int
    reproduced: int


class RecipeReport(_Report):
    """The API recipe's held-out validation (SPEC-09 §4.7). `refused` says why the recipe did not enter the config."""

    held_out: list[CaptureId]
    fields: dict[str, RecipeFieldReport]
    refused: str | None = None


class ValidationReport(_Report):
    """The `extraction_config.validation_report` (SPEC-08 §4.7). `refused` says why nothing can activate; `api_recipe`
    is the recipe's validation when the site has one (SPEC-09 §4.7)."""

    held_out: list[CaptureId]
    fields: dict[str, FieldReport]
    listing: ListingReport | None
    refused: str | None = None
    api_recipe: RecipeReport | None = None


@dataclass(frozen=True, slots=True)
class Validated:
    """The config to activate, with only its kept fields, their statuses, yields and validities, and the held-out
    captures in `provenance.validated_on`; None when nothing may activate (`report.refused`)."""

    ir: ExtractionConfigIR | None
    report: ValidationReport


def validate(
    ir: ExtractionConfigIR, schema: SchemaDef, held_out: Sequence[HeldOutPage], vocabulary: Vocabulary
) -> Validated:
    """Validate `ir` on `held_out` (§4.7). It activates only with at least `MIN_HELD_OUT` pages and one kept field."""
    captures = [page.capture_id for page in held_out]
    if len(held_out) < MIN_HELD_OUT:
        return Validated(None, ValidationReport(held_out=captures, fields={}, listing=None, refused="too_few_held_out"))
    executor = EngineExecutor(ir, vocabulary)
    runs = [_PageRun.of(executor, schema, page) for page in held_out]
    fields, page_reports = _check_fields(ir.fields, schema, runs, _page_slots)
    listing, listing_report = _check_listing(ir.listing, schema, runs)
    kept = len(fields) + (len(listing.fields) if listing is not None else 0)
    report = ValidationReport(
        held_out=captures, fields=page_reports, listing=listing_report, refused=None if kept else "no_field_kept"
    )
    if not kept:
        return Validated(None, report)
    provenance = ir.provenance.model_copy(update={"validated_on": captures})
    validated = ir.model_copy(update={"fields": fields, "listing": listing, "provenance": provenance})
    # `model_copy` skips validation; the round trip runs the IR's validators on the pruned document.
    return Validated(ExtractionConfigIR.model_validate(validated.model_dump(by_alias=True)), report)


def corroboration(comparable: int, agreeing: int) -> FieldStatus:
    """§8.3 step 4: `corroborated` with at least `MIN_COMPARABLE` comparable pages, all agreeing while there are fewer
    than `EVERY_PAGE_BELOW`, and at least `CORROBORATION_SHARE` of them from then on."""
    if comparable < EVERY_PAGE_BELOW:
        held = comparable >= MIN_COMPARABLE and agreeing == comparable
    else:
        held = Fraction(agreeing, comparable) >= CORROBORATION_SHARE
    return "corroborated" if held else "uncorroborated"


# --- one page -------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PageRun:
    """Both executors' output on one held-out page: the engine's config candidates by owner and field."""

    page: HeldOutPage
    spec_of: Mapping[str, FieldSpec]
    candidates: Mapping[tuple[str, str], Candidate]
    rows: int
    released: Released

    @classmethod
    def of(cls, executor: EngineExecutor, schema: SchemaDef, page: HeldOutPage) -> "_PageRun":
        executed = executor.execute(page.page, schema, page.ctx)
        release_page = ReleasePage(page.page.html, page.page.network, page.ctx.base_url)
        return cls(
            page=page,
            spec_of=schema.fields,
            candidates={(c.entity_id, c.field): c for c in executed.candidates},
            rows=len(executed.rows),
            released=release_run(executor.ir, release_page, release_rules(schema, page.ctx)),
        )

    def released_value(self, values: Mapping[str, Value], name: str) -> JsonValue | None:
        """The release executor's value for `name`, normalized as the engine normalizes; None when it has none."""
        if name not in values:
            return None
        result = normalize(values[name], self.spec_of[name], self.page.ctx)
        return result.value if isinstance(result, Ok) else None


@dataclass(frozen=True, slots=True)
class _Slot:
    """One entity's view of one field: the engine's config candidate, the release executor's normalized value, the
    value the engine published (a field it did not publish has none) and the structured or adapter values."""

    candidate: Candidate | None
    released: JsonValue | None
    published: JsonValue | None
    references: Sequence[JsonValue]

    @property
    def value(self) -> JsonValue | None:
        """The engine executor's valid value."""
        if self.candidate is None or not isinstance(self.candidate.normalized, Ok):
            return None
        return self.candidate.normalized.value


def _slot(candidate: Candidate | None, released: JsonValue | None, facts: Facts, name: str) -> _Slot:
    return _Slot(candidate, released, facts.published.get(name), tuple(facts.references.get(name, ())))


type _SlotsOf = Callable[[_PageRun, str], tuple[list[_Slot], bool]]


def _page_slots(run: _PageRun, name: str) -> tuple[list[_Slot], bool]:
    """A page-level field has one slot, the page."""
    released = run.released_value(run.released.fields, name)
    return [_slot(run.candidates.get((PAGE, name)), released, run.page.facts, name)], True


def _row_slots(run: _PageRun, name: str) -> tuple[list[_Slot], bool]:
    """A row field has one slot per row, the config's n-th row against the engine's n-th; the rows align when both
    executors and the engine have as many."""
    facts, released = run.page.rows, run.released.rows
    slots = [
        _slot(
            run.candidates.get((row_id(n), name)),
            run.released_value(released[n], name) if n < len(released) else None,
            facts[n] if n < len(facts) else Facts(),
            name,
        )
        for n in range(max(run.rows, len(facts), len(released)))
    ]
    return slots, run.rows == len(facts) == len(released)


@dataclass(frozen=True, slots=True)
class _Seen:
    """One field on one held-out page."""

    matched: bool
    valid: bool
    published: bool
    reproduced: bool
    comparable: bool
    agrees: bool


def _seen(slots: Sequence[_Slot], aligned: bool, spec: FieldSpec) -> _Seen:
    candidates = [slot.candidate for slot in slots if slot.candidate is not None]
    published = [slot for slot in slots if slot.published is not None]
    referenced = [slot for slot in slots if slot.references]
    return _Seen(
        matched=bool(candidates),
        valid=all(isinstance(c.normalized, Ok) for c in candidates),
        published=bool(published),
        reproduced=aligned and all(_reproduces(slot, spec) for slot in published),
        comparable=bool(referenced),
        agrees=all(_agrees(slot, spec) for slot in referenced),
    )


def _reproduces(slot: _Slot, spec: FieldSpec) -> bool:
    # §8.3 step 3: the engine executor, and the independent release executor, give the value the engine published.
    value, released, published = slot.value, slot.released, slot.published
    if value is None or released is None or published is None:
        return False
    return equal(value, published, spec) and equal(released, published, spec)


def _agrees(slot: _Slot, spec: FieldSpec) -> bool:
    value = slot.value
    return value is not None and all(equal(value, reference, spec) for reference in slot.references)


# --- fields ---------------------------------------------------------------------------------------------------------


def _check_fields(
    fields: Mapping[str, FieldSteps], schema: SchemaDef, runs: Sequence[_PageRun], slots_of: _SlotsOf
) -> tuple[dict[str, FieldSteps], dict[str, FieldReport]]:
    """The fields that pass, with their status, yield and validity, and every field's report."""
    kept: dict[str, FieldSteps] = {}
    reports: dict[str, FieldReport] = {}
    for name, steps in fields.items():
        spec = schema.fields.get(name)
        seen = [] if spec is None else [_seen(*slots_of(run, name), spec) for run in runs]
        report = _report(seen, steps.status, len(runs), "not_in_schema" if spec is None else _dropped(seen))
        reports[name] = report
        if report.status is not None:
            update = {"status": report.status, "yield_": report.yield_, "validity": report.validity}
            kept[name] = steps.model_copy(update=update)
    return kept, reports


def _dropped(seen: Sequence[_Seen]) -> str | None:
    """The first §4.7 check the field fails, or None."""
    published = [s for s in seen if s.published]
    if not published:
        return "never_published"
    if not all(s.matched for s in published):
        return "no_match"
    if not all(s.valid for s in seen):
        return "invalid"
    if not all(s.reproduced for s in published):
        return "not_reproduced"
    return None


def _report(seen: Sequence[_Seen], status: FieldStatus, pages: int, dropped: str | None) -> FieldReport:
    matched = sum(s.matched for s in seen)
    valid = sum(s.matched and s.valid for s in seen)
    comparable = sum(s.comparable for s in seen)
    agreeing = sum(s.comparable and s.agrees for s in seen)
    kept_status: FieldStatus = "operator" if status == "operator" else corroboration(comparable, agreeing)
    return FieldReport(
        pages=pages,
        matched=matched,
        valid=valid,
        published=sum(s.published for s in seen),
        reproduced=sum(s.published and s.reproduced for s in seen),
        comparable=comparable,
        corroborated_on=agreeing,
        status=None if dropped else kept_status,
        yield_=matched / pages,  # §4.7: yield = matched / pages, validity = valid / matched
        validity=valid / matched if matched else None,
        dropped=dropped,
    )


# --- listings -------------------------------------------------------------------------------------------------------


def _check_listing(
    listing: ListingSpec | None, schema: SchemaDef, runs: Sequence[_PageRun]
) -> tuple[ListingSpec | None, ListingReport | None]:
    if listing is None:
        return None, None
    rows_ok = sum(run.rows >= MIN_ROWS for run in runs)
    fields, reports = _check_fields(listing.fields, schema, runs, _row_slots)
    next_step, next_report = _check_next(listing, schema, runs)
    dropped = None
    if rows_ok < len(runs):
        dropped = "too_few_rows"
    elif not fields:
        dropped = "no_field_kept"
    if dropped is not None:
        lost = {"status": None, "dropped": dropped}
        reports = {name: r if r.dropped else r.model_copy(update=lost) for name, r in reports.items()}
        return None, ListingReport(rows_ok=rows_ok, fields=reports, next=next_report, dropped=dropped)
    kept = listing.model_copy(update={"fields": fields, "next": next_step})
    return kept, ListingReport(rows_ok=rows_ok, fields=reports, next=next_report)


def _check_next(
    listing: ListingSpec, schema: SchemaDef, runs: Sequence[_PageRun]
) -> tuple[Step | None, FieldReport | None]:
    """`next` is checked as the page-level field it fills (ARCHITECTURE §5.3), and dropped when it fails."""
    if listing.next is None or NEXT_PAGE_FIELD not in schema.fields:
        return None, None
    steps = {NEXT_PAGE_FIELD: FieldSteps(steps=[listing.next], status="uncorroborated")}
    kept, reports = _check_fields(steps, schema, runs, _page_slots)
    return (listing.next if kept else None), reports[NEXT_PAGE_FIELD]
