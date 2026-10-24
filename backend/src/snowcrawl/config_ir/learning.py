"""The learning pipeline: from a state's stored pages to a validated config, without a database.

The sample is the stored pages with the most published required values, the rest are held out (`split`). Induction
proposes selectors without an LLM, role A synthesizes the fields it left, and the config is validated on the held-out
pages, with an API recipe when one is learned and validated. A `Locate` request also renders the surface's newest
stored pages and adds the fields it locates (`_located`). What a `learn` job does around this, from starting the job to
activating the config, is `learn_job`.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from typing import Final

from pydantic import JsonValue
from sqlalchemy.exc import SQLAlchemyError

from snowcrawl.acquire.types import RequestContext
from snowcrawl.collect.vocabulary import Vocabulary
from snowcrawl.config_ir.absent import ABSENT, absent_fields
from snowcrawl.config_ir.api_recipe.learn import learn_recipe
from snowcrawl.config_ir.api_recipe.replay import Render, Replays
from snowcrawl.config_ir.api_recipe.validate import RecipeValidated, attach, refused
from snowcrawl.config_ir.held_out import StoredPage
from snowcrawl.config_ir.induction import Induction, SamplePage, induce, page_level
from snowcrawl.config_ir.listing_induction import ListingInduction, induce_listing, row_fields
from snowcrawl.config_ir.locate import (
    LOCATE_SAMPLES,
    Calls,
    Extract,
    ListingRecipe,
    Sampled,
    locate,
    located_config,
    sampled,
)
from snowcrawl.config_ir.model import NEXT_PAGE_FIELD, ExtractionConfigIR, Fetch, Provenance, SchemaRef
from snowcrawl.config_ir.synthesis import synthesize
from snowcrawl.config_ir.validation import Facts, HeldOutPage, Validated, validate, with_unlearned
from snowcrawl.core.engine_version import ENGINE_VERSION
from snowcrawl.db.models import ConfigOrigin, FetchMethod, JobId
from snowcrawl.llm.client import LLMClient, LLMFailure
from snowcrawl.schemas.types import SchemaDef, document_digest

log = logging.getLogger(__name__)

# Of the 8 pages a run reads, five are the learning sample and the rest are held out.
SAMPLE_PAGES: Final = 5
# A validation report reason stays short: it is a table cell in the config view, not a log.
REASON_CHARS: Final = 200


@dataclass(frozen=True, slots=True)
class Target:
    """What a run learns a config for: the schema, the site's host and fetch method, and the job role A is charged
    to."""

    schema: SchemaDef
    host: str
    fetch: FetchMethod
    job_id: JobId


@dataclass(frozen=True, slots=True)
class Learn:
    """A request to learn a config for `target` from the state's stored `pages`, most recent first."""

    target: Target
    pages: Sequence[StoredPage]


@dataclass(frozen=True, slots=True)
class Locate:
    """A request to learn as `learn` does, then locate `fields` (none named: the page-level fields the config does not
    read, and a listing's row fields when it reads no rows) on the surface's rendered pages. `surface` are the
    surface's stored pages, `serving` the config it serves, and `context` the request context of the job that asked."""

    learn: Learn
    fields: Sequence[str]
    surface: Sequence[StoredPage]
    serving: ExtractionConfigIR | None
    context: RequestContext | None


@dataclass(frozen=True, slots=True)
class Hooks:
    """What a run sends and renders with: recipe replays, browser renders, and the extraction of a render. Without
    `replay`, a run learns no API recipe; without `render` and `extract`, it locates nothing."""

    replay: Replays | None
    render: Render | None = None
    extract: Extract | None = None


async def learned(
    client: LLMClient, request: Learn | Locate, vocabulary: Vocabulary, max_chars: int, hooks: Hooks
) -> Validated:
    """The config learned from the request's sample and validated on its held-out pages, with its API recipe, and the
    fields a `Locate` request located. `max_chars` is role A's HTML limit per page."""
    learn = request.learn if isinstance(request, Locate) else request
    target = learn.target
    sample, held_out = split(target.schema, learn.pages)
    validated = await learn_config(
        client, target, sample, [page.held_out for page in held_out], vocabulary, max_chars, absent_from=learn.pages
    )
    # A recipe enters a validated config only (`attach`), so nothing is replayed for a refused one.
    if validated.ir is not None and hooks.replay is not None:
        validated = attach(validated, await _page_recipe(client, target, sample, held_out, hooks.replay, hooks.render))
    if isinstance(request, Locate):
        validated = await _locate_step(client, request, validated, vocabulary, hooks)
    return validated


def split(schema: SchemaDef, pages: Sequence[StoredPage]) -> tuple[list[StoredPage], list[StoredPage]]:
    """The learning sample, the `SAMPLE_PAGES` pages with the most published required values (the most recent first
    on a tie), and the held-out pages, the rest."""
    required = {name for name, spec in schema.fields.items() if spec.required}

    def published(page: StoredPage) -> int:
        entities = (page.sample.published, *page.sample.rows)
        return sum(len(required.intersection(entity)) for entity in entities)

    ranked = sorted(pages, key=published, reverse=True)  # stable: `pages` are most recent first
    return ranked[:SAMPLE_PAGES], ranked[SAMPLE_PAGES:]


async def _locate_step(
    client: LLMClient, request: Locate, validated: Validated, vocabulary: Vocabulary, hooks: Hooks
) -> Validated:
    """`validated` with the fields the request located; unchanged when the locate step fails: its error refuses
    the located fields, not the config learning validated (as a recipe's does); unchanged too when the run cannot
    render."""
    if hooks.render is None or hooks.extract is None:
        return validated
    try:
        rendered = await _samples(request, hooks.render, hooks.extract)
        return await _located(client, request, validated, vocabulary, rendered, hooks)
    except (LLMFailure, SQLAlchemyError):
        raise  # the run's own failures, as `_page_recipe` re-raises them
    except Exception:
        log.exception("learn job %s: locate failed", request.learn.target.job_id)
        return validated


async def _page_recipe(
    client: LLMClient,
    target: Target,
    sample: Sequence[StoredPage],
    held_out: Sequence[StoredPage],
    replay: Replays,
    render: Render | None,
) -> RecipeValidated:
    """The API recipe that serves the pages, or why there is none."""
    try:
        return await learn_recipe(
            client, sample, held_out, target.schema, replay(target.job_id), job_id=target.job_id, render=render
        )
    except (LLMFailure, SQLAlchemyError):
        # The run's own failures: role D's ends the run as role A's does, and a database error would leave a
        # replay's usage unaccounted, so the run ends failed.
        raise
    except Exception as e:
        # The recipe learner's own error refuses the recipe, not the config it would have joined.
        log.exception("learn job %s: recipe learning failed", target.job_id)
        return refused(f"recipe_error: {type(e).__name__}")


async def _samples(request: Locate, render: Render, extract: Extract) -> list[Sampled]:
    """The surface's `LOCATE_SAMPLES` newest stored pages rendered, each with what its render published."""
    target = request.learn.target
    pages: list[Sampled] = []
    for page in request.surface[:LOCATE_SAMPLES]:
        bundles = await render(page.bundle.manifest.url, target.schema.page_kind)
        if bundles:
            extraction = await extract(bundles[0], target.schema, target.job_id)
            pages.append(await asyncio.to_thread(sampled, page, bundles[0], extraction))
    return pages


async def _located(
    client: LLMClient,
    request: Locate,
    validated: Validated,
    vocabulary: Vocabulary,
    pages: Sequence[Sampled],
    hooks: Hooks,
) -> Validated:
    """`validated` with the fields the request asks for located on the rendered `pages` (`locate`), and why each other
    one was not."""
    target = request.learn.target
    schema = target.schema
    base = validated.ir or request.serving or _induced(target, Induction(), ListingInduction())[0]
    # A listing whose config reads no rows (no listing, no listing recipe) has its rows located too.
    rowless = schema.page_kind == "listing" and base.listing is None and base.api_recipe is None
    names = list(request.fields) or [
        *(
            name
            for name, spec in schema.fields.items()
            if page_level(schema, name) and not spec.row_mapped and name not in base.fields
        ),
        *(row_fields(schema) if rowless else ()),
    ]
    if not names:
        return validated
    replay = None if hooks.replay is None else hooks.replay(target.job_id)
    calls = None if replay is None else Calls(client, replay, target.job_id, request.context)
    recipe = _listing_recipe(client, request, validated, hooks, pages)
    located = await locate(base, schema, names, pages, vocabulary, calls, recipe)
    return with_unlearned(located_config(validated, base, located), located.reasons)


def _listing_recipe(
    client: LLMClient, request: Locate, validated: Validated, hooks: Hooks, rendered: Sequence[Sampled]
) -> ListingRecipe | None:
    """A listing's `call` tier: its recipe, learned from the surface's pages as `_page_recipe` learns one, a page that
    listed nothing with the rows its render published (`rendered`), which the recipe's calls are matched with; None
    when the run already tried (a config validated) or cannot replay."""
    if validated.ir is not None or hooks.replay is None:
        return None
    target = request.learn.target
    rows = {page.stored.held_out.capture_id: page.rows for page in rendered if not page.stored.held_out.rows}
    pages = [_with_rows(page, rows.get(page.held_out.capture_id, ())) for page in request.surface]
    sample, held_out = split(target.schema, pages)
    return partial(_page_recipe, client, target, sample, held_out, hooks.replay, hooks.render)


def _with_rows(page: StoredPage, rows: Sequence[Mapping[str, JsonValue]]) -> StoredPage:
    """`page` with `rows` as its published rows, when it has any."""
    if not rows:
        return page
    facts = tuple(Facts(published=dict(row)) for row in rows)
    return replace(page, held_out=replace(page.held_out, rows=facts))


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
    # A field no page stated has no value to learn a step from; the config lists it instead.
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
    # Fields an adapter or API recipe maps keep coming from it: they need no steps.
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
    role A runs for what a record needs, not for an optional field alone."""
    required = {name for name, spec in schema.fields.items() if spec.required}
    return bool(required - covered) or any(not covered.intersection(group) for group in schema.required_groups)


def learnable(schema: SchemaDef) -> tuple[SchemaDef, dict[str, str]]:
    """The schema learning learns steps for, and why each other field gets none. A row-mapped field gets none
    (`row_field`): induction generalizes one locator per field per page, and a row field needs a row
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
    # A config whose fields an adapter maps is the adapter's.
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
