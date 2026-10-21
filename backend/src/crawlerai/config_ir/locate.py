"""The locate run (learning-configs spec, "Locate run"): where the fields a surface's HTTP pages leave missing live,
found on browser renders of its stored pages and written into its config as field sources.

A learning run on a surface whose render mode locates (`locate`, `always`), or one a job's `render` started
(`progressive.request_locate`), renders up to `LOCATE_SAMPLES` of the stored pages it reads in the browser with network
capture; their HTTP captures are kept beside them (step 1). Each render is extracted as a page is (the collectors,
resolution and role C, grounded: `Extract`), and what it publishes is the run's oracle (step 2); a field no render
publishes is `not_found_in_render`.

For each field, the first render that published it gives the candidate steps: the value is induced in every source
document that holds it (`induction.source_steps`, step 3). Each step is validated as a learning run validates steps
(`validation.validate`, both executors) on at least `MIN_LOCATE_HELD_OUT` other sample pages that published the field
(#332's rule for role C finds, every source now), on each tier's pages (step 4):
- `http`: a step of a document the HTML carries (any source but a captured call), on the pages' HTTP captures;
- `call`: a step of a captured call, on the HTTP captures joined with the answer of the call's API recipe replayed over
  HTTP (`validation.replayed`). The recipe is discovered on the renders' calls and its headers proven by replay
  (`api_recipe.discovery`, `api_recipe.learn.prove`); a header the caller's request context supplies is kept as a
  reference to it, never as a value;
- `browser`: a step of a document the HTML carries, on the renders.

The cheapest tier whose step validated wins (`http` < `call` < `browser`, step 5), written with `FieldSteps.needs` and,
for `call`, the recipe it names in the config's `recipes`; a field that validated nowhere stays out (`not_located`).

A listing's rows follow the same tiers when its config reads none (no listing, no listing recipe), on the rows the
renders published: rows in a JSON document the HTML carries become a `jsonpath` row step (`json_rows`), and rows of
the render's item blocks a listing induced on it (`listing_induction`); each candidate is validated as `http` on the
other pages' HTTP captures, else as `browser` on their renders, its row fields written with that `needs`. Between them
is `call`: the listing recipe of the renders' call series, with its pagination (`api_recipe.learn`, which the run
gives as `Rows.recipe`), served as the config's `api_recipe`.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, get_args

from pydantic import JsonValue

from crawlerai.acquire.types import RequestContext
from crawlerai.collect.vocabulary import Vocabulary
from crawlerai.config_ir.api_recipe.binding import Sample, page_data
from crawlerai.config_ir.api_recipe.discovery import DiscoverySample, discover
from crawlerai.config_ir.api_recipe.learn import prove
from crawlerai.config_ir.api_recipe.model import ApiRecipe, Proof, RequestSpec
from crawlerai.config_ir.api_recipe.replay import Replay, ReplayPage
from crawlerai.config_ir.api_recipe.validate import RecipeValidated
from crawlerai.config_ir.held_out import StoredPage, read_bundle
from crawlerai.config_ir.induction import Published, SamplePage, page_level, source_steps
from crawlerai.config_ir.json_rows import json_listings
from crawlerai.config_ir.listing_induction import induce_listing, row_fields
from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps, ListingSpec, Needs, Step
from crawlerai.config_ir.progressive import LOCATE_SAMPLES
from crawlerai.config_ir.validation import (
    Facts,
    FieldReport,
    HeldOutPage,
    ListingReport,
    Validated,
    replayed,
    validate,
)
from crawlerai.content.page import ParsedPage
from crawlerai.db.models import CaptureId, JobId
from crawlerai.llm.client import LLMClient
from crawlerai.normalize.base import Context
from crawlerai.resolve.types import ExtractionResult
from crawlerai.schemas.types import SchemaDef
from crawlerai.storage.capture_bundle import CaptureBundle

__all__ = [
    "LOCATE_SAMPLES",
    "MIN_LOCATE_HELD_OUT",
    "NOT_FOUND_IN_RENDER",
    "Calls",
    "Extract",
    "ListingRecipe",
    "Located",
    "Rows",
    "Sampled",
    "locate",
    "located_config",
    "sampled",
]

# A located step must reproduce the published value on at least two other sample pages: one page agreeing could be a
# coincidence of its layout (#332).
MIN_LOCATE_HELD_OUT: Final = 2
NOT_FOUND_IN_RENDER: Final = "not_found_in_render"
NOT_LOCATED: Final = "not_located"
_TIERS: Final[tuple[Needs, ...]] = get_args(Needs)  # cheapest first

# Extracts a rendered capture for a schema as a page is extracted (`resolve.pipeline.extract_page`, role C charged to
# the job): the locate run's oracle.
Extract = Callable[[CaptureBundle, SchemaDef, JobId], Awaitable[ExtractionResult]]
# Learns the listing recipe of the run's pages (`api_recipe.learn.learn_recipe`): a listing's `call` tier.
ListingRecipe = Callable[[], Awaitable[RecipeValidated]]


@dataclass(frozen=True)
class Sampled:
    """A sample page of a locate run: its stored HTTP capture, its render parsed with its context, and the page-level
    values the render published, and a listing's rows'."""

    stored: StoredPage
    render: CaptureBundle
    page: ParsedPage
    ctx: Context
    published: Mapping[str, JsonValue]
    rows: Sequence[Mapping[str, JsonValue]] = ()

    def held_out(self, name: str, *, rendered: bool) -> HeldOutPage:
        """The page as validation reads it for `name`: its render or its HTTP capture, with the render's value."""
        page = self.stored.held_out
        facts = Facts(published={name: self.published[name]})
        if rendered:
            return HeldOutPage(page.capture_id, self.page, self.ctx, facts)
        return HeldOutPage(page.capture_id, page.page, page.ctx, facts)

    def held_out_rows(self, *, rendered: bool) -> HeldOutPage:
        """The page as validation reads a listing's rows: its render or its HTTP capture, with the render's rows."""
        page = self.stored.held_out
        facts = Facts(published=self.published)
        rows = [Facts(published=row) for row in self.rows]
        if rendered:
            return HeldOutPage(page.capture_id, self.page, self.ctx, facts, rows)
        return HeldOutPage(page.capture_id, page.page, page.ctx, facts, rows)


def sampled(stored: StoredPage, render: CaptureBundle, extraction: ExtractionResult) -> Sampled:
    """The sample page of `stored` rendered as `render`, which `extraction` extracted."""
    page, ctx = read_bundle(render)
    entity = extraction.entity or {}
    published = {name: outcome.value for name, outcome in entity.items() if outcome.status == "published"}
    rows = [{name: o.value for name, o in row.items() if o.status == "published"} for row in extraction.rows]
    return Sampled(stored, render, page, ctx, published, rows)


@dataclass(frozen=True)
class Calls:
    """What a `call` source's recipe is proven with: role D's client (an ambiguous binding), the run's replay, its job,
    and the caller's request context, whose headers a recipe may reference."""

    client: LLMClient
    replay: Replay
    job_id: JobId
    context: RequestContext | None = None


@dataclass(frozen=True)
class Located:
    """The located fields with their chosen steps, the recipes their `call` sources name, and each one's validation
    report; every tier each field validated in (`sources`), and why each other asked field was not located."""

    fields: dict[str, FieldSteps] = field(default_factory=dict)
    recipes: dict[str, ApiRecipe] = field(default_factory=dict)
    reports: dict[str, FieldReport] = field(default_factory=dict)
    sources: dict[str, dict[Needs, FieldSteps]] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    validated_on: dict[CaptureId, None] = field(default_factory=dict)  # the pages the chosen steps validated on
    rows: "Rows | None" = None  # a listing's rows, when asked


@dataclass(frozen=True)
class Rows:
    """A listing's located rows: the listing (`http` or `browser` row fields) with its report, or the listing recipe
    (`call`); else why none."""

    listing: ListingSpec | None = None
    report: ListingReport | None = None
    recipe: RecipeValidated | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _Run:
    base: ExtractionConfigIR
    schema: SchemaDef
    vocabulary: Vocabulary
    calls: Calls | None


async def locate(
    base: ExtractionConfigIR,
    schema: SchemaDef,
    names: Sequence[str],
    pages: Sequence[Sampled],
    vocabulary: Vocabulary,
    calls: Calls | None,
    recipe: ListingRecipe | None = None,
) -> Located:
    """Locate `names` on `pages` (module docstring); `base` gives the config's identity (site, schema, fetch). Without
    `calls`, no `call` source is tried; a listing's rows are located when `names` holds a row field, their `call` tier
    by `recipe`."""
    run = _Run(base, schema, vocabulary, calls)
    located = Located()
    listed = [name for name in names if schema.page_kind == "listing" and name in row_fields(schema)]
    for name in names:
        if name not in listed:
            await _page_field(run, name, pages, located)
    if not listed:
        return located
    rows = await _locate_rows(run, pages, recipe)
    if rows.listing is None and rows.recipe is None:
        located.reasons.update(dict.fromkeys(listed, rows.reason or NOT_LOCATED))
    else:
        held = [page.stored.held_out.capture_id for page in pages if page.rows][1:]
        located.validated_on.update(dict.fromkeys(held))
    return replace(located, rows=rows)


async def _page_field(run: _Run, name: str, pages: Sequence[Sampled], located: Located) -> None:
    schema = run.schema
    if name not in schema.fields or not page_level(schema, name) or schema.fields[name].row_mapped:
        located.reasons[name] = NOT_LOCATED
        return
    with_value = [page for page in pages if page.published.get(name) is not None]
    if not with_value:
        located.reasons[name] = NOT_FOUND_IN_RENDER
        return
    await _locate_field(run, name, with_value, located)


async def _locate_rows(run: _Run, pages: Sequence[Sampled], recipe: ListingRecipe | None) -> Rows:
    """The listing's rows on `pages` (module docstring), the cheapest tier that validated."""
    with_rows = [page for page in pages if page.rows]
    if not with_rows:
        return Rows(reason=NOT_FOUND_IN_RENDER)
    if len(with_rows) <= MIN_LOCATE_HELD_OUT:
        return Rows(reason="too_few_held_out")
    candidates = await asyncio.to_thread(_row_candidates, run, with_rows[0])
    others = with_rows[1:]
    if (http := await asyncio.to_thread(_validated_rows, run, candidates, "http", others)) is not None:
        return http
    if recipe is not None and (found := await recipe()).recipe is not None:
        return Rows(recipe=found)
    if (browser := await asyncio.to_thread(_validated_rows, run, candidates, "browser", others)) is not None:
        return browser
    return Rows(reason=NOT_LOCATED)


def _row_candidates(run: _Run, first: Sampled) -> list[ListingSpec]:
    """The listings the first render's rows propose: in its JSON documents, then in its item blocks."""
    found = json_listings(first.page, first.ctx, run.schema, first.rows)
    rows = [{name: Published(value, "") for name, value in row.items()} for row in first.rows]
    induced = induce_listing(run.schema, [SamplePage(first.page, first.ctx, {}, rows)], run.vocabulary).listing
    return [*found, *([induced] if induced is not None else [])]


def _validated_rows(
    run: _Run, candidates: Sequence[ListingSpec], needs: Needs, pages: Sequence[Sampled]
) -> Rows | None:
    """The first candidate whose rows validate for `needs` on `pages`, its row fields written with `needs`."""
    held_out = [page.held_out_rows(rendered=needs == "browser") for page in pages]
    for listing in candidates:
        ir = run.base.model_copy(update={"fields": {}, "listing": listing, "recipes": {}, "api_recipe": None})
        validated = validate(ir, run.schema, held_out, run.vocabulary, min_held_out=MIN_LOCATE_HELD_OUT)
        kept = validated.ir.listing if validated.ir is not None else None
        if kept is not None:
            fields = {name: steps.model_copy(update={"needs": needs}) for name, steps in kept.fields.items()}
            return Rows(kept.model_copy(update={"fields": fields}), validated.report.listing)
    return None


async def _locate_field(run: _Run, name: str, pages: Sequence[Sampled], located: Located) -> None:
    first, others = pages[0], pages[1:]
    if len(others) < MIN_LOCATE_HELD_OUT:
        located.reasons[name] = "too_few_held_out"
        return
    value = first.published[name]
    # Induction and validation parse and run the pages: off the event loop.
    found = await asyncio.to_thread(source_steps, first.page, first.ctx, run.schema, run.vocabulary, name, value)
    in_html = [step for source, steps in found.items() if source != "xhr" for step in steps]
    recipe, by_call = await _call_tier(run, name, found.get("xhr", []), pages)
    validated: dict[Needs, tuple[FieldSteps, FieldReport] | None] = {
        "http": await asyncio.to_thread(_validated, run, name, in_html, "http", others),
        "call": by_call,
        "browser": await asyncio.to_thread(_validated, run, name, in_html, "browser", others),
    }
    tiers: dict[Needs, tuple[FieldSteps, FieldReport]] = {
        needs: kept for needs, kept in validated.items() if kept is not None
    }
    if not tiers:
        located.reasons[name] = NOT_LOCATED
        return
    located.sources[name] = {needs: steps for needs, (steps, _) in tiers.items()}
    needs = next(needs for needs in _TIERS if needs in tiers)
    located.fields[name], located.reports[name] = tiers[needs]
    located.validated_on.update(dict.fromkeys(page.stored.held_out.capture_id for page in others))
    if needs == "call" and recipe is not None:
        _add_recipe(located, name, recipe)


def _add_recipe(located: Located, name: str, recipe: ApiRecipe) -> None:
    """`recipe` named `name`; or, when a field located before calls the same request, that field's recipe reading
    this field too, so the fetch sends one companion call per endpoint (acquisition spec, "Data calls")."""
    request = set(RequestSpec.model_fields)
    shared = next(
        (n for n, r in located.recipes.items() if r.model_dump(include=request) == recipe.model_dump(include=request)),
        None,
    )
    if shared is None:
        located.recipes[name] = recipe
        return
    held = located.recipes[shared]
    located.recipes[shared] = held.model_copy(update={"map": {**held.map, **recipe.map}})
    located.fields[name] = located.fields[name].model_copy(update={"call": shared})


def _validated(
    run: _Run,
    name: str,
    steps: Sequence[Step],
    needs: Needs,
    pages: Sequence[Sampled],
    recipe: ApiRecipe | None = None,
    held_out: Sequence[HeldOutPage] | None = None,
) -> tuple[FieldSteps, FieldReport] | None:
    """The first of `steps` that validates for `needs` on `pages` (their HTTP captures, renders for `browser`, or
    `held_out` as given), as the field's steps with their validation report."""
    if held_out is None:
        held_out = [page.held_out(name, rendered=needs == "browser") for page in pages]
    for step in steps:
        call = None if recipe is None else name
        steps_of = FieldSteps(steps=[step], status="uncorroborated", needs=needs, call=call)
        ir = run.base.model_copy(
            update={"fields": {name: steps_of}, "listing": None, "recipes": {} if recipe is None else {name: recipe}}
        )
        validated = validate(ir, run.schema, held_out, run.vocabulary, min_held_out=MIN_LOCATE_HELD_OUT)
        report = validated.report.fields.get(name)
        if validated.ir is not None and name in validated.ir.fields and report and report.published >= len(held_out):
            return validated.ir.fields[name], report
    return None


async def _call_tier(
    run: _Run, name: str, steps: Sequence[Step], pages: Sequence[Sampled]
) -> tuple[ApiRecipe | None, tuple[FieldSteps, FieldReport] | None]:
    """The recipe of the call that carries `name`, and the first of its `steps` validated on its replayed answers."""
    calls = run.calls
    if not steps or calls is None or (recipe := await _recipe(run, calls, name, pages)) is None:
        return None, None
    return recipe, await _validated_call(run, calls, name, steps, recipe, pages[1:])


async def _validated_call(
    run: _Run, calls: Calls, name: str, steps: Sequence[Step], recipe: ApiRecipe, pages: Sequence[Sampled]
) -> tuple[FieldSteps, FieldReport] | None:
    """A captured call's step validated on the HTTP captures joined with the recipe's answer, replayed over HTTP."""
    held_out: list[HeldOutPage] = []
    for page in pages:
        joined = await replayed(
            page.held_out(name, rendered=False), page.stored.bundle, recipe, calls.replay, calls.context
        )
        if joined is None:
            return None  # the recipe must reproduce the value without the browser on every page
        held_out.append(joined)
    return await asyncio.to_thread(_validated, run, name, steps, "call", pages, recipe, held_out)


async def _recipe(run: _Run, calls: Calls, name: str, pages: Sequence[Sampled]) -> ApiRecipe | None:
    """The API recipe of the call that carries `name` on every render, bound from the HTTP pages' URLs and documents
    (as serving binds it) with the headers its replay proved; None when there is none."""
    asked = run.schema.model_copy(
        update={"fields": {name: run.schema.fields[name].model_copy(update={"required": True})}, "required_groups": []}
    )
    samples = [DiscoverySample(page.render, {name: page.published[name]}, page.ctx) for page in pages]
    endpoints = await asyncio.to_thread(discover, samples, asked)
    if not endpoints:
        return None
    endpoint = endpoints[0]
    fields = {name: endpoint.map[name]}
    replays = [
        ReplayPage(
            Sample(page.stored.bundle.manifest.url, request, page_data(page.stored.held_out.page)),
            {name: page.published[name]},
            page.ctx,
            context=calls.context,
        )
        for page, request in zip(pages, endpoint.requests, strict=True)
    ]
    bound = await prove(calls.client, fields, replays, asked, calls.replay, calls.job_id)
    if isinstance(bound, str):
        return None
    proven, bound_by = bound
    proof = Proof(
        validated_on=[page.stored.held_out.capture_id for page in pages],
        headers_tried=proven.headers_tried,
        bound_by=bound_by,
    )
    return ApiRecipe(**proven.spec.model_dump(), map=fields, proof=proof)


def located_config(validated: Validated, base: ExtractionConfigIR, located: Located) -> Validated:
    """`validated` (the run's learned config; else `base`, the config the surface serves or an empty one) with the
    located fields and their recipes, origin `located`, and their reports; unchanged when nothing was located."""
    rows = located.rows or Rows()
    if not located.fields and rows.listing is None and rows.recipe is None:
        return validated
    ir = validated.ir or base
    report = validated.report
    provenance = ir.provenance.model_copy(
        update={"origin": "located", "validated_on": ir.provenance.validated_on or list(located.validated_on)}
    )
    merged = ir.model_copy(
        update={
            "fields": {**ir.fields, **located.fields},
            "recipes": {**ir.recipes, **located.recipes},
            "listing": rows.listing or ir.listing,
            "api_recipe": rows.recipe.recipe if rows.recipe is not None else ir.api_recipe,
            "provenance": provenance,
        }
    )
    # A field re-located off its call drops that recipe. `model_copy` skips validation; the round trip runs the
    # IR's validators on the merged document.
    merged = merged.model_copy(update={"recipes": merged.named_recipes()})
    checked = ExtractionConfigIR.model_validate(merged.model_dump(by_alias=True))
    update: dict[str, object] = {"fields": {**report.fields, **located.reports}, "refused": None}
    if rows.report is not None:
        update["listing"] = rows.report
    if rows.recipe is not None:
        update["api_recipe"] = rows.recipe.report
    return Validated(checked, report.model_copy(update=update))
