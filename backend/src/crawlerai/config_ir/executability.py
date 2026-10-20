"""How a learned config's fields execute (learning-configs, "Executability classes"): the input each field's steps
need, from the IR alone, so a config's release check and the learning simulation can say what running it takes.

A step reads one of: the page's HTML (an XPath, a CSS selector, a regex, an attribute of a row; a JSONPath into its
JSON-LD or the JSON in its inline scripts, HTML Standard: script elements), the responses a browser captured while it
rendered the page (`xhr`), or the response of an API call the config's recipe makes (`api`). A field with several
steps needs the most demanding of them, so a config whose fields are all `static-html` runs on a plain HTTP fetch.
"""

from collections import Counter
from typing import Final, Literal

from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps, JsonPathStep, Step

Executability = Literal["static-html", "needs-browser", "api-call", "unexecutable"]
# From the least to the most demanding; a field takes the class of its most demanding step.
CLASSES: Final[tuple[Executability, ...]] = ("static-html", "needs-browser", "api-call", "unexecutable")


def step_class(step: Step, *, has_recipe: bool) -> Executability:
    """The input one step needs. An `api` source needs the config's recipe: without one nothing serves it."""
    if not isinstance(step, JsonPathStep):
        return "static-html"
    match step.source:
        case "xhr":
            return "needs-browser"
        case "api":
            return "api-call" if has_recipe else "unexecutable"
        case "jsonld" | "js_state" | "attr":
            return "static-html"


def field_class(steps: FieldSteps, *, has_recipe: bool) -> Executability:
    """The class of a field: `unexecutable` when it is suspended (no executor runs it), else its steps' most
    demanding class."""
    if steps.status == "suspended":
        return "unexecutable"
    found = {step_class(step, has_recipe=has_recipe) for step in steps.steps}
    return max(found, key=CLASSES.index)


def config_classes(ir: ExtractionConfigIR) -> dict[str, Executability]:
    """The class of each of the config's fields: page fields by name, row fields as `listing:<name>`, and a
    listing's `next` as `listing:next` (a listing's row selector runs with the fields and is not listed)."""
    recipe = ir.api_recipe is not None
    classes: dict[str, Executability] = {
        name: field_class(steps, has_recipe=recipe) for name, steps in ir.fields.items()
    }
    listing = ir.listing
    if listing is not None:
        classes.update({f"listing:{n}": field_class(steps, has_recipe=recipe) for n, steps in listing.fields.items()})
        if listing.next is not None:
            classes["listing:next"] = step_class(listing.next, has_recipe=recipe)
    return classes


def class_counts(ir: ExtractionConfigIR | None) -> dict[Executability, int]:
    """How many of the config's fields are in each class, every class present; zeros without a config."""
    found = Counter(config_classes(ir).values()) if ir is not None else Counter()
    return {name: found[name] for name in CLASSES}
