"""Operator corrections (learning-configs spec, C5): a site is fixed with data, through `PUT /v1/configs/{id}`, not with
code.

A correction replaces a field's steps, removes a field (`null`), or confirms a field's steps as they are. Every field
it touches becomes `operator`; the others keep their steps and status. The result is a new `operator` config that has
not been validated yet: the yields and validities of the version it came from are cleared, and the caller validates it
on held-out pages (§4.7) before anything activates.
"""

from collections.abc import Mapping

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from crawlerai.config_ir.model import ExtractionConfigIR, FieldSteps, Step
from crawlerai.schemas.types import Name, SchemaDef


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CorrectedSteps(_Model):
    steps: list[Step] = Field(min_length=1)


class Correction(_Model):
    """The body of `PUT /v1/configs/{id}`: steps per field (`null` removes the field), and fields whose steps the
    operator confirms."""

    fields: dict[Name, CorrectedSteps | None] = {}
    confirm: list[Name] = []

    def operated(self) -> set[str]:
        """The fields the operator gave steps or confirmed: those that must survive validation to activate."""
        return {name for name, steps in self.fields.items() if steps is not None} | set(self.confirm)


class InvalidCorrection(ValueError):
    """The correction does not fit the config or its schema; `errors` are (dotted path in the body, reason) pairs,
    `""` for the whole body."""

    def __init__(self, errors: list[tuple[str, str]]) -> None:
        super().__init__("the correction does not fit the config")
        self.errors = errors


def correct(
    ir: ExtractionConfigIR, schema: SchemaDef, correction: Correction, *, engine_version: str, at: AwareDatetime
) -> ExtractionConfigIR:
    """`ir` with `correction` applied, as an `operator` config to validate. Raises `InvalidCorrection`."""
    _check(ir, schema, correction)
    page, rows = dict(ir.fields), dict(ir.listing.fields) if ir.listing is not None else {}
    for name, corrected in correction.fields.items():
        fields = rows if _in_rows(ir, schema, name) else page
        if corrected is None:
            del fields[name]
        else:
            fields[name] = FieldSteps(steps=corrected.steps, status="operator")
    for name in correction.confirm:
        fields = rows if _in_rows(ir, schema, name) else page
        fields[name] = fields[name].model_copy(update={"status": "operator"})
    listing = ir.listing.model_copy(update={"fields": _unmeasured(rows)}) if ir.listing is not None else None
    provenance = ir.provenance.model_copy(
        update={"origin": "operator", "validated_on": [], "learned_at": at, "engine_version": engine_version}
    )
    # A field given steps is no longer absent (D-1341): the operator found where the site states it.
    absent = [name for name in ir.absent if correction.fields.get(name) is None]
    update = {"fields": _unmeasured(page), "listing": listing, "provenance": provenance, "absent": absent}
    corrected_ir = ir.model_copy(update=update)
    # `model_copy` skips validation; the round trip runs the IR's validators on the corrected document.
    return ExtractionConfigIR.model_validate(corrected_ir.model_dump(by_alias=True))


def _is_row_field(schema: SchemaDef, name: str) -> bool:
    """A row field of a listing schema (schemas spec `scope`)."""
    return schema.page_kind == "listing" and schema.fields[name].scope == "row"


def _in_rows(ir: ExtractionConfigIR, schema: SchemaDef, name: str) -> bool:
    """Whether `name`'s steps run relative to each row of `ir`'s listing."""
    return ir.listing is not None and _is_row_field(schema, name)


def _unmeasured(fields: Mapping[str, FieldSteps]) -> dict[str, FieldSteps]:
    # The held-out yield and validity belong to the version that was validated; the new one is measured afresh.
    return {name: steps.model_copy(update={"yield_": None, "validity": None}) for name, steps in fields.items()}


def _check(ir: ExtractionConfigIR, schema: SchemaDef, correction: Correction) -> None:
    if not correction.fields and not correction.confirm:
        raise InvalidCorrection([("", "a correction changes or confirms at least one field")])
    configured = set(ir.fields) | (set(ir.listing.fields) if ir.listing is not None else set())
    errors: list[tuple[str, str]] = []
    for name, corrected in correction.fields.items():
        reason = _field_problem(ir, schema, name, removing=corrected is None, configured=configured)
        if reason is not None:
            errors.append((f"fields.{name}", reason))
    for name in correction.confirm:
        if name in correction.fields:
            errors.append((f"confirm.{name}", "the field is also corrected"))
        elif name not in configured:
            errors.append((f"confirm.{name}", "the config has no steps to confirm"))
    if errors:
        raise InvalidCorrection(errors)


def _field_problem(
    ir: ExtractionConfigIR, schema: SchemaDef, name: str, *, removing: bool, configured: set[str]
) -> str | None:
    if name not in schema.fields:
        return f"not a field of schema {schema.name}"
    if removing:
        return None if name in configured else "the config has no steps to remove"
    if _is_row_field(schema, name) and ir.listing is None:
        return "a row field needs the config's listing row selector"
    return None
