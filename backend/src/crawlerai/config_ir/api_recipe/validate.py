"""Held-out validation of an API recipe (SPEC-09 §4.7, ARCHITECTURE §7.2 step 3): replay the recipe for each held-out
page and compare every mapped field with the value the engine published from the page's browser capture, the bar
SPEC-08 §4.7 sets for a config.

A recipe is accepted only whole: every field of its map must reproduce on every held-out page where the engine
published it, and be published on at least one. An accepted recipe carries its proof and enters the validated config
with its report; the config's `fetch.method` is left as it is, since the recipe is the acquisition's API rung, not a
fetch method (§4.7, §4.8).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from crawlerai.config_ir.api_recipe.headers import Proven
from crawlerai.config_ir.api_recipe.model import ApiRecipe, BoundBy, Proof
from crawlerai.config_ir.api_recipe.replay import Replay, ReplayPage, compare
from crawlerai.config_ir.validation import MIN_HELD_OUT, RecipeFieldReport, RecipeReport, Validated
from crawlerai.db.models import CaptureId
from crawlerai.schemas.types import SchemaDef


@dataclass(frozen=True, slots=True)
class HeldOutReplay:
    """A held-out browser capture: its id, which the proof lists, and the page as replay reads it."""

    capture_id: CaptureId
    page: ReplayPage


@dataclass(frozen=True, slots=True)
class RecipeValidated:
    """The accepted recipe with its proof; None when it did not validate (`report.refused`)."""

    recipe: ApiRecipe | None
    report: RecipeReport


async def validate_recipe(
    proven: Proven,
    bound_by: BoundBy,
    fields: Mapping[str, str],
    held_out: Sequence[HeldOutReplay],
    schema: SchemaDef,
    replay: Replay,
) -> RecipeValidated:
    """Replays `proven.spec` for each held-out page, in order, and accepts it with the `fields` map when every field
    reproduces on every page that published it (§4.7)."""
    captures = [item.capture_id for item in held_out]
    enough = len(held_out) >= MIN_HELD_OUT
    pages = [await compare(proven.spec, fields, item.page, schema, replay) for item in held_out] if enough else []
    reports = {
        name: RecipeFieldReport(
            published=sum(name in page for page in pages), reproduced=sum(page.get(name, False) for page in pages)
        )
        for name in fields
        if enough
    }
    refused = _refused(reports) if enough else "too_few_held_out"
    report = RecipeReport(held_out=captures, fields=reports, refused=refused)
    if refused is not None:
        return RecipeValidated(None, report)
    proof = Proof(validated_on=captures, headers_tried=proven.headers_tried, bound_by=bound_by)
    return RecipeValidated(ApiRecipe(**proven.spec.model_dump(), map=dict(fields), proof=proof), report)


def refused(reason: str) -> RecipeValidated:
    """A recipe refused before held-out validation (binding, role D or header minimization), with `reason`."""
    return RecipeValidated(None, RecipeReport(held_out=[], fields={}, refused=reason))


def _refused(reports: Mapping[str, RecipeFieldReport]) -> str | None:
    if unpublished := [name for name, report in reports.items() if report.published == 0]:
        return "never_published: " + ", ".join(unpublished)
    if failed := [name for name, report in reports.items() if report.reproduced < report.published]:
        return "not_reproduced: " + ", ".join(failed)
    return None


def attach(validated: Validated, recipe: RecipeValidated) -> Validated:
    """The validated config with the recipe's report in its `validation_report`, and the recipe as its `api_recipe`
    when it was accepted; a recipe never enters a config that did not validate, or without its own validation."""
    report = validated.report.model_copy(update={"api_recipe": recipe.report})
    ir = validated.ir
    if ir is not None and recipe.recipe is not None:
        ir = ir.model_copy(update={"api_recipe": recipe.recipe})
    return Validated(ir, report)
