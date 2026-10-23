"""The `platform_draft` export: a config as XPath 1.0, regex and JSONPath steps for
an external crawler platform whose own format is not known yet (OPEN_QUESTIONS #1), so every export says `draft: true`.

Each field keeps its steps in order, since the first valid value wins and a field reduced to one selector would
export something other than what the engine runs. A CSS step is exported as its XPath translation, which is what the
executors run, and an `attr` step as the XPath attribute step `@name` (XPath 1.0 §2.5), which reads the same attribute
of the context node: the row in a listing, the root element on a page. The release executor runs both steps the same
way (a CSS step by its XPath, `attr` as the context node's attribute), so the release check of the IR is the check of
the draft. A field the release check marks `manual` is exported with `manual: true`. An `api_recipe` is
exported as stored, since held-out validation replayed it, and with its PHP code hint (`php_hint`).
XPath steps run in PHP 8.4 on the HTML Standard parse of the page (`xpath_document`). Regexes are in the portable
subset (`portable_regex`) and run with PHP's `/u` modifier (`regex_flags`). Exports carry selectors only, never values.
"""

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from crawlerai.config_ir.api_recipe.model import ApiRecipe
from crawlerai.config_ir.exporters.php_hint import php_hint
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
from crawlerai.config_ir.release_check import ReleaseField, ReleaseListing, ReleaseReport
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
    # The PHP 8.4 document every XPath step runs on, with `new Dom\XPath($document)`: the HTML Standard parse,
    # the tree the engine and the release check read, so a step selects the same element there. `HTML_NO_DEFAULT_NS`
    # leaves HTML elements in no namespace, as lxml has them, so an unprefixed name test (XPath 1.0 §2.3) matches them;
    # `LIBXML_NOERROR` keeps parse errors, which the HTML Standard recovers from, out of PHP's warnings.
    xpath_document: Literal["Dom\\HTMLDocument::createFromString($html, LIBXML_NOERROR | Dom\\HTML_NO_DEFAULT_NS)"] = (
        "Dom\\HTMLDocument::createFromString($html, LIBXML_NOERROR | Dom\\HTML_NO_DEFAULT_NS)"
    )
    ir_version: Literal["1"]
    site: str
    schema_: SchemaRef = Field(alias="schema")
    page_kind: PageKind
    fetch: Fetch
    fields: dict[str, DraftField]
    listing: DraftListing | None
    api_recipe: ApiRecipe | None
    api_recipe_php: str | None


def platform_draft(ir: ExtractionConfigIR, report: ReleaseReport) -> PlatformDraft:
    """The draft of `ir`, with the `manual` marks of its release check `report`."""
    listing = None
    if ir.listing is not None and report.listing is not None:
        listing = _listing(ir.listing, report.listing)
    return PlatformDraft(
        ir_version=ir.ir_version,
        site=ir.site,
        schema_=ir.schema_,
        page_kind=ir.page_kind,
        fetch=ir.fetch,
        fields=_draft_fields(ir.fields, report.fields),
        listing=listing,
        api_recipe=ir.api_recipe,
        api_recipe_php=None if ir.api_recipe is None else php_hint(ir.api_recipe),
    )


def _step(step: Step) -> Step:
    match step:
        case CssStep():
            return XPathStep(xpath=step.xpath, post=step.post)
        case AttrStep():
            return XPathStep(xpath=f"@{step.attr}", post=step.post)
        case _:
            return step


def _draft_field(steps: Sequence[Step], report: ReleaseField) -> DraftField:
    return DraftField(steps=[_step(step) for step in steps], manual=report.manual)


def _draft_fields(fields: dict[str, FieldSteps], report: dict[str, ReleaseField]) -> dict[str, DraftField]:
    return {name: _draft_field(steps.steps, report[name]) for name, steps in fields.items()}


def _listing(listing: ListingSpec, report: ReleaseListing) -> DraftListing:
    row = _step(listing.row)
    row_xpath = row.xpath if isinstance(row, XPathStep) else None
    draft_next = None
    if listing.next is not None and report.next is not None:
        draft_next = _draft_field([listing.next], report.next)
    return DraftListing(row_xpath=row_xpath, fields=_draft_fields(listing.fields, report.fields), next=draft_next)
