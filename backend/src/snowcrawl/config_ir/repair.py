"""Recipe repair: the next version of a custom recipe a field of which drifted, proposed from the pages it serves.

A repair run (`learn_job`, a `learn` job whose request names the recipe, `progressive.request_learning(repair=)`)
reads the scope's stored pages whose URL one of the recipe's patterns matches, and learns an API recipe from them as
config learning does (`api_recipe.learn`: discovery, binding, header minimization, held-out validation), preferring
the recipe's own endpoint. The proposal is the recipe with its main call repaired:

- when the learned request is the recipe's (same method, URL template and body template), the engineer's request
  is kept whole, with its binders, headers and pagination; a drifted field the learned map reads gets the learned path;
- otherwise the call or one of its parameters changed: the learned request, as replay proved it, is the main call,
  reading the fields the learned map reads that no other kept source of the recipe gives.

A drifted page or extra-call field the learned main call reads moves into it (one source per field). Every other part
the engineer gave (patterns, warm-up, extra calls, page fields, who sends the calls, rate) is kept. A proposal that
changes nothing is refused. Nothing is stored here: the run stores the proposal `pending_approval` against the
recipe's pattern shape (`store_pending(shape=)`, in `activation`), and nothing applies before a person approves it.

`changes` lists what a proposal changes in its recipe, by the dotted path of each part of `CustomRecipe` that differs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, ConfigDict, JsonValue

from snowcrawl.config_ir.api_recipe.learn import learn_recipe
from snowcrawl.config_ir.api_recipe.model import ApiRecipe, RequestSpec
from snowcrawl.config_ir.custom_recipe import CustomRecipe
from snowcrawl.config_ir.held_out import StoredPage
from snowcrawl.config_ir.learning import Hooks, Target, split
from snowcrawl.config_ir.model import ExtractionConfigIR
from snowcrawl.config_ir.validation import RecipeReport, Validated, ValidationReport
from snowcrawl.core.engine_version import ENGINE_VERSION
from snowcrawl.llm.client import LLMClient
from snowcrawl.schemas.types import SchemaDef

NO_REPLAY: Final = "no_replay: the run cannot send requests, so no recipe can be proven"
UNCHANGED: Final = "unchanged: the learned call repairs no field of the recipe"


@dataclass(frozen=True, slots=True)
class Repair:
    """A request to repair the custom recipe `current` from the stored `pages` its patterns match, most recent
    first."""

    target: Target
    current: ExtractionConfigIR
    pages: Sequence[StoredPage]


async def repaired(client: LLMClient, request: Repair, hooks: Hooks) -> Validated:
    """The recipe's next version (module docstring), or why there is none. An LLM failure of role D propagates."""
    current, target = request.current, request.target
    main = current.api_recipe
    if main is None or not current.patterns:
        raise ValueError("a repair run repairs a custom recipe")
    if hooks.replay is None:
        return _refused(NO_REPLAY)
    sample, held_out = split(target.schema, request.pages)
    learned = await learn_recipe(
        client,
        sample,
        held_out,
        target.schema,
        hooks.replay(target.job_id),
        job_id=target.job_id,
        render=hooks.render,
        prefer=main,
    )
    if learned.recipe is None:
        return Validated(None, _report(learned.report))
    proposal = proposed(current, main, learned.recipe, target.schema)
    if proposal is None:
        return _refused(UNCHANGED, learned.report)
    return Validated(proposal, _report(learned.report))


def proposed(
    current: ExtractionConfigIR, main: ApiRecipe, learned: ApiRecipe, schema: SchemaDef
) -> ExtractionConfigIR | None:
    """`current`, a custom recipe with the main call `main`, with that call repaired from `learned`, a validated
    recipe (module docstring); None when that changes nothing."""
    recipe = CustomRecipe.from_ir(current, schema.id)
    drifted = {name for name, steps in current.fields.items() if steps.status == "suspended"}
    repaired_main = _main_call(main, learned, drifted, recipe.field_names() - set(main.map) - drifted)
    if repaired_main is None:
        return None
    main = repaired_main
    moved = set(main.map)
    calls = {
        name: call.model_copy(update={"map": kept})
        for name, call in recipe.calls.items()
        if (kept := {n: p for n, p in call.map.items() if n not in moved})
    }
    fields = {name: field for name, field in recipe.fields.items() if name not in moved}
    proposal = recipe.model_copy(update={"main": main, "calls": calls, "fields": fields})
    if proposal == recipe:
        return None
    ir = proposal.to_ir(schema, at=datetime.now(UTC), engine_version=ENGINE_VERSION)
    validated_on = [] if learned.proof is None else learned.proof.validated_on
    # The drifted fields no learned source repaired stay suspended.
    steps = {n: s.model_copy(update={"status": "suspended"}) if n in drifted else s for n, s in ir.fields.items()}
    provenance = ir.provenance.model_copy(update={"validated_on": validated_on})
    return ir.model_copy(update={"fields": steps, "provenance": provenance})


def _main_call(main: ApiRecipe, learned: ApiRecipe, drifted: set[str], others: set[str]) -> ApiRecipe | None:
    """The main call repaired from `learned` (module docstring), `others` being the fields the recipe's other kept
    sources give; None when the learned call reads none of the rest."""
    if _request(main) == _request(learned):
        repaired = {name: learned.map[name] for name in drifted & set(learned.map)}
        return main.model_copy(update={"map": {**main.map, **repaired}})
    # A call needs a field to read (an `ApiRecipe` map): one reading only what the kept sources give repairs nothing.
    if not (read := {n: p for n, p in learned.map.items() if n not in others}):
        return None
    return learned.model_copy(update={"map": read})


def _request(spec: RequestSpec) -> tuple[str, str, str | None]:
    return spec.method, spec.url, None if spec.body is None else spec.body.template


def _refused(reason: str, recipe: RecipeReport | None = None) -> Validated:
    report = ValidationReport(held_out=[], fields={}, listing=None, refused=reason, api_recipe=recipe)
    return Validated(None, report)


def _report(recipe: RecipeReport) -> ValidationReport:
    return ValidationReport(
        held_out=recipe.held_out, fields={}, listing=None, refused=recipe.refused, api_recipe=recipe
    )


class RecipeChange(BaseModel):
    """One part of a recipe a repair changes: its dotted path in the recipe (`main.map.title`, `main.url`,
    `calls.stock`), and its value before and after (None where it is not there)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    part: str
    before: JsonValue
    after: JsonValue


def changes(before: CustomRecipe, after: CustomRecipe) -> list[RecipeChange]:
    """What `after` changes in `before`, each changed part at its deepest path, in path order."""
    found: list[RecipeChange] = []
    _diff("", before.model_dump(mode="json"), after.model_dump(mode="json"), found)
    return sorted(found, key=lambda change: change.part)


def _diff(path: str, before: JsonValue, after: JsonValue, found: list[RecipeChange]) -> None:
    if before == after:
        return
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before.keys() | after.keys():
            _diff(f"{path}.{key}" if path else key, before.get(key), after.get(key), found)
        return
    found.append(RecipeChange(part=path, before=before, after=after))
