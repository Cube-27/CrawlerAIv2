"""The `platform_draft` export (SPEC-08 §4.11, ARCHITECTURE §12.2): a config as XPath 1.0, regex and JSONPath steps for
an external crawler platform whose own format is not known yet (OPEN_QUESTIONS #1), so every export says `draft: true`.

Each field keeps its steps in order, since the first valid value wins (§12.1) and a field reduced to one selector would
export something other than what the engine runs. A CSS step is exported as its XPath translation, which is what the
executors run, and an `attr` step as the XPath attribute step `@name` (XPath 1.0 §2.5), which reads the same attribute
of the context node: the row in a listing, the root element on a page. `as_xpath` is that translation on the IR
itself, so the release check runs the steps the export carries. A field the release check marks `manual` (§12.3) is
exported with `manual: true`. An `api_recipe` is exported as stored: held-out validation replayed it (SPEC-09 §4.7),
and its PHP code hint is SPEC-09's (PR 7). Regexes are in the portable subset (`portable_regex`) and run with PHP's
`/u` modifier (`regex_flags`). Exports carry selectors only, never values (INV-27).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.model import (
    AttrStep,
    CssStep,
    ExtractionConfigIR,
    Fetch,
    FieldSteps,
    ListingSpec,
    SchemaRef,
    Step,
    XPathStep,
)
from crawlerai.config_ir.release_check import ReleaseField, ReleaseReport
from crawlerai.db.models import PageKind


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True)


class DraftField(_Model):
    steps: list[Step]
    manual: bool


class DraftListing(_Model):
    """`row_xpath` selects the rows (None when the row step is not XPath, and then every row field is `manual`)."""

    row_xpath: str | None
    fields: dict[str, DraftField]
    next: DraftField | None


class PlatformDraft(_Model):
    draft: Literal[True] = True
    # PHP PCRE pattern modifiers for every regex: `u`, UTF mode, in which `.` and classes match code points as in the
    # engine (`portable_regex`).
    regex_flags: Literal["u"] = "u"
    ir_version: Literal["1"]
    site: str
    schema_: SchemaRef = Field(alias="schema")
    page_kind: PageKind
    fetch: Fetch
    fields: dict[str, DraftField]
    listing: DraftListing | None
    api_recipe: ApiRecipe | None


def as_xpath(ir: ExtractionConfigIR) -> ExtractionConfigIR:
    """`ir` with its CSS and `attr` steps written as the XPath steps they run as."""
    listing = ir.listing
    if listing is not None:
        listing = listing.model_copy(
            update={
                "row": _step(listing.row),
                "fields": _fields(listing.fields),
                "next": None if listing.next is None else _step(listing.next),
            }
        )
    return ir.model_copy(update={"fields": _fields(ir.fields), "listing": listing})


def platform_draft(ir: ExtractionConfigIR, report: ReleaseReport) -> PlatformDraft:
    """The draft of `ir`, an IR `as_xpath` returned, with the `manual` marks of its release check `report`."""
    listing = None
    if ir.listing is not None and report.listing is not None:
        listing = _listing(ir.listing, report.listing.fields, report.listing.next)
    return PlatformDraft(
        ir_version=ir.ir_version,
        site=ir.site,
        schema_=ir.schema_,
        page_kind=ir.page_kind,
        fetch=ir.fetch,
        fields=_draft_fields(ir.fields, report.fields),
        listing=listing,
        api_recipe=ir.api_recipe,
    )


def _step(step: Step) -> Step:
    match step:
        case CssStep():
            return XPathStep(xpath=step.xpath, post=step.post)
        case AttrStep():
            return XPathStep(xpath=f"@{step.attr}", post=step.post)
        case _:
            return step


def _fields(fields: dict[str, FieldSteps]) -> dict[str, FieldSteps]:
    return {name: steps.model_copy(update={"steps": [_step(s) for s in steps.steps]}) for name, steps in fields.items()}


def _draft_fields(fields: dict[str, FieldSteps], report: dict[str, ReleaseField]) -> dict[str, DraftField]:
    return {name: DraftField(steps=steps.steps, manual=report[name].manual) for name, steps in fields.items()}


def _listing(listing: ListingSpec, report: dict[str, ReleaseField], next_: ReleaseField | None) -> DraftListing:
    row_xpath = listing.row.xpath if isinstance(listing.row, XPathStep) else None
    draft_next = None
    if listing.next is not None and next_ is not None:
        draft_next = DraftField(steps=[listing.next], manual=next_.manual)
    return DraftListing(row_xpath=row_xpath, fields=_draft_fields(listing.fields, report), next=draft_next)
